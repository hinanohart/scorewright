# scorewright

**Sandboxed, multi-signal, cross-framework fitness scoring for evolution / RSI / agent loops — with an inline anti-gaming integrity layer.**

[![CI](https://github.com/hinanohart/scorewright/actions/workflows/ci.yml/badge.svg)](https://github.com/hinanohart/scorewright/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

> Status: **pre-alpha (v0.1.0a1)**. APIs may change. Core is dependency-free
> (standard library only). Measured numbers in this README are produced by
> `benchmarks/run_bench.py` on the hardware/date noted next to each figure;
> figures that require an API key are shown as `N/A` when no key is present.

## Why

Every evolution / self-improvement / agent loop needs a *fitness function*: a
way to turn "this candidate program" into numbers the search can climb. In
practice each project re-implements its own `evaluate.py` — re-deriving how to
sandbox candidate code, how to time it, how to price its token usage, how to
ask an LLM judge for a score, and (almost always skipped) how to tell whether
the candidate is **gaming the scorer** rather than solving the task.

scorewright is the reusable layer for that. It is:

- **Multi-signal** — correctness, performance, cost, and LLM-judge quality are
  separate, composable scorers, each emitting *measured* values only.
- **Sandboxed** — candidate code runs under a subprocess sandbox with
  CPU/memory/file-descriptor limits, wall-clock timeout, a temp working
  directory, and an environment allow-list (no ambient secrets leak in), plus
  optional best-effort network isolation. This is OS-level hardening, **not a
  hard security boundary**: it raises the bar against accidental damage and
  resource abuse, but for genuinely untrusted code use a VM/container backend
  (the `microsandbox` extra) or a disposable, network-isolated VM.
- **Cross-framework** — adapters convert scorewright's intermediate
  representation into the shape a host framework expects. v0.1.0a1 ships an
  **OpenEvolve** adapter; a `verifiers` adapter is planned for v0.2.
- **Gaming-aware** — an `AntiGamingScorer` adds *integrity* signals as a
  first-class part of fitness: held-out divergence, performance
  self-consistency, and structured-output anchoring. **Warn-only by default**;
  fail-closed is opt-in.

### What scorewright deliberately is **not**

- Not an evolution engine, not a search algorithm — it scores; your loop
  searches.
- Not a reward-hacking *detector* with completeness guarantees. The integrity
  layer is a **best-effort, multi-signal, opt-in-fail-closed** set of heuristics
  that flags suspicious candidates and biases toward the safe side on
  uncertainty. It does not, and does not claim to, catch all gaming.

## Install

```bash
pip install scorewright            # core (standard library only)
pip install "scorewright[openevolve]"   # + run the OpenEvolve example/bench
pip install "scorewright[microsandbox]" # + VM-isolated backend (stub in 0.1.0a1)
```

## Quickstart

```python
from pathlib import Path
from scorewright import Candidate, CompositeScorer
from scorewright.sandbox import SubprocessSandbox
from scorewright.scorers import CorrectnessScorer, PerfScorer

sandbox = SubprocessSandbox(cpu_seconds=10, memory_mb=512, timeout_s=30)
# fs isolation and the memory limit are on by default; pass allow_network=False
# for best-effort network isolation (requires Python 3.12+ / a permitting kernel).

scorer = CompositeScorer([
    CorrectnessScorer(sandbox, test_command=["python", "-m", "pytest", "-q"]),
    PerfScorer(sandbox, command=["python", "solution.py"], repeats=5),
])

candidate = Candidate(path=Path("./candidate_program"))
for result in scorer.score_all(candidate):
    print(result.scorer, result.ok, [(s.name, s.value, s.unit) for s in result.signals])
```

`scorewright` measures; it does not silently aggregate. Combining signals into a
single fitness number is the caller's (or the adapter's) responsibility, so the
weighting stays explicit and auditable.

### Plugging into OpenEvolve

```python
from scorewright.adapters.openevolve import to_openevolve_evaluator

evaluate = to_openevolve_evaluator(scorer)   # -> Callable[[str], dict[str, float]]
# pass `evaluate` where OpenEvolve expects an evaluation function
```

### Catching scorer gaming

```python
from scorewright.scorers import AntiGamingScorer, is_flagged

integrity = AntiGamingScorer(
    sandbox,
    visible_test_command=["python", "-m", "pytest", "test_visible.py", "-q"],
    heldout_test_command=["python", "-m", "pytest", "test_heldout.py", "-q"],
    perf_command=["python", "solution.py"],
)
result = integrity.score(candidate)   # warn-only: always measures, never rejects
print(is_flagged(result))             # True if any integrity signal tripped
print(result.signal("integrity_flagged").raw["reasons"])
```

The scorer only *measures* (warn-only) — the reject decision is opt-in at the
judgment layer. Wire it through the adapter to fail closed:

```python
evaluate = to_openevolve_evaluator(
    CompositeScorer([correctness, perf, integrity]),
    aggregate=my_aggregate,
    reject_on_gaming=True,   # flagged candidates get reject_score
)
```

## Benchmark

`benchmarks/run_bench.py` scores a fixed suite of candidate programs through the
scorers and the OpenEvolve-adapter interface (no live LLM or evolution run is
needed), and records correctness, performance, cost, and the anti-gaming
**caught-rate** (fraction of deliberately-planted gaming candidates that the
integrity layer flags). Each run is stamped with its environment
(`os, machine, python, date, scorewright version, perf_repeats`) and written to
`benchmarks/results/`.

Measured on `Linux-6.6 WSL2 x86_64`, Python 3.12.3, 2026-05-24 (UTC),
5-task suite, `perf_repeats=4` — reproduce with `python benchmarks/run_bench.py`
(raw output in [`benchmarks/results/`](benchmarks/results/)):

| Signal | Value | Notes |
|---|---|---|
| Anti-gaming **caught-rate** | **1.0** (3/3) | held-out & judge-injection catches are exact; the perf-variance catch fires on a large, machine-robust timing margin (CV 0.92 vs 0.5 threshold) |
| Anti-gaming **false-positive-rate** | **0.0** (0/2) | honest candidates not flagged |
| Correctness (honest pass-rate) | **1.0** | deterministic |
| Perf (median wall-time, honest) | ~0.022 s | machine dependent; compare only within the same environment |
| Cost (per honest candidate) | $0.00024 | computed from recorded token usage × the **example** pricing snapshot (not authoritative) |

> The caught-rate is over a small, hand-built suite of *known* strategies — a
> demonstration that the checks fire on what they target, not a coverage claim
> against reward-hacking in the wild. Cost figures require a pricing table and
> recorded token usage; with neither present the cost signal reports `ok=False`
> rather than a fabricated number. See [benchmarks/README.md](benchmarks/README.md)
> for methodology and caveats.

## Design

```
src/scorewright/
  types.py        # ScoreResult / Signal — the intermediate representation (IR)
  scorer.py       # Scorer protocol + CompositeScorer (runs scorers, never aggregates)
  _pricing.py     # ModelPrice + a clearly-dated EXAMPLE pricing snapshot
  sandbox/        # SubprocessSandbox (default) + microsandbox stub (extra)
  scorers/        # correctness, perf, cost, llm_judge, anti_gaming
  adapters/       # openevolve (IR -> native, pure conversion)
```

**Measurement vs. judgment.** Scorers *measure* and return `Signal`s with units
and a `higher_is_better` flag. They never normalize or weight. Aggregation is a
separate, explicit step in the adapter or your loop.

**Honest failure.** A scorer that cannot run (missing API key, missing pricing,
execution error) returns `ScoreResult(ok=False, error=...)` with no signals. It
never invents a value.

## Audit-trail integration (memcanon)

[`memcanon`](https://github.com/hinanohart/memcanon) v0.2+ accepts events
from this repo via a thin in-process shim and content-hashes them into a
local audit store:

> memcanon is not on PyPI yet. Install it from the tagged release:
>
> ```bash
> pip install "git+https://github.com/hinanohart/memcanon@v0.2.0a2"
> ```

```python
from memcanon.emit import emit
from memcanon.store.local import LocalStore

with LocalStore("audit") as store:
    emit("scorewright", {"kind": "...", "decision": "..."}, store=store)
```

Each record is tagged `source:scorewright` + `schema:memcanon-emit/1`. Memcanon's
`memcanon export --format eu-ai-act-12 --to OUT.json` can then build an
Article 12(2) paragraph-mapped audit-log artefact (SHAPE only, NOT a
conformity assessment).

## License

MIT. See [LICENSE](LICENSE).
