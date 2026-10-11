"""The live runbooks quote messages the program really prints and cover every alert kind.

``live-cloud-nights.md`` is S4's runbook (Task 14); ``live-shadow-mornings.md`` is S3.3's, kept as
history with a dated note, and is checked only where it still makes sense: its quoted refusal
texts must still be in the program, and it must point at the new runbook.
"""

import re
from pathlib import Path

from ntsb_probable_cause.live.morning import ALERT_KINDS
from ntsb_probable_cause.live.night import NIGHT_KINDS

ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = ROOT / "docs" / "runbooks" / "live-cloud-nights.md"
OLD_RUNBOOK = ROOT / "docs" / "runbooks" / "live-shadow-mornings.md"


def _sources() -> str:
    paths = [
        *(ROOT / "src").rglob("*.py"),
        *(ROOT / "apps").rglob("*.py"),
        *(ROOT / "scripts").glob("*.py"),
        *(ROOT / "scripts").glob("*.sh"),
    ]
    return "\n".join(p.read_text() for p in paths)


def _section(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


def _rows(section: str) -> list[str]:
    return [line for line in section.splitlines() if line.startswith("| `")]


def _commands(text: str) -> list[str]:
    """Every line of every fenced code block."""
    blocks = re.findall(r"```[a-z]*\n(.*?)```", text, flags=re.DOTALL)
    return [line.strip() for block in blocks for line in block.splitlines() if line.strip()]


def _aws_lines(text: str) -> list[str]:
    inline = re.findall(r"`(aws [^`]+)`", text)
    return [line for line in [*_commands(text), *inline] if re.search(r"(^|\| |\$\()aws ", line)]


# --- the new runbook ---------------------------------------------------------------------------


def test_every_alert_kind_has_a_row_in_the_emails_table() -> None:
    rows = _rows(_section(RUNBOOK.read_text(), "## 3. The emails", "\n## 4."))
    kinds = {row.split("|")[1].strip().strip("`") for row in rows}
    assert set(ALERT_KINDS) <= kinds
    assert kinds <= set(ALERT_KINDS)  # a row for a kind the program does not have is stale
    for row in rows:
        what, does = row.split("|")[2:4]
        assert what.strip(), row
        assert does.strip(), row


def test_every_refusal_kind_and_every_night_kind_is_in_the_alert_list_and_the_runbook() -> None:
    sources = (ROOT / "src" / "ntsb_probable_cause" / "live").rglob("*.py")
    raised = {
        kind
        for path in sources
        for kind in re.findall(r'LiveRefusal\(\s*"([a-z0-9-]+)"', path.read_text())
    }
    assert raised  # the pattern found the refusals
    assert raised <= set(ALERT_KINDS)
    assert set(NIGHT_KINDS) <= set(ALERT_KINDS)
    text = RUNBOOK.read_text()
    for kind in sorted(raised | set(NIGHT_KINDS)):
        assert f"| `{kind}` |" in text, kind


def test_every_quoted_message_text_is_in_the_program() -> None:
    sources = _sources()
    rows = _rows(_section(RUNBOOK.read_text(), "## 6. Messages", "\n---"))
    assert len(rows) >= 25
    for row in rows:
        first = row.split("|")[1]
        quoted = re.findall(r"`([^`]+)`", first)
        assert quoted, row
        for text in quoted:
            assert text in sources, text


def test_every_message_row_has_what_to_do() -> None:
    for row in _rows(_section(RUNBOOK.read_text(), "## 6. Messages", "\n---")):
        cells = [c.strip() for c in row.split("|")[1:-1]]
        assert len(cells) == 3, row
        assert all(cells), row


def test_every_aws_command_names_the_ntsb_profile_and_no_command_prints_a_secret() -> None:
    text = RUNBOOK.read_text()
    lines = _aws_lines(text)
    assert len(lines) >= 20
    for line in lines:
        if line in {"aws login", "aws configure list-profiles"}:  # they choose no profile
            continue
        if "get-login-password" in line:
            assert "--profile ntsb" in line.split("|")[0], line
            continue
        assert "--profile ntsb" in line, line
    for line in _commands(text):
        assert "get-secret-value" not in line
        assert not re.search(r"\becho\b.*(key|token|secret)", line, re.IGNORECASE), line
        if "pass show" in line:
            assert "| aws ssm put-parameter" in line, line  # piped on, never to the screen
        assert "--with-decryption" not in line


def test_the_live_key_is_written_with_the_exact_command_and_the_note() -> None:
    text = RUNBOOK.read_text()
    assert (
        "pass show api/openrouter-live | aws ssm put-parameter --name /ntsb/live/openrouter-key "
        "--type SecureString --value file:///dev/stdin --overwrite --profile ntsb"
    ) in text
    assert "The value never appears on the screen" in text


def _app_context_names() -> set[str]:
    app = (ROOT / "infra" / "app.py").read_text()
    return set(re.findall(r'try_get_context\("([a-z_]+)"\)', app))


def test_every_cdk_deploy_gives_the_full_context_from_infra_app() -> None:
    text = RUNBOOK.read_text()
    deploys = [line for line in _commands(text) if line.startswith("cdk deploy")]
    assert len(deploys) == 4  # two for the first deploy, the go-ahead, and the post-merge one
    known = _app_context_names()
    for line in deploys:
        assert line.startswith("cdk deploy NtsbLiveStack --profile ntsb "), line
        names = set(re.findall(r"-c ([a-z_]+)=", line))
        assert names <= known, line
        assert {"recorder_bucket", "alert_email", "github_oidc_provider_arn"} <= names, line
        assert "ledger_branches" in names, line
        assert ("live_image_digest" in names) != ("live_image_digest_placeholder" in names), line
    enabled = [line for line in deploys if "live_schedule=enabled" in line]
    assert len(enabled) == 2  # the go-ahead, and the post-merge deploy that must keep it on
    assert any("ledger_branches=main " in line + " " for line in enabled)
    assert all("live_schedule" not in line for line in deploys if line not in enabled)
    assert "live_image_digest_placeholder=1" in deploys[0]
    merged = deploys[-1]
    assert "ledger_branches=main " in merged + " "
    assert "s4-predictions-and-resolution" not in merged
    for first in deploys[:3]:
        assert "ledger_branches=main,s4-predictions-and-resolution" in first


def test_the_runbook_names_the_stack_outputs_the_stack_defines() -> None:
    stack = (ROOT / "infra" / "live_stack.py").read_text()
    outputs = set(re.findall(r'CfnOutput\(self, "([A-Za-z]+)"', stack))
    assert {"LiveBucketName", "RepositoryUri", "AlertTopicArn", "LedgerRoleArn"} <= outputs
    text = RUNBOOK.read_text()
    for name in outputs:
        assert name in text, name


def test_the_ledger_setup_matches_the_workflow() -> None:
    text = RUNBOOK.read_text()
    workflow = (ROOT / ".github" / "workflows" / "ledger.yml").read_text()
    for secret in ("LEDGER_ROLE_ARN", "LIVE_BUCKET"):
        assert f"secrets.{secret}" in workflow
        assert f"gh secret set {secret}" in text
    assert "vars.LEDGER_ENABLED == 'true'" in workflow
    assert "gh variable set LEDGER_ENABLED --body true" in text
    assert text.index("gh secret set") < text.index("gh variable set LEDGER_ENABLED")
    assert text.index("switch --orphan ledger") < text.index("gh variable set LEDGER_ENABLED")
    assert text.index("branches/ledger/protection") < text.index("gh variable set LEDGER_ENABLED")
    assert not re.search(r"^\s*environment:", workflow, re.MULTILINE)
    assert "No GitHub environment" in text
    assert '"allow_force_pushes": false' in text
    assert '"allow_deletions": false' in text
    assert '"required_pull_request_reviews": null' in text
    assert 'Do **not** add "require a pull request"' in text


def test_the_runbook_covers_the_carried_situations() -> None:
    text = RUNBOOK.read_text()
    for needle in (
        "`set-alarm-state`" if False else "aws cloudwatch set-alarm-state --alarm-name",
        '--state-value ALARM --state-reason "S4 test"',
        "Run the test only once the alarm shows `OK`",
        "an alarm\n   already in `ALARM` sends nothing",
        "CDK does not remember the `-c` values",
        "A deploy without `-c live_schedule=enabled` switches the schedule off again",
        "without `-c ledger_branches=main` brings back the S4 branch's trust",
        "A run is finished only on the image that started it",
        "Do not deploy a new image while a run is unfinished",
        "ECR keeps the 5 newest images",
        "aws s3 rm s3://<bucket>/nights/<date>/started --profile ntsb",
        "It repeats every night while any case waits this long. This is expected.",
        "A kill before the first `spec.json` upload",
        "The next night makes the backfill\nlist again",
        "The export is not one step",
        "`export-failed`",
        "The image repository `ntsb-live`, the log group",
        "`ntsb-live export`",
        "needs the repository's\n`.git`",
        "reset period is **monthly**",
        "Check the reset period",
        "ntsb-live-reader",
        "live-shadow-read-store",
        "pass rm aws/ntsb-live-reader",
        "`[profile ntsb-live]`",
        "## Glossary",
    ):
        assert needle in text, needle


def test_every_make_target_the_runbook_names_exists() -> None:
    makefile = (ROOT / "Makefile").read_text()
    text = RUNBOOK.read_text()
    named = set(re.findall(r"`?make (s[0-9]+[0-9a-z]*-[a-z-]+)", text))
    assert {
        "s4-export",
        "s4-verify-ledger",
        "s4-report",
        "s4-spend",
        "s4-dry-run",
        "s4-image",
    } <= named
    for target in named:
        assert re.search(rf"^{target}:", makefile, re.MULTILINE), target
    assert "make s33-morning" not in text


def test_the_new_runbook_uses_plain_instructions_to_andy() -> None:
    text = RUNBOOK.read_text()
    assert "Tell Claude" in text or "tell Claude" in text
    assert "ask Andy" not in text
    assert "Claude asks you before the first cloud night" in text


# --- the old runbook, kept as history ----------------------------------------------------------


def test_the_old_runbook_points_at_the_new_one_with_a_dated_note() -> None:
    head = OLD_RUNBOOK.read_text().split("\n## 1.", 1)[0]
    assert "2026-10-11" in head
    assert "docs/runbooks/live-cloud-nights.md" in head
    assert "history" in head


def test_the_old_runbooks_quoted_refusal_texts_are_still_in_the_program() -> None:
    sources = _sources()
    section = _section(OLD_RUNBOOK.read_text(), "## 6. When the command refuses", "\n## 7.")
    rows = _rows(section)
    assert len(rows) >= 15
    for row in rows:
        for quoted in re.findall(r"`([^`]+)`", row.split("|")[1]):
            assert quoted in sources, quoted
