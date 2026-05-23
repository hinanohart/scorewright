# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
(pre-release suffixes per PEP 440).

## [0.1.0a1] — 2026-05-24

Initial pre-alpha release.

### Added
- Intermediate representation: `Signal`, `ScoreResult`, `SignalKind`, `Candidate`.
- `Scorer` protocol and `CompositeScorer` (runs scorers, collects results,
  performs no aggregation).
- `SubprocessSandbox`: subprocess execution with `resource` rlimits
  (address space, CPU, open files), wall-clock timeout with process-group kill,
  temp working-directory isolation, and an environment allow-list.
- `_microsandbox` backend: import-guarded interface stub (full backend planned
  for v0.2).
- Scorers: `CorrectnessScorer` (pytest), `PerfScorer` (median wall-time, peak
  RSS), `CostScorer` (token usage × dated pricing table → USD), and
  `LLMJudgeScorer` (GenRM-style, injected client, hardened structured-output
  parsing).
- `AntiGamingScorer`: integrity signals (held-out divergence, performance
  self-consistency, structured-output anchor). Warn-only by default; fail-closed
  is opt-in.
- `adapters.openevolve.to_openevolve_evaluator`: converts the IR into an
  OpenEvolve-compatible evaluation callable.
- Benchmark harness `benchmarks/run_bench.py` with hardware/date-stamped output.

### Notes
- Core has no third-party runtime dependencies (standard library only).
- A `verifiers` adapter and a completed microsandbox backend are planned for
  v0.2.
