"""S3.2 Task 6: the gates that let the registered held-out runs happen once, and nothing else.

Arm B is three steps: an answer run, ``tools`` over it, and ``check --way luna --stats s3`` over
that. Today the last two refuse every held-out run. They admit a ``heldout-400`` arm B run only
after ``docs/rounds/s3-registration.md`` is committed, from a clean tree, once per source; arm C
on ``heldout-400`` needs the same registration (decision 0142; spec §4.3 item 5, §18).

Nothing here touches real held-out data. Every run folder is built under ``tmp_path`` from a
fixture record with a made-up case number and an event date in the held-out years. The
repository's state (the registration, a dirty tree) is faked, never read.
"""

import copy
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from apps.eval.__main__ import main
from tests.test_eval_app import GOOD, REFINE, _eval_env, _factory, _StubDocketReader
from tests.test_occurrence_misses import _case

from ntsb_probable_cause import gitinfo
from ntsb_probable_cause.agent import armb
from ntsb_probable_cause.agent.run import GUIDANCE, AgentRunner, refuse_unregistered_heldout
from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.model.client import ModelClient, RecordingFakeClient, tool_reply
from ntsb_probable_cause.scoring import checkpass, ledger, samples
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.coding_stats import load_stats
from ntsb_probable_cause.scoring.records import CaseResult, RunRecord, read_jsonl, write_jsonl
from ntsb_probable_cause.scoring.runner import BatchRunner, RunSpec
from ntsb_probable_cause.settings import Settings

HELD = "heldout-400"
CASE = "ERA21LA901"  # made up: no such case exists
REGISTRATION = Path("docs/rounds/s3-registration.md")
USED = Path("docs/rounds/s3-2-used.md")  # decision 0142: committed by the controller at close-out


class Repo:
    """The repository's state as the gates read it: registration, used mark, dirty tree."""

    def __init__(self) -> None:
        self.registered = False
        self.used = False
        self.dirty = False

    def is_committed(self, path: Path, repo: Path = Path()) -> bool:
        """The registration and the used mark are in doubt; every other file is committed."""
        if Path(path) == REGISTRATION:
            return self.registered
        if Path(path) == USED:
            return self.used
        return True

    def commit_state(self, repo: Path = Path()) -> tuple[str, bool]:
        """A fixed short SHA and the fake dirty flag."""
        return "abc1234", self.dirty


def _held_raw(raw: dict[str, object]) -> dict[str, object]:
    """A fixture record made over as a held-out case: a made-up number, a held-out event date."""
    held = copy.deepcopy(raw)
    held["ntsbNumber"] = CASE
    held["eventDate"] = "2021-06-01T00:00:00"
    return held


def _no_client(_settings: Settings) -> tuple[ModelClient, BatchRunner | None]:
    raise AssertionError("no client may be built for a refused command")


def _ledger_rows(path: Path) -> list[str]:
    return [line for line in path.read_text().splitlines() if line.startswith("| 20")]


@pytest.fixture
def repo(monkeypatch: pytest.MonkeyPatch) -> Repo:
    state = Repo()
    monkeypatch.setattr(gitinfo, "is_committed", state.is_committed)
    monkeypatch.setattr(ledger, "commit_state", state.commit_state)
    return state


def _answer_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    record_fixtures: list[dict[str, object]],
) -> tuple[str, Path, Path]:
    """A finished held-out arm B answer run, made by the real command.

    Returns the run id, the runs directory and the held-out ledger.
    """
    monkeypatch.setattr("apps.eval.__main__.CachedDocketReader", _StubDocketReader)
    held = _held_raw(record_fixtures[0])
    _eval_env(tmp_path, monkeypatch, held)
    monkeypatch.setitem(samples._FILES, HELD, "dev_ids.csv")
    ledger_path = tmp_path / "heldout-ledger.md"
    monkeypatch.setenv("NTSB_HELDOUT_LEDGER_PATH", str(ledger_path))
    argv = ["run", "--arm", "B", "--sample", HELD, "--sync", "--price-variant", "standard"]
    argv += [flag for name in GUIDANCE for flag in ("--guidance", name)]
    assert main(argv, client_factory=_factory(RecordingFakeClient([GOOD, REFINE]))) == 0
    runs = tmp_path / "data" / "runs"
    (source,) = [p.name for p in runs.iterdir() if p.is_dir()]
    return source, runs, ledger_path


def _tools_client() -> RecordingFakeClient:
    return RecordingFakeClient([tool_reply("submit_answer", GOOD), REFINE])


# --------------------------------------------------------------------------------------------
# 1 and 2: tools
# --------------------------------------------------------------------------------------------


class TestToolsOnHeldOut:
    def test_refused_until_the_registration_is_committed_then_one_ledger_row(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        record_fixtures: list[dict[str, object]],
        repo: Repo,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        source, runs, ledger_path = _answer_run(tmp_path, monkeypatch, record_fixtures)
        assert len(_ledger_rows(ledger_path)) == 1  # the answer run's own row
        record = read_jsonl(runs / source / "run.jsonl", RunRecord)[0]
        assert record.sample == HELD
        (case,) = read_jsonl(runs / source / "cases.jsonl", CaseResult)
        assert case.split == "heldout"  # the value real held-out cases carry

        capsys.readouterr()
        assert main(["tools", source, "--sync"], client_factory=_no_client) == 1
        err = capsys.readouterr().err
        assert "development" in err
        assert not (runs / armb.tools_id(source)).exists()
        assert len(_ledger_rows(ledger_path)) == 1

        repo.registered = True
        client = _tools_client()
        assert main(["tools", source, "--sync"], client_factory=_factory(client)) == 0
        derived = armb.tools_id(source)
        assert f"tools {derived}: 1 cases" in capsys.readouterr().out
        rows = _ledger_rows(ledger_path)
        assert len(rows) == 2
        assert f"{derived}/cases.jsonl" in rows[1]
        assert f"| {HELD} | B |" in rows[1]

    def test_a_dirty_tree_is_refused_before_anything_is_read(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        record_fixtures: list[dict[str, object]],
        repo: Repo,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        source, runs, ledger_path = _answer_run(tmp_path, monkeypatch, record_fixtures)
        repo.registered = True
        repo.dirty = True

        def no_cases(_processed: Path, _ids: object) -> object:
            raise AssertionError("no case may be read for a dirty tree")

        monkeypatch.setattr(samples, "load_cases", no_cases)
        # The source's cases are not read either: an unreadable file would fail another way.
        (runs / source / "cases.jsonl").write_text("not json\n")
        capsys.readouterr()
        assert main(["tools", source, "--sync"], client_factory=_no_client) == 1
        assert "uncommitted changes" in capsys.readouterr().err
        assert not (runs / armb.tools_id(source)).exists()
        assert len(_ledger_rows(ledger_path)) == 1

    def test_a_second_tools_on_the_same_source_is_refused(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        record_fixtures: list[dict[str, object]],
        repo: Repo,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        source, _runs, ledger_path = _answer_run(tmp_path, monkeypatch, record_fixtures)
        repo.registered = True
        assert main(["tools", source, "--sync"], client_factory=_factory(_tools_client())) == 0
        capsys.readouterr()
        assert main(["tools", source, "--sync"], client_factory=_no_client) == 1
        assert "exists" in capsys.readouterr().err
        assert len(_ledger_rows(ledger_path)) == 2  # no third row

    def test_registration_opens_only_heldout_400_arm_b(self, tmp_path: Path, repo: Repo) -> None:
        repo.registered = True
        base = _record(tmp_path, HELD, "B")
        for changed in (
            base.model_copy(update={"sample": "heldout-40"}),
            base.model_copy(update={"arm": "A"}),
            base.model_copy(update={"arm": "C"}),
            base.model_copy(update={"arm": "ceiling"}),
        ):
            assert not checkpass.heldout_open(changed, is_committed=repo.is_committed)
        assert checkpass.heldout_open(base, is_committed=repo.is_committed)
        repo.registered = False
        assert not checkpass.heldout_open(base, is_committed=repo.is_committed)

    def test_the_default_asks_git_at_the_time_of_the_call(self, tmp_path: Path, repo: Repo) -> None:
        """A test (or a later fake) that replaces ``gitinfo.is_committed`` must reach the gate."""
        base = _record(tmp_path, HELD, "B")
        assert not checkpass.heldout_open(base)
        repo.registered = True
        assert checkpass.heldout_open(base)

    def test_the_library_guard_wants_heldout_cases_for_a_heldout_run(
        self, tmp_path: Path, repo: Repo
    ) -> None:
        repo.registered = True
        record = _record(tmp_path, HELD, "B")
        held = [_case("c1", ("552240",), ("552240",), split="heldout")]
        checkpass._refuse_unless_development(record, held)  # no refusal
        mixed = [*held, _case("c2", ("552240",), ("552240",), split="dev")]
        with pytest.raises(ConfigurationError, match="outside the held-out split"):
            checkpass._refuse_unless_development(record, mixed)
        dev = _record(tmp_path, "dev-400", "B")
        with pytest.raises(ConfigurationError, match="outside the development split"):
            checkpass._refuse_unless_development(dev, held)

    def test_an_unfinished_or_derived_heldout_run_is_still_refused(
        self, tmp_path: Path, repo: Repo
    ) -> None:
        repo.registered = True
        held = [_case("c1", ("552240",), ("552240",), split="heldout")]
        record = _record(tmp_path, HELD, "B")
        with pytest.raises(ConfigurationError, match="has not finished"):
            checkpass._refuse_unless_development(record.model_copy(update={"finished": None}), held)
        derived = record.model_copy(update={"run_id": f"{record.run_id}-check-luna"})
        with pytest.raises(ConfigurationError, match="no stacked checks"):
            checkpass._refuse_unless_development(derived, held)


def _record(tmp_path: Path, sample: str, arm: str) -> RunRecord:
    when = datetime(2026, 10, 3, tzinfo=UTC)
    return RunRecord(
        run_id=f"20261003T000000-abc1234-{sample}-{arm}",
        sample=sample,
        arm=arm,
        exclusions=(),
        includes=(),
        prompt_version="s1-v6+tools-s3",
        guidance=GUIDANCE,
        model="openai/gpt-6-luna",
        price_variant="batch",
        cap_usd=0.30,
        budget_usd=40.0,
        commit_sha="abc1234",
        dirty=False,
        started=when,
        finished=when,
        cases=1,
        cost_usd=0.0,
    )


# --------------------------------------------------------------------------------------------
# 3 and 4: check
# --------------------------------------------------------------------------------------------


def _tools_run_folder(
    runs: Path, *, run_id: str = f"20261003T000000-abc1234-{HELD}-B-tools", tools: bool = True
) -> str:
    """A finished held-out arm B run, one scored case: enough for ``check`` to read."""
    record = _record(runs, HELD, "B").model_copy(
        update={
            "run_id": run_id,
            "prompt_version": "s1-v6+tools-s3+pabc" if tools else "s1-v6",
        }
    )
    write_jsonl(runs / run_id / "run.jsonl", [record])
    case = _case(CASE, ("552240", "552241"), ("552241",), split="heldout")
    write_jsonl(runs / run_id / "cases.jsonl", [case])
    return run_id


def _check_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    runs = tmp_path / "runs"
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NTSB_RUNS_DIR", str(runs))
    ledger_path = tmp_path / "heldout-ledger.md"
    monkeypatch.setenv("NTSB_HELDOUT_LEDGER_PATH", str(ledger_path))
    monkeypatch.setattr(samples, "load_cases", lambda _processed, ids: [{} for _ in ids])
    monkeypatch.setattr(samples, "seen_pairs", lambda _processed: frozenset())
    return runs, ledger_path


class TestCheckOnHeldOut:
    def test_refused_until_registered_then_one_ledger_row(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        repo: Repo,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        runs, ledger_path = _check_env(tmp_path, monkeypatch)
        run_id = _tools_run_folder(runs)
        argv = ["check", run_id, "--way", "luna", "--stats", "s3"]
        assert main(argv, client_factory=_no_client) == 1
        assert "development" in capsys.readouterr().err
        assert not (runs / f"{run_id}-check-luna").exists()
        assert not ledger_path.exists()

        repo.registered = True
        assert main(argv, client_factory=_factory(_luna_client())) == 0
        derived = f"{run_id}-check-luna"
        assert (runs / derived / "run.jsonl").exists()
        (row,) = _ledger_rows(ledger_path)
        assert f"{derived}/cases.jsonl" in row
        assert f"| {HELD} | B |" in row

    def test_a_heldout_run_that_is_not_a_tools_run_is_refused(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        repo: Repo,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        runs, ledger_path = _check_env(tmp_path, monkeypatch)
        repo.registered = True
        run_id = _tools_run_folder(runs, run_id=f"20261003T000000-abc1234-{HELD}-B", tools=False)
        argv = ["check", run_id, "--way", "luna", "--stats", "s3"]
        assert main(argv, client_factory=_no_client) == 1
        assert "-tools" in capsys.readouterr().err
        assert not (runs / f"{run_id}-check-luna").exists()
        assert not ledger_path.exists()

    def test_a_dirty_tree_is_refused_before_anything_is_read(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        repo: Repo,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        runs, ledger_path = _check_env(tmp_path, monkeypatch)
        repo.registered = True
        repo.dirty = True
        run_id = _tools_run_folder(runs)

        def no_cases(_processed: Path, _ids: object) -> object:
            raise AssertionError("no case may be read for a dirty tree")

        monkeypatch.setattr(samples, "load_cases", no_cases)
        argv = ["check", run_id, "--way", "luna", "--stats", "s3"]
        assert main(argv, client_factory=_no_client) == 1
        assert "uncommitted changes" in capsys.readouterr().err
        assert not (runs / f"{run_id}-check-luna").exists()
        assert not ledger_path.exists()

    def test_a_second_check_is_refused(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        repo: Repo,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        runs, ledger_path = _check_env(tmp_path, monkeypatch)
        repo.registered = True
        run_id = _tools_run_folder(runs)
        argv = ["check", run_id, "--way", "luna", "--stats", "s3"]
        assert main(argv, client_factory=_factory(_luna_client())) == 0
        capsys.readouterr()
        assert main(argv, client_factory=_no_client) == 1
        assert "exists" in capsys.readouterr().err
        assert len(_ledger_rows(ledger_path)) == 1

    def test_the_library_preflight_reads_only_a_tools_run_on_heldout(
        self, tmp_path: Path, repo: Repo
    ) -> None:
        """The command checks the run id; the library checks the run's own prompt version."""
        repo.registered = True
        answer = _tools_run_folder(
            tmp_path, run_id=f"20261003T000000-abc1234-{HELD}-B", tools=False
        )
        with pytest.raises(ConfigurationError, match="reads the <run id>-tools run only"):
            checkpass.preflight(tmp_path / answer, "luna", tmp_path, stats="s3")
        tools = _tools_run_folder(tmp_path)
        pre = checkpass.preflight(tmp_path / tools, "luna", tmp_path, stats="s3")
        assert pre.run_id == f"{tools}-check-luna"

    @pytest.mark.parametrize("way", ["rule", "jev", "jev2"])
    def test_only_luna_may_check_a_heldout_run(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        repo: Repo,
        capsys: pytest.CaptureFixture[str],
        way: str,
    ) -> None:
        """Decisions 0097, 0142: refused before a case is read or a client built."""
        runs, ledger_path = _check_env(tmp_path, monkeypatch)
        repo.registered = True
        run_id = _tools_run_folder(runs)

        def no_cases(_processed: Path, _ids: object) -> object:
            raise AssertionError("no case may be read for a refused way")

        def no_jev(_settings: Settings) -> object:
            raise AssertionError("no jev client may be built for a held-out run")

        monkeypatch.setattr(samples, "load_cases", no_cases)
        argv = ["check", run_id, "--way", way, "--stats", "s3"]
        assert main(argv, client_factory=_no_client, jev_factory=no_jev) == 1  # type: ignore[arg-type]
        assert "way luna only" in capsys.readouterr().err
        assert [p.name for p in runs.iterdir()] == [run_id]  # no derived folder
        assert not ledger_path.exists()

    def test_after_a_luna_check_another_way_is_refused(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        repo: Repo,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        runs, ledger_path = _check_env(tmp_path, monkeypatch)
        repo.registered = True
        run_id = _tools_run_folder(runs)
        luna = ["check", run_id, "--way", "luna", "--stats", "s3"]
        assert main(luna, client_factory=_factory(_luna_client())) == 0
        capsys.readouterr()
        rule = ["check", run_id, "--way", "rule", "--stats", "s3"]
        assert main(rule, client_factory=_no_client) == 1
        assert "way luna only" in capsys.readouterr().err
        assert not (runs / f"{run_id}-check-rule").exists()
        assert len(_ledger_rows(ledger_path)) == 1

    def test_the_library_preflight_refuses_any_other_way_on_heldout(
        self, tmp_path: Path, repo: Repo
    ) -> None:
        repo.registered = True
        tools = _tools_run_folder(tmp_path)
        for way in ("rule", "jev", "jev2"):
            with pytest.raises(ConfigurationError, match="way luna only"):
                checkpass.preflight(tmp_path / tools, way, tmp_path, stats="s3")

    def test_the_stats_rule_still_holds_for_a_heldout_tools_run(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        repo: Repo,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        runs, ledger_path = _check_env(tmp_path, monkeypatch)
        repo.registered = True
        run_id = _tools_run_folder(runs)
        argv = ["check", run_id, "--way", "luna", "--stats", "s27"]
        assert main(argv, client_factory=_no_client) == 1
        assert "--stats s3" in capsys.readouterr().err
        assert not ledger_path.exists()

    def test_arm_c_heldout_and_other_heldout_samples_stay_refused(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        repo: Repo,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        runs, _ledger_path = _check_env(tmp_path, monkeypatch)
        repo.registered = True
        for sample, arm in (("heldout-40", "B"), (HELD, "C"), (HELD, "A")):
            run_id = f"20261003T000000-abc1234-{sample}-{arm}-tools"
            record = _record(runs, sample, arm).model_copy(update={"run_id": run_id})
            write_jsonl(runs / run_id / "run.jsonl", [record])
            write_jsonl(runs / run_id / "cases.jsonl", [_case(CASE, ("552240",), ("552240",))])
            argv = ["check", run_id, "--way", "luna", "--stats", "s3"]
            assert main(argv, client_factory=_no_client) == 1
            assert "development" in capsys.readouterr().err


def _luna_client() -> RecordingFakeClient:
    return RecordingFakeClient([json.dumps({"ranking": ["552241"]})])


# --------------------------------------------------------------------------------------------
# 5: arm C
# --------------------------------------------------------------------------------------------


class TestArmCOnHeldOut:
    def test_run_is_refused_before_a_client_or_a_reservation(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        record_fixtures: list[dict[str, object]],
        repo: Repo,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr("apps.eval.__main__.CachedDocketReader", _StubDocketReader)
        _eval_env(tmp_path, monkeypatch, _held_raw(record_fixtures[0]))
        monkeypatch.setitem(samples._FILES, HELD, "dev_ids.csv")
        monkeypatch.setenv("NTSB_HELDOUT_LEDGER_PATH", str(tmp_path / "ledger.md"))
        argv = ["run", "--arm", "C", "--sample", HELD, "--sync", "--price-variant", "standard"]
        argv += ["--cap-usd", "0.30", "--expected-cost-per-case-usd", "0.01"]
        assert main(argv, client_factory=_no_client) == 1
        err = capsys.readouterr().err
        assert (
            "heldout-400: arm C runs on held-out only after docs/rounds/s3-registration.md is "
            "committed (decision 142)" in err
        )
        runs = tmp_path / "data" / "runs"
        assert not runs.exists() or not list(runs.iterdir())

    def test_the_runner_itself_refuses_when_called_directly(
        self, tmp_path: Path, repo: Repo
    ) -> None:
        """The library guard holds without the command: ``AgentRunner._refuse`` checks it."""
        runner = AgentRunner(
            RecordingFakeClient([]),
            batch=None,
            tables=load_tables(),
            stats=load_stats("s3"),
            seen_pairs=frozenset(),
            runs_dir=tmp_path / "runs",
            month_spent_usd=0.0,
            commit=("abc1234", False),
            docket=None,
            ledger_path=tmp_path / "ledger.md",
            is_committed=repo.is_committed,
        )
        spec = RunSpec(sample=HELD, arm="C", guidance=GUIDANCE, sync=True, price_variant="standard")
        with pytest.raises(ConfigurationError, match="arm C runs on held-out only after"):
            runner.run(spec, [])
        assert not (tmp_path / "runs").exists()

    def test_the_registration_lifts_that_refusal_only(self, tmp_path: Path, repo: Repo) -> None:
        repo.registered = True
        runner = AgentRunner(
            RecordingFakeClient([]),
            batch=None,
            tables=load_tables(),
            stats=load_stats("s3"),
            seen_pairs=frozenset(),
            runs_dir=tmp_path / "runs",
            month_spent_usd=0.0,
            commit=("abc1234", True),  # dirty: the next rule in line
            docket=None,
            ledger_path=tmp_path / "ledger.md",
            is_committed=repo.is_committed,
        )
        spec = RunSpec(sample=HELD, arm="C", guidance=GUIDANCE, sync=True, price_variant="standard")
        with pytest.raises(ConfigurationError, match="uncommitted changes"):
            runner.run(spec, [])


# --------------------------------------------------------------------------------------------
# 6: development runs are unchanged. The existing tests/test_agent_armb.py, test_checkpass.py
# and the check tests in tests/test_eval_app.py run as they were; this adds the refusals they
# rely on, with the wording they match.
# --------------------------------------------------------------------------------------------


def test_a_development_arm_b_run_never_asks_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def asked(_path: Path, repo: Path = Path()) -> bool:
        raise AssertionError("a development run does not ask whether the registration is committed")

    monkeypatch.setattr(gitinfo, "is_committed", asked)
    record = _record(tmp_path, "dev-400", "B")
    assert not checkpass.heldout_open(record)
    checkpass._refuse_unless_development(record, [_case("c1", ("552240",), ("552240",))])


def test_the_hint_for_a_refused_heldout_run_names_the_registration(
    tmp_path: Path, repo: Repo
) -> None:
    record = _record(tmp_path, HELD, "B")
    with pytest.raises(ConfigurationError, match=r"s3-registration\.md"):
        checkpass._refuse_unless_development(record, [])


def test_development_tools_and_check_leave_the_heldout_ledger_alone(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    record_fixtures: list[dict[str, object]],
    repo: Repo,
) -> None:
    """A development run is not a held-out run: no ledger file is made, registered or not."""
    monkeypatch.setattr("apps.eval.__main__.CachedDocketReader", _StubDocketReader)
    _eval_env(tmp_path, monkeypatch, record_fixtures[0])
    ledger_path = tmp_path / "heldout-ledger.md"
    monkeypatch.setenv("NTSB_HELDOUT_LEDGER_PATH", str(ledger_path))
    repo.registered = True
    argv = ["run", "--arm", "B", "--sample", "dev-400", "--sync", "--price-variant", "standard"]
    argv += [flag for name in GUIDANCE for flag in ("--guidance", name)]
    assert main(argv, client_factory=_factory(RecordingFakeClient([GOOD, REFINE]))) == 0
    runs = tmp_path / "data" / "runs"
    (source,) = [p.name for p in runs.iterdir() if p.is_dir()]
    assert main(["tools", source, "--sync"], client_factory=_factory(_tools_client())) == 0
    derived = armb.tools_id(source)
    assert main(["check", derived, "--way", "rule", "--stats", "s3"]) == 0
    assert (runs / f"{derived}-check-rule" / "run.jsonl").exists()
    assert not ledger_path.exists()


# --------------------------------------------------------------------------------------------
# 7: used once (decision 0142). Once docs/rounds/s3-2-used.md is committed, both gates close.
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("registered", "used", "opened"),
    [(True, False, True), (True, True, False), (False, False, False), (False, True, False)],
)
def test_heldout_open_admits_a_registered_run_only_until_the_used_mark_is_committed(
    tmp_path: Path, repo: Repo, registered: bool, used: bool, opened: bool
) -> None:
    repo.registered, repo.used = registered, used
    record = _record(tmp_path, HELD, "B")
    assert checkpass.heldout_open(record, is_committed=repo.is_committed) is opened


def test_a_heldout_arm_b_run_after_use_is_refused_naming_the_mark_and_0142(
    tmp_path: Path, repo: Repo
) -> None:
    repo.registered = repo.used = True
    record = _record(tmp_path, HELD, "B")
    with pytest.raises(ConfigurationError, match=r"s3-2-used\.md is committed \(decision 0142\)"):
        checkpass._refuse_unless_development(record, [])


def test_the_tools_command_is_refused_once_the_used_mark_is_committed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    record_fixtures: list[dict[str, object]],
    repo: Repo,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source, runs, ledger_path = _answer_run(tmp_path, monkeypatch, record_fixtures)
    repo.registered = repo.used = True
    capsys.readouterr()
    assert main(["tools", source, "--sync"], client_factory=_no_client) == 1
    assert "s3-2-used.md" in capsys.readouterr().err
    assert not (runs / armb.tools_id(source)).exists()
    assert len(_ledger_rows(ledger_path)) == 1


@pytest.mark.parametrize(
    ("registered", "used", "refusal"),
    [
        (True, False, None),
        (True, True, r"s3-2-used\.md is committed .*decision 0142"),
        (False, False, r"s3-registration\.md"),
        (False, True, r"s3-registration\.md"),
    ],
)
def test_arm_c_on_heldout_is_refused_once_the_used_mark_is_committed(
    repo: Repo, registered: bool, used: bool, refusal: str | None
) -> None:
    repo.registered, repo.used = registered, used
    if refusal is None:
        refuse_unregistered_heldout(HELD, repo.is_committed)
        return
    with pytest.raises(ConfigurationError, match=refusal):
        refuse_unregistered_heldout(HELD, repo.is_committed)


def test_a_development_arm_c_run_never_asks_about_the_used_mark() -> None:
    def asked(_path: Path) -> bool:
        raise AssertionError("a development run asks git nothing")

    refuse_unregistered_heldout("dev-400", asked)
