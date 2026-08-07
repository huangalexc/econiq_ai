"""``econiq-eval`` — run the harness against a database.

Exits non-zero on a blocking failure so CI can gate on it. The audits and the
fault-injection benchmark need no labelled data, so this is runnable against any
environment from the day it is installed; the benchmark sections appear as the
datasets are filled in.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from econiq_data_models import DatabaseSettings, create_engine, create_session_factory

from econiq_eval.harness import render_markdown, run_harness
from econiq_eval.phase0 import STANDING_NOTES, evaluate_phase0
from econiq_eval.phase0 import render_markdown as render_phase0
from econiq_eval.runs import RunLedger


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="econiq-eval", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Audits and fault injection against the database")
    run.add_argument("--output", type=Path, help="Write the markdown report here")
    run.add_argument(
        "--no-faults",
        action="store_true",
        help="Skip fault injection (it writes and rolls back inside a transaction)",
    )

    phase0 = sub.add_parser(
        "phase0",
        help="Evaluate an existing database against PRD §28 (read-only)",
    )
    phase0.add_argument("--output", type=Path, help="Write the markdown report here")
    phase0.add_argument(
        "--provider",
        default="unknown",
        help="Which provider produced this graph. Recorded in the report so a "
        "scripted run is never mistaken for model validation.",
    )

    prompts = sub.add_parser("prompts", help="Per-prompt-version operational statistics")
    prompts.add_argument("--agent", help="Restrict to one agent")
    prompts.add_argument("--baseline", help="Prompt version to compare from")
    prompts.add_argument("--candidate", help="Prompt version to compare to")

    return parser


async def _run(args: argparse.Namespace) -> int:
    engine = create_engine(DatabaseSettings())
    factory = create_session_factory(engine)
    try:
        report = await run_harness(factory, inject_faults=not args.no_faults)
        markdown = render_markdown(report)
        if args.output:
            args.output.write_text(markdown)
        print(markdown)
        for reason in report.blocking_failures:
            print(f"BLOCKING: {reason}", file=sys.stderr)
        return 0 if report.passed else 1
    finally:
        await engine.dispose()


async def _phase0(args: argparse.Namespace) -> int:
    """Read-only. Populating the corpus is the test suite's job, not a CLI flag —
    a command that truncated a database to run a benchmark would eventually be
    pointed at one that mattered."""
    engine = create_engine(DatabaseSettings())
    factory = create_session_factory(engine)
    try:
        report = await evaluate_phase0(factory, provider=args.provider)
        markdown = render_phase0(report, notes=STANDING_NOTES)
        if args.output:
            args.output.write_text(markdown)
        print(markdown)
        return 0 if report.passed else 1
    finally:
        await engine.dispose()


async def _prompts(args: argparse.Namespace) -> int:
    engine = create_engine(DatabaseSettings())
    factory = create_session_factory(engine)
    try:
        ledger = RunLedger(factory)
        if args.baseline and args.candidate:
            if not args.agent:
                print("--agent is required when comparing versions", file=sys.stderr)
                return 2
            comparison = await ledger.compare(
                args.agent, baseline=args.baseline, candidate=args.candidate
            )
            if comparison is None:
                print(
                    f"No runs recorded for one of {args.baseline}/{args.candidate} — "
                    "nothing to compare.",
                    file=sys.stderr,
                )
                return 2
            print(comparison.summary())
            return 1 if comparison.regressed else 0

        for stats in await ledger.stats(agent_name=args.agent):
            print(stats.as_dict())
        unversioned = await ledger.unversioned_runs()
        if unversioned:
            print(
                f"\n{len(unversioned)} run(s) carry no prompt version — "
                "they cannot be compared across prompt changes (agent doc §21).",
                file=sys.stderr,
            )
        return 0
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handler = {"run": _run, "phase0": _phase0, "prompts": _prompts}[args.command]
    return asyncio.run(handler(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
