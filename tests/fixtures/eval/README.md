# Evaluation case lists

Copied by `scripts/copy_eval_ids.py` from the spike repository at commit `1f768ba`: `labelling/decidability.filled.csv` (the 40-case like-for-like set) and `labelling/leakage.filled.csv`. Event dates come from the spike's processed file. **Case id and event date only.** Every case in both sheets is held-out by event date, and the 40-case sheet is the `heldout-40` sample itself, so the spike's own cause, finding-code and factual-account columns are withheld data (0013) and are not copied here at all. `scripts/check_fixtures_redacted.py` fails if a fixture CSV grows a column carrying them.

`dev_seal_400_ids.csv`: the sealed development sample, decision 0095; drawn by `scripts/draw_sealed.py`, seed 20260926, excluding `dev-400`; opened once.

`dev_seal_s3_400_ids.csv`: S3's sealed development sample, decision 0129; drawn by `scripts/draw_sealed.py --sample dev-seal-s3-400`, seed 20260930, excluding `dev-400` and `dev-seal-400`. Refused by every command until S3.2's registration (`docs/rounds/s3-registration.md`) is committed. Case id and event date only.
