# Benchmark tasks

The candidate programs scored by the benchmark are defined as embedded sources
in [`../run_bench.py`](../run_bench.py) (under the `TASKS` list), so a single
file reproduces the entire run without external fixtures.

Each task materializes to a temporary directory at run time with:

- `solution.py` — the candidate program;
- `test_visible.py` — the graded ("visible") tests;
- `test_heldout.py` — held-out tests used for the divergence integrity check.

Gaming tasks additionally carry a ground-truth label (`kind = "gaming:<strategy>"`)
and, for the judge-injection case, a crafted `judge_output`. See
[`../README.md`](../README.md) for the methodology and caveats.
