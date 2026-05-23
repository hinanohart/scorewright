# Example: scoring through the OpenEvolve adapter

This example builds the `evaluate(program_path) -> dict` callable that OpenEvolve
expects and runs it on a local candidate (`candidate/fib.py`) — **no OpenEvolve
install and no LLM required**. It demonstrates the intended wiring:

1. construct a `SubprocessSandbox`;
2. compose `CorrectnessScorer` + `PerfScorer`;
3. convert to an OpenEvolve evaluator with `to_openevolve_evaluator`, passing an
   explicit `aggregate` (aggregation belongs to the caller, not the scorers);
4. call `evaluate(candidate_dir)` and read the metrics dict.

## Run

```bash
pip install -e ".[dev]"
python examples/openevolve_fib/run_example.py
```

Expected output (values are illustrative; `perf_wall_time_s` is machine
dependent):

```json
{
  "correctness_pass_rate": 1.0,
  "perf_wall_time_s": 0.0173,
  "perf_peak_rss_kb": 11456.0,
  "combined_score": 0.9998
}
```

To plug into a real OpenEvolve run, pass the returned `evaluate` function where
OpenEvolve expects an evaluation function (install the adapter's optional
dependency with `pip install "scorewright[openevolve]"`).
