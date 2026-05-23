#!/usr/bin/env python3
"""Score a candidate through the OpenEvolve-adapter interface.

This runs end to end without installing OpenEvolve or any LLM: it builds the
same ``evaluate(program_path) -> dict`` callable that OpenEvolve would call and
invokes it on the local candidate directory. To wire it into a real OpenEvolve
run, pass ``evaluate`` where OpenEvolve expects an evaluation function.

Run:  python examples/openevolve_fib/run_example.py
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from pathlib import Path

from scorewright import CompositeScorer
from scorewright.adapters.openevolve import to_openevolve_evaluator
from scorewright.sandbox import SubprocessSandbox
from scorewright.scorers import CorrectnessScorer, PerfScorer

HERE = Path(__file__).parent
CANDIDATE = HERE / "candidate"
PY = sys.executable


def main() -> int:
    sandbox = SubprocessSandbox(memory_mb=None, cpu_seconds=30, timeout_s=60)
    scorer = CompositeScorer(
        [
            CorrectnessScorer(
                sandbox,
                test_command=[PY, "-m", "pytest", "-q", "--tb=no", "-p", "no:cacheprovider"],
            ),
            PerfScorer(sandbox, command=[PY, "fib.py"], repeats=3),
        ]
    )

    # Aggregation lives here, in the caller — pass-rate as the primary objective,
    # lightly penalized by runtime. scorewright's scorers never aggregate.
    def aggregate(m: Mapping[str, float]) -> float:
        return m.get("correctness_pass_rate", 0.0) - 0.01 * m.get("perf_wall_time_s", 0.0)

    evaluate = to_openevolve_evaluator(scorer, aggregate=aggregate)
    metrics = evaluate(str(CANDIDATE))
    print(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
