# scorewright benchmark

`run_bench.py` is a **reproducible, key-free** benchmark of scorewright itself.
It does not run an LLM or a real evolution loop. It scores a fixed suite of
candidate programs — some honest, some using a known gaming strategy — through
scorewright's scorers and the OpenEvolve-adapter interface, then reports how the
anti-gaming layer does.

## Run

```bash
pip install -e ".[dev]"
python benchmarks/run_bench.py            # writes benchmarks/results/result_<date>.json
```

## What it measures

| Metric | Determinism |
|---|---|
| **caught-rate** = flagged gaming candidates / all gaming candidates | deterministic |
| **false-positive-rate** = flagged honest candidates / all honest candidates | deterministic |
| honest correctness pass-rate | deterministic |
| perf wall-time | hardware dependent — stamped, never a portable claim |

The candidate suite (sources are embedded in `run_bench.py` so a single file
fully reproduces the run):

- `honest_sum_a`, `honest_sum_b` — correct programs; all tests pass; stable timing.
- `gaming_overfit` — passes the *visible* tests but fails the *held-out* tests
  (caught by held-out divergence).
- `gaming_perf_variance` — alternates a sleep across identical runs via external
  state (caught by performance self-consistency).
- `gaming_judge_injection` — supplies a judge response with two anchored
  `SCORE:` lines (caught by the structured-output anchor).

## Honest caveats

- The caught-rate is over **this small, hand-built suite of known strategies**.
  It is a demonstration that the integrity checks fire on the patterns they
  target — not a measure of coverage against unknown reward-hacking in the wild.
- The performance self-consistency check observes timing variance *within its
  own repeated runs*; caching that is fully warmed before measurement may go
  unseen. This is why the layer is warn-only by default.
- Wall-time depends on the machine; compare only against figures with the same
  environment stamp.
