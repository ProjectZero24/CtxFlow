"""Command-line entry point for the ResearchOS evaluation harness.

Usage::

    python -m researchos.eval
    python -m researchos.eval --json --out benchmark-report.json
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Optional, Sequence

from researchos.eval.benchmark import BenchmarkRunner
from researchos.eval.dataset import get_default_contradiction_benchmark


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="researchos-eval",
        description=(
            "Compare CtxFlow graph memory against flat-vector RAG "
            "baselines on the superseded-claim benchmark."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the full report as JSON instead of a markdown table.",
    )
    parser.add_argument(
        "--out",
        default="",
        help="Optional path to write the JSON report to.",
    )
    parser.add_argument(
        "--k",
        type=int,
        default=5,
        help="Number of retrieved items per query (default: 5).",
    )
    args = parser.parse_args(argv)

    suite = get_default_contradiction_benchmark()
    runner = BenchmarkRunner(suite, k=args.k)
    metrics = runner.run_benchmark()
    report = runner.run_report()

    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2)
            handle.write("\n")

    if args.json:
        json.dump(report, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(f"Benchmark suite: {suite.name}")
        print(f"Papers: {len(suite.papers)} | Questions: {len(suite.questions)}")
        print()
        print(runner.format_report(metrics))
        if args.out:
            print(f"\nJSON report written to {args.out}")

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
