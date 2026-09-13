# Decision records

Every significant decision on this project is written down here: architecture, scope,
tooling and methodology. One decision per file, numbered in the order taken.

## Why

The reasoning is the substance of this project. Anyone reading it should be able to find
the argument behind a choice and say precisely where they think it fails, instead of
inferring what was considered from the code that survived. A decision recorded only in a
commit message or a conversation is not recorded.

This also protects the work across sessions. A choice whose justification is lost gets
re-litigated, or quietly reversed by someone who never saw the constraint that produced it.

## Format

`NNNN-short-title.md`, with five headings:

- **Context** — what was true that forced a choice.
- **Decision** — what was chosen, stated so it can be checked against the code.
- **Why** — the reasoning, in order of weight.
- **What this rules out** — the alternatives and what each would have cost. A record with
  nothing here usually means the decision was not real.
- **Status** — `Accepted`, or `Superseded by NNNN`.

Keep them to one page. If a record needs more, the detail belongs in a specification
under `docs/specs/` and the record links to it.

## Rules

- **Append-only.** Never edit a decision to reflect a change of mind. Write a new record
  that names the one it replaces, and mark the old one superseded. The history of what was
  believed and when is part of the record.
- **Evidence over assertion.** Where a decision rests on a number, cite the script or sheet
  it came from. Where it rests on judgement, say so in those words.
- **Record the rejected option honestly.** State the strongest version of the alternative,
  not a weakened one.

## Index

| # | Decision | Status |
|---|---|---|
| [0001](0001-two-repositories.md) | Two repositories: frozen spike, one build repo | Accepted |
| [0002](0002-library-with-thin-apps.md) | Library with thin application entrypoints | Accepted |
| [0003](0003-static-site-as-pure-function-of-store.md) | The public site is a pure function of the store | Accepted |
| [0004](0004-scheduled-fargate-and-sqlite.md) | Scheduled Fargate task, SQLite in S3 | Accepted |
| [0005](0005-cdk-python-for-infrastructure.md) | AWS CDK in Python for infrastructure | Accepted |
| [0006](0006-code-constrained-output.md) | Code-constrained output with a graded lay explanation | Accepted; amended by 0013 |
| [0007](0007-build-order-recorder-pulled-forward.md) | Build order, with the recorder pulled forward | Accepted |
| [0008](0008-record-decisions.md) | Record every significant decision | Accepted |
| [0009](0009-model-access-via-openrouter.md) | Evaluation and live model calls go through OpenRouter | Accepted |
| [0010](0010-separate-aws-account.md) | The project runs in its own AWS account under Organizations | Accepted |
| [0011](0011-tooling-uv-hatchling-strict-analysis.md) | Tooling: uv on hatchling, Python 3.14, strict static analysis | Accepted |
| [0012](0012-typed-constants-replace-config-yaml.md) | Typed constants and settings replace `config.yaml` | Accepted |
| [0013](0013-evidence-synthesis-verdict.md) | Evidence, synthesis and verdict: the factual narrative is withheld and the agent writes its own | Accepted |
| [0014](0014-processed-file-index-plus-raw-record.md) | The processed file holds index columns and the raw record | Accepted |
| [0015](0015-fixtures-redacted-real-dev-records.md) | Fixtures are redacted real development records | Accepted |
| [0016](0016-layered-leakage-guard-and-model-boundary.md) | A layered leakage guard, and a request-side model boundary | Accepted |
| [0017](0017-spec-lifecycle-as-built-and-plan-deletion.md) | Specifications close with an As-built record; plans are deleted at merge | Accepted |
| [0018](0018-squash-merges-and-tag-only-releases.md) | Squash merges, and tag-only releases at stage close | Accepted |
| [0019](0019-tripwire-skips-sentence-check-on-weather-report.md) | In the weather report field, the tripwire skips sentences from the factual narrative | Accepted |
