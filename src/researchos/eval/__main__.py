"""Command-line entry point for the ResearchOS evaluation harness.

Usage::

    python -m researchos.eval
    python -m researchos.eval --json --out benchmark-report.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

from researchos.eval.benchmark import BenchmarkRunner
from researchos.eval.dataset import get_default_contradiction_benchmark


def main(argv: Optional[Sequence[str]] = None) -> int:
    command_args = list(argv) if argv is not None else sys.argv[1:]
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
    args = parser.parse_args(command_args)

    suite = get_default_contradiction_benchmark()
    runner = BenchmarkRunner(suite, k=args.k)
    metrics = runner.run_benchmark()
    report = runner.run_report(metrics)
    repository_root = Path(__file__).resolve().parents[3]
    source_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    working_tree_dirty = bool(subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repository_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip())
    report["run"] = {
        "date_utc": datetime.now(timezone.utc).date().isoformat(),
        "command": " ".join(
            [sys.executable, "-m", "researchos.eval", *command_args]
        ),
        "source_commit": source_commit,
        "working_tree_dirty": working_tree_dirty,
        "limitations": [
            "Synthetic benchmark with five papers and ten questions; results are not statistically significant.",
            "Answer and provenance metrics use normalized substring matching.",
            "Flat baselines use a deterministic hashed lexical embedder, not semantic embeddings.",
            "CtxFlow graph evaluation queries the graph directly and does not run agents.",
            "Supersession links are manually injected from benchmark annotations; automatic detection is not evaluated.",
            "Context tokens are estimated as four characters per token.",
            "The multi-agent-shaped flat baseline over-fetches 2k candidates while retaining at most k context items.",
        ],
    }

    if args.out:
        output_path = Path(args.out)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as handle:
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
