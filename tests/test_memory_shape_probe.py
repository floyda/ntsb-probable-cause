"""``scripts/memory_shape_probe.py`` against a fake Claude SDK (decision 0202 item 5, Task 11).

Nothing here calls the network, reads a key or opens a case file.
"""

from pathlib import Path
from types import SimpleNamespace
from typing import cast

import anthropic
import pytest
from scripts import memory_shape_probe
from tests.test_memory_claude import FakeMessages, _message

from ntsb_probable_cause import gitinfo
from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.memory import claude
from ntsb_probable_cause.scoring import samples

PROPOSE = '{"new": [], "edits": [], "retire": []}'


def _install(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    replies: list[SimpleNamespace],
    *,
    dirty: bool = False,
) -> FakeMessages:
    messages = FakeMessages(replies)
    models = SimpleNamespace(
        retrieve=lambda model_id: SimpleNamespace(
            id=model_id, display_name=model_id, max_input_tokens=200000, max_tokens=64000
        )
    )
    sdk = cast(anthropic.Anthropic, SimpleNamespace(messages=messages, models=models))
    settings = SimpleNamespace(
        runs_dir=tmp_path / "runs",
        learning_monthly_budget_usd=90.0,
        require_anthropic_key=lambda: "test-key",
    )
    monkeypatch.setattr(memory_shape_probe, "Settings", lambda: settings)
    monkeypatch.setattr(claude, "sdk_from_key", lambda key: sdk)
    monkeypatch.setattr(gitinfo, "commit_state", lambda: ("abc1234", dirty))

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("the probe must not open a case file")

    monkeypatch.setattr(samples, "load_cases", refuse)
    return messages


def test_every_check_reads_ok_and_the_result_is_written(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    messages = _install(monkeypatch, tmp_path, [_message(PROPOSE)])
    out = tmp_path / "result.txt"
    assert memory_shape_probe.main(["--out", str(out)]) == 0
    text = capsys.readouterr().out
    checks = [line for line in text.splitlines() if line.startswith("check ")]
    assert len(checks) == 5
    assert all(line.endswith(": ok") for line in checks)
    assert out.read_text() == text
    assert len(messages.created) == 1
    assert len(messages.batch_requests[0]) == 2


def test_a_truncated_reply_fails_a_check_and_returns_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _install(monkeypatch, tmp_path, [_message("{", stop="max_tokens")])
    assert memory_shape_probe.main([]) == 1
    text = capsys.readouterr().out
    assert "check every reply stopped on end_turn: FAILED" in text
    assert "check sonnet reply parses as ProposeReply: FAILED" in text


def test_a_dirty_tree_is_refused_before_any_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    messages = _install(monkeypatch, tmp_path, [], dirty=True)
    with pytest.raises(ConfigurationError):
        memory_shape_probe.main([])
    assert messages.created == []
