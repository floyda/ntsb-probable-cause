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
| [0015](0015-fixtures-redacted-real-dev-records.md) | Fixtures are redacted real development records | Accepted; amended by 0020 |
| [0016](0016-layered-leakage-guard-and-model-boundary.md) | A layered leakage guard, and a request-side model boundary | Accepted |
| [0017](0017-spec-lifecycle-as-built-and-plan-deletion.md) | Specifications close with an As-built record; plans are deleted at merge | Accepted |
| [0018](0018-squash-merges-and-tag-only-releases.md) | Squash merges, and tag-only releases at stage close | Accepted |
| [0019](0019-tripwire-skips-sentence-check-on-weather-report.md) | In the weather report field, the tripwire skips sentences from the factual narrative | Accepted |
| [0020](0020-amateur-built-make-and-model-replaced-in-evidence.md) | The make and model of amateur-built aircraft are replaced in evidence | Accepted |
| [0021](0021-agency-measured-as-hypothesis-trail.md) | Agency is measured as a scored hypothesis trail | Accepted |
| [0022](0022-loop-must-beat-call-every-tool-arm.md) | The loop must beat a call-every-tool arm at equal cost | Accepted |
| [0023](0023-evidence-by-source-with-measured-availability.md) | Evidence arrives by source, and availability is masked from measured arrival | Accepted |
| [0024](0024-open-split-enters-measurements-only-as-numbers.md) | Open-split cases enter a measurement only as numbers | Accepted |
| [0025](0025-scoring-targets-from-ntsb-code-tables.md) | Scoring targets come from the NTSB's code tables, in two stages | Accepted; amends 0006 and 0022 |
| [0026](0026-slices-fixed-samples-and-heldout-ledger.md) | Slices by fatality first; fixed samples; a held-out ledger | Accepted |
| [0027](0027-registration-rule-and-case-number-probe.md) | The registration rule, and the case-number probe measure memorisation | Accepted |
| [0028](0028-prose-graded-by-validated-judge-never-a-bar.md) | Prose outputs are graded by a validated judge, and are never a bar | Accepted |
| [0029](0029-live-headline-is-the-finding-score.md) | The live board's headline is the finding score | Accepted |
| [0030](0030-cost-in-usd-cap-and-budget-in-code.md) | Cost in US dollars from the provider; the cap and the monthly budget are enforced in code | Accepted |
| [0031](0031-default-model-gpt-luna-model-axis-after-s3.md) | The default model is GPT-5.6 Luna; the model axis is measured after S3 | Accepted |
| [0032](0032-a-batch-run-is-resumable-from-its-recorded-batches.md) | A batch run is resumable from the batches it already paid for | Accepted |
| [0033](0033-stage-pull-requests-keep-their-commits.md) | Stage pull requests are merged, not squashed, so a recorded commit resolves | Accepted |
| [0034](0034-cross-model-check-uses-gemini-flash.md) | The cross-model sanity check uses Gemini 3.1 Flash Lite, not Sonnet 5 | Accepted |
| [0035](0035-judge-narrative-gains-a-less-detailed-label.md) | The judge's narrative dimension gains a fourth label, "less detailed" | Accepted |
| [0036](0036-docket-fixtures-from-development-dockets-only.md) | Docket fixtures come from development-split dockets only | Accepted; amends the roadmap S2 entry |
| [0037](0037-docket-documents-are-evidence-by-case-level-authorship.md) | Every docket document is evidence; the line is the NTSB's case-level write-up | Accepted; amends 0013 |
| [0038](0038-filter-measured-by-tripwire-hits-and-a-title-hand-check.md) | The docket filter is measured by tripwire hits, and its type labels by a title hand-check | Accepted |
| [0039](0039-docket-shape-remeasured-on-closed-open-split-cases.md) | Docket shape is re-measured on closed open-split cases, 40 per stratum, numbers only | Accepted |
