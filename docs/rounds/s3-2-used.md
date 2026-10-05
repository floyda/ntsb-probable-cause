# S3.2: held-out used (decision 0142)

S3.2's single use of `heldout-400` is complete. Its runs, in the held-out ledger
(`docs/results/heldout-ledger.md`), are arm A, arm B's answer (one aborted attempt, then the
run), its tool post-pass and ordering check, the loop, and the loop without the docket, all on
2026-10-04. Their reading is `docs/results/s32-claims-heldout.txt`.

From the commit that adds this file, `checkpass.heldout_open` and
`agent/run.py:refuse_unregistered_heldout` refuse any new held-out arm B post-pass, ordering
check or arm C run that S3.2's registration had opened. A later held-out measurement needs its
own decision record and its own registration (decision 0140 item 4).
