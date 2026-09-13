## What this changes

## Checks

- [ ] `make check` passes locally
- [ ] Plan tasks ticked in the same commits as their code; deviations logged in the plan
- [ ] Any significant departure from the specification has a decision record

## Stage close-out (only for the pull request that finishes a stage — decision 0017)

- [ ] `close-stage` skill run
- [ ] Specification status `Implemented`, with date and this pull request
- [ ] As-built section has all five parts: Delivered; Done means, with evidence; Departures from this specification; Decisions taken during the stage; Implementation record
- [ ] Roadmap stage entry marked done and linked
- [ ] Plan file deleted; permalink to its last commit recorded in the As-built section
- [ ] `uv run python -m scripts.check_docs` passes
