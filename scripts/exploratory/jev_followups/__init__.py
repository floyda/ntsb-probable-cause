"""Three throwaway follow-ups to the Jev dev-400 result (docs/results/typesafe-jev-dev400.md).

Exploratory, so outside the strict tooling, but every payload used in these modules is built
by ``ntsb_probable_cause.scoring.runner.case_payload``, which runs ``split_record`` and the
leakage guard (decisions 0013, 0016), and every number is printed by
``ntsb_probable_cause.scoring.report``'s helpers so intervals are consistent with the rest of
the project. Development split (dev-400) only; no held-out case is touched.
"""
