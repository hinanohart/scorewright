# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
(pre-release suffixes per PEP 440).

## [0.1.0a2] — 2026-05-24

Robustness and correctness fixes from a post-release adversarial audit. No
public API changes.

### Fixed
- `SubprocessSandbox`: the child process is now **unconditionally reaped** even
  if output pumping raises, so a failure can no longer leave an orphaned/zombie
  child holding resource limits.
- `SubprocessSandbox`: the post-timeout output drain is **time-bounded**, so a
  grandchild that escapes the process group (e.g. by calling `setsid` itself)
  and holds a pipe open can no longer make the parent block past its wall-clock
  timeout.
- `SubprocessSandbox`: pipe file descriptors are cleaned up if `os.fork()`
  fails, preventing an fd leak under load.
- `CorrectnessScorer` / `AntiGamingScorer`: pytest pass-rates are parsed only
  from the genuine summary line (anchored, last-match) **and reconciled against
  pytest's exit code**, which a candidate cannot forge. A candidate that prints
  fake counts — even a fake summary at process exit — can therefore no longer
  report success while pytest reports failure, so it cannot inflate the
  pass-rate the integrity layer trusts (the held-out divergence check).
- `AntiGamingScorer`: the `integrity_perf_cache_ratio` signal is always emitted
  (neutral `1.0` when timings are sub-resolution), so the set of integrity
  signals is deterministic.

### Changed
- `SubprocessSandbox`: a failed `exec` now writes a short diagnostic to the
  child's stderr before exiting 127.
- The benchmark harness is now type-checked under mypy strict (and ruff) in CI.

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
