"""The gated Claude client (decisions 0202, 0207). A fake SDK object; offline; no key."""

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import anthropic
import pytest

from ntsb_probable_cause import sources
from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.memory import claude
from ntsb_probable_cause.scoring.budget import learning_month_spent


def _message(text: str | None, stop: str = "end_turn") -> SimpleNamespace:
    content = [SimpleNamespace(type="thinking", thinking="")]
    if text is not None:
        content.append(SimpleNamespace(type="text", text=text))
    usage = SimpleNamespace(
        input_tokens=1000,
        output_tokens=200,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    )
    return SimpleNamespace(content=content, stop_reason=stop, usage=usage)


class FakeMessages:
    def __init__(self, replies: list[SimpleNamespace]) -> None:
        self.replies = replies
        self.created: list[dict[str, object]] = []
        self.batches = SimpleNamespace(
            create=self._create_batch, retrieve=self._retrieve, results=self._results
        )
        self.batch_requests: list[list[dict[str, object]]] = []
        self.recorded_keys: list[str] = []

    def create(self, **params: object) -> SimpleNamespace:
        self.created.append(params)
        return self.replies.pop(0)

    def _create_batch(self, *, requests: list[dict[str, object]]) -> SimpleNamespace:
        self.batch_requests.append(requests)
        return SimpleNamespace(id="batch-1")

    def _retrieve(self, batch_id: str) -> SimpleNamespace:
        return SimpleNamespace(id=batch_id, processing_status="ended")

    def _results(self, batch_id: str) -> list[SimpleNamespace]:
        keys = (
            [str(r["custom_id"]) for r in self.batch_requests[-1]]
            if self.batch_requests
            else self.recorded_keys
        )
        return [
            SimpleNamespace(
                custom_id=key,
                result=SimpleNamespace(type="succeeded", message=_message('{"applies": []}')),
            )
            for key in reversed(keys)
        ]


def _client(
    tmp_path: Path, replies: list[SimpleNamespace]
) -> tuple[claude.LearningClient, FakeMessages]:
    messages = FakeMessages(replies)
    sdk = cast(anthropic.Anthropic, SimpleNamespace(messages=messages))
    client = claude.LearningClient(
        sdk, tmp_path, "run-1", commit=("abc1234", False), forbidden=frozenset({"DEV400CASE"})
    )
    return client, messages


def _call(
    role: str = "propose", case_ids: tuple[str, ...] = ("A1",), user: str = "u"
) -> claude.Call:
    return claude.Call(
        role=role,
        model=claude.SONNET,
        effort="high",
        system="s",
        user=user,
        schema={"type": "object"},
        max_tokens=16000,
        case_ids=case_ids,
    )


def test_a_repeated_call_is_answered_from_the_record_without_paying_twice(tmp_path: Path) -> None:
    client, messages = _client(tmp_path, [_message('{"new": [], "edits": [], "retire": []}')])
    first = client.send(_call())
    again = client.send(_call())
    assert first.ok
    assert again == first
    assert len(messages.created) == 1


def test_a_refusal_or_a_truncation_is_a_failed_reply_not_an_exception(tmp_path: Path) -> None:
    client, _ = _client(
        tmp_path, [_message(None, stop="refusal"), _message("{", stop="max_tokens")]
    )
    assert not client.send(_call(user="a")).ok
    assert not client.send(_call(user="b")).ok


def test_a_forbidden_case_or_role_is_refused_before_any_call(tmp_path: Path) -> None:
    client, messages = _client(tmp_path, [])
    with pytest.raises(ConfigurationError):
        client.send(_call(case_ids=("DEV400CASE",)))
    with pytest.raises(ConfigurationError):
        client.send(_call(role="answer"))
    assert messages.created == []


def test_effort_and_structured_output_are_stated_on_every_call() -> None:
    params = _call().params()
    assert params["output_config"] == {
        "effort": "high",
        "format": {"type": "json_schema", "schema": {"type": "object"}},
    }
    assert "thinking" not in params
    assert "tool_choice" not in params


def test_batch_results_are_matched_by_id_whatever_their_order(tmp_path: Path) -> None:
    client, messages = _client(tmp_path, [])
    calls = [_call(role="apply", user=f"u{i}") for i in range(3)]
    replies = client.send_batch(calls, sleep=lambda _: None)
    assert set(replies) == {c.key() for c in calls}
    assert all(r.ok for r in replies.values())
    assert all(r.batch for r in replies.values())
    assert len(messages.batch_requests) == 1


def test_cost_is_priced_from_usage_and_written_as_learning_spend(tmp_path: Path) -> None:
    client, _ = _client(tmp_path, [_message('{"new": [], "edits": [], "retire": []}')])
    reply = client.send(_call())
    price = sources.claude_price(claude.SONNET, batch=False)
    assert reply.cost_usd == pytest.approx(
        (1000 * price.input_usd_per_mtok + 200 * price.output_usd_per_mtok) / 1e6
    )
    assert learning_month_spent(tmp_path, now=datetime.now(UTC)) == pytest.approx(reply.cost_usd)


def test_a_recorded_reply_carries_what_its_price_needs(tmp_path: Path) -> None:
    client, _ = _client(tmp_path, [_message('{"a": 1}')])
    reply = client.send(_call())
    row = json.loads((tmp_path / "run-1" / "calls.jsonl").read_text().splitlines()[0])
    for name in (
        "model",
        "batch",
        "input_tokens",
        "output_tokens",
        "cache_write_tokens",
        "cache_read_tokens",
    ):
        assert name in row
    price = sources.claude_price(row["model"], batch=row["batch"])
    assert reply.cost_usd == claude.cost_usd(1000, 200, 0, 0, price)


def test_a_refusal_records_its_category(tmp_path: Path) -> None:
    message = _message(None, stop="refusal")
    message.stop_details = SimpleNamespace(category="cyber")
    client, _ = _client(tmp_path, [message])
    reply = client.send(_call())
    assert reply.stop_category == "cyber"
    assert reply.error is not None


def test_a_recorded_unfinished_batch_is_waited_on_not_sent_again(tmp_path: Path) -> None:
    client, messages = _client(tmp_path, [])
    calls = [_call(role="apply", user=f"u{i}") for i in range(2)]
    keys = sorted(c.key() for c in calls)
    messages.recorded_keys = keys
    line = {"batch_id": "batch-0", "keys": keys, "finished": False}
    (tmp_path / "run-1" / "batches.jsonl").write_text(json.dumps(line) + "\n")
    replies = client.send_batch(calls, sleep=lambda _: None)
    assert messages.batch_requests == []
    assert all(r.ok for r in replies.values())
    rows = [json.loads(x) for x in (tmp_path / "run-1" / "batches.jsonl").read_text().splitlines()]
    assert rows[-1]["finished"] is True


def test_mixed_models_in_one_batch_are_refused(tmp_path: Path) -> None:
    client, _ = _client(tmp_path, [])
    other = claude.Call("apply", claude.HAIKU, "low", "s", "u", {}, 10, ("A1",))
    with pytest.raises(ConfigurationError):
        client.send_batch([_call(role="apply"), other], sleep=lambda _: None)


def test_a_haiku_prompt_past_the_price_limit_is_refused(tmp_path: Path) -> None:
    client, messages = _client(tmp_path, [])
    huge = claude.Call(
        "apply",
        claude.HAIKU,
        "low",
        "s",
        "x" * (sources.HAIKU_55_PROMPT_LIMIT * 5),
        {},
        10,
        ("A1",),
    )
    with pytest.raises(ConfigurationError):
        client.send(huge)
    assert messages.created == []


def test_sdk_from_key_builds_a_client_without_the_network() -> None:
    sdk = claude.sdk_from_key("test-key-not-real")
    assert isinstance(sdk, anthropic.Anthropic)
