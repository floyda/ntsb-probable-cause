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
| [0030](0030-cost-in-usd-cap-and-budget-in-code.md) | Cost in US dollars from the provider; the cap and the monthly budget are enforced in code | Accepted; its guard fixed by 0045 |
| [0031](0031-default-model-gpt-luna-model-axis-after-s3.md) | The default model is GPT-5.6 Luna; the model axis is measured after S3 | Accepted; item 1 replaced by 0073 |
| [0032](0032-a-batch-run-is-resumable-from-its-recorded-batches.md) | A batch run is resumable from the batches it already paid for | Accepted |
| [0033](0033-stage-pull-requests-keep-their-commits.md) | Stage pull requests are merged, not squashed, so a recorded commit resolves | Accepted |
| [0034](0034-cross-model-check-uses-gemini-flash.md) | The cross-model sanity check uses Gemini 3.1 Flash Lite, not Sonnet 5 | Accepted |
| [0035](0035-judge-narrative-gains-a-less-detailed-label.md) | The judge's narrative dimension gains a fourth label, "less detailed" | Accepted |
| [0036](0036-heldout-text-purged-from-history-shas-map-forward.md) | Withheld held-out text is purged from git history; the runs' recorded SHAs map forward | Accepted |
| [0037](0037-docket-fixtures-from-development-dockets-only.md) | Docket fixtures come from development-split dockets only | Accepted; amends the roadmap S2 entry; item 2 superseded by 0049 |
| [0038](0038-docket-documents-are-evidence-by-case-level-authorship.md) | Every docket document is evidence; the line is the NTSB's case-level write-up | Accepted; amends 0013; item 2 superseded by 0051, item 4 retired by 0054 |
| [0039](0039-filter-measured-by-tripwire-hits-and-a-title-hand-check.md) | The docket filter is measured by tripwire hits, and its type labels by a title hand-check | Accepted; items 1-2 completed and removed by 0056, item 3 narrowed by 0052 |
| [0040](0040-docket-shape-remeasured-on-closed-open-split-cases.md) | Docket shape is re-measured on closed open-split cases, 40 per stratum, numbers only | Accepted |
| [0041](0041-docket-text-enters-through-a-case-context.md) | Docket text enters through a case context built by one attach step, before the split | Accepted |
| [0042](0042-two-docket-roles-selection-when-the-context-is-built.md) | Two docket evidence roles; the documents attached are chosen when the context is built | Accepted |
| [0043](0043-arm-b-adds-whole-documents-in-rank-order-up-to-the-cap.md) | Arm B adds whole documents in a published rank order and stops at the cap; omissions are recorded and counted | Accepted; item 2 superseded by 0048 |
| [0044](0044-amateur-built-replacement-applies-to-document-text.md) | The amateur-built replacement applies to document text, in the attach step, counted as a floor | Accepted; extends 0020 |
| [0045](0045-monthly-budget-is-a-reservation-under-a-lock.md) | The monthly budget is a reservation taken under a lock at run start and settled at the end | Accepted; fixes the 0030 guard |
| [0046](0046-known-owner-and-operator-names-are-replaced-in-document-text.md) | The owner and operator names the record already holds are replaced in document text; full strings only | Accepted; extends 0020, 0044 |
| [0047](0047-pypdf-extracts-docket-text-no-ocr.md) | `pypdf` extracts docket text, a page that fails counts zero, and there is no OCR in S2 | Accepted; corrected 2026-09-21 (the pin is `pypdf[crypto]`); page half adjusted by 0053 |
| [0048](0048-arm-b-ranks-by-each-documents-measured-size.md) | Arm B ranks by each document's own measured size; the category's other jobs are gone (0051, 0052, 0054) | Accepted; supersedes 0043 item 2; superseded in part by 0051, 0052, 0054 |
| [0049](0049-the-name-line-is-the-public-surface-not-the-repository.md) | Names may stay in committed NTSB listing pages; the guard is this project's own public surfaces | Accepted; supersedes 0037 item 2's reason and its "a public repository is an output"; extends 0020, 0044, 0046 |
| [0050](0050-tripwire-skips-factual-narrative-sentences-in-docket-documents.md) | In docket documents the tripwire skips factual-narrative sentences; refusals fall from 38.9% to 4.2% of cases | Accepted; extends 0019 |
| [0051](0051-the-document-header-drops-the-provenance-clause.md) | The document header drops the provenance clause and states how many pages held readable text | Accepted; supersedes 0038 item 2, narrows 0048 item 4 |
| [0052](0052-arm-b-attaches-every-readable-document.md) | Arm B attaches every document extraction found text in; the photograph exclusion and `ARM_B_TYPES` go | Accepted; supersedes 0048 item 3, narrows 0039 item 3; item 4 corrected 2026-09-21 (0054, 0055, 0056); its open defect resolved by 0053 |
| [0053](0053-a-page-of-fifty-characters-is-readable.md) | A page with 50 or more characters is readable; "attached" now implies "has a readable page" by arithmetic | Accepted; resolves the defect 0052 records, adjusts 0047 |
| [0054](0054-the-party-submission-comparison-is-retired.md) | The party-submission comparison is retired: the category finds only NTSB-labelled submissions, not the population | Accepted; retires 0038 item 4, removes the `no-submissions` variant |
| [0055](0055-the-document-header-carries-the-listing-number.md) | The document header identifies a document by its listing number, not an inferred category label | Accepted; amends 0051 item 3 |
| [0056](0056-the-deny-list-cannot-be-filled-from-titles.md) | The deny-list cannot be filled from titles and is removed; the category keeps no job in the live path | Accepted; completes and removes 0039 items 1-2 |
| [0057](0057-unset-directory-settings-derive-from-data-dir.md) | An unset directory setting derives from `data_dir` | Accepted |
| [0058](0058-ci-installs-the-word-list-the-title-check-needs.md) | Continuous integration installs the word list the title check needs | Accepted; amended by 0070 |
| [0059](0059-every-script-states-its-status.md) | Every script in `scripts/` states its kind, its output and what has since changed, in its docstring | Accepted |
| [0060](0060-every-watched-case-is-polled-daily-no-tiers.md) | Every watched case is polled once a day, with no tiers; tiering considered and rejected | Accepted |
| [0061](0061-the-recorder-reads-the-listing-only-never-a-document.md) | The recorder reads the listing page only and never downloads a document | Accepted |
| [0062](0062-the-document-number-is-the-key-with-three-events.md) | The document number in the link is the key; three events; suspected re-numbers are counted | Accepted |
| [0063](0063-a-compressed-listing-page-is-kept-when-its-hash-is-new.md) | A compressed copy of the listing page is kept whenever its hash is new | Accepted |
| [0064](0064-closure-rules-and-the-thirty-day-tail.md) | Closure: status changes are events, nothing is deleted, the verdict is never stored, the docket is watched 30 days after | Accepted |
| [0065](0065-event-months-are-the-source-of-truth-the-change-feed-is-stored-beside-them.md) | The event months are re-fetched nightly as the source of truth; the change feed is stored beside them and compared by script | Accepted; departs from the roadmap's "by modification date" |
| [0066](0066-the-recorder-fetches-with-the-docket-cache-off.md) | The recorder fetches with the docket client's cache off and keeps its own copies | Accepted |
| [0067](0067-watched-cases-are-part-91-plus-empty-regulation.md) | Watched cases are Part 91 plus those with the regulation empty; regulation changes are counted at 8 weeks | Accepted |
| [0068](0068-arrival-is-recorded-per-document-with-no-type-label.md) | Arrival is recorded per document with no type label; the mask's docket rule is presence and count | Accepted; amends the agency design §6.2 |
| [0069](0069-the-ntsb-key-reaches-the-task-from-parameter-store.md) | The NTSB key reaches the scheduled task from AWS Parameter Store, encrypted | Accepted |
| [0070](0070-the-word-list-is-vendored-into-the-repository.md) | The word list is vendored into the repository | Accepted; amends 0058 |
| [0071](0071-the-coverage-threshold-is-deferred-to-s3-as-a-mark-not-a-refusal.md) | The leakage guard's coverage threshold is deferred to the start of S3, reframed as a mark rather than a refusal | Accepted |
| [0072](0072-recorders-one-exempted-import-link.md) | The recorder's call to `split_record` is the one link exempted from the synthesis-and-verdict import rule | Accepted; narrows 0016 |
| [0073](0073-the-default-model-is-gpt-6-luna-behind-a-gate.md) | The default model is GPT-6 Luna, behind a shape probe and a 1% format gate, at a reasoning level set to `medium` and recorded | Accepted; gate passed 2026-09-24; replaces 0031 item 1 |
| [0092](0092-s25-closes-on-four-nights-report-and-cost-follow.md) | S2.5 closes on four recorded nights; the 14-night report and billed cost follow as a dated addendum | Accepted |
