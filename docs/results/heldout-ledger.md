# Held-out ledger

Every run that touched a held-out sample (decision 0026).

| date | sample | arm | exclusions | includes | model | commit | cost USD | results |
|---|---|---|---|---|---|---|---|---|
| 2026-09-17 | heldout-400 | A | - | - | openai/gpt-5.6-luna | c717ab5 | 0.35 | 20260917T061530-c717ab5-heldout-400-A/cases.jsonl |
| 2026-09-17 | heldout-40 | ceiling | - | - | openai/gpt-5.6-luna | c717ab5 | 0.04 | 20260917T061525-c717ab5-heldout-40-ceiling/cases.jsonl |
| 2026-09-17 | heldout-400 | ceiling | registration | - | openai/gpt-5.6-luna | c717ab5 | 0.46 | 20260917T061532-c717ab5-heldout-400-ceiling/cases.jsonl |
| 2026-09-17 | heldout-400 | ceiling | - | - | openai/gpt-5.6-luna | c717ab5 | 0.49 | 20260917T061527-c717ab5-heldout-400-ceiling/cases.jsonl |
| 2026-09-17 | heldout-400 | ceiling | - | - | anthropic/claude-haiku-4.5 | cc4b763 | 0.72 | 20260917T061527-c717ab5-heldout-400-ceiling/judge.jsonl |
| 2026-09-21 | heldout-400 | B | - | - | openai/gpt-5.6-luna | 3bc3a51 | 2.00 | 20260921T071430-3bc3a51-heldout-400-B/cases.jsonl |
| 2026-09-21 | heldout-400 | — (leakage scan, no model call) | - | - | none | cc73ebf | 0.00 | docs/results/s2-narrative-coverage-heldout.txt |
| 2026-09-24 | heldout-400 | ceiling | - | - | openai/gpt-6-luna | 05c5c5b | 0.24 | 20260924T070202-05c5c5b-heldout-400-ceiling/cases.jsonl |
| 2026-09-24 | heldout-400 | B — ABORTED: OpenRouter lost the stage-1 retry batch after 10 h queued (404); 40 refused by the guard, 360 unanswered, none scored; re-run fresh by Andy's decision | - | - | openai/gpt-6-luna | 36bcd22 | 0.58 | 20260924T075506-36bcd22-heldout-400-B/cases.jsonl |
