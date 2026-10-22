"""Run the full pipeline locally.

Convenience script to run all stages in sequence for testing.

    python -m agent.pipeline --dry-run   # test all stages without DB/API writes
    python -m agent.pipeline             # run full pipeline
    python -m agent.pipeline --stage score  # run from specific stage
"""

from __future__ import annotations

import argparse

STAGES = [
    ("ingest", "agent.ingest"),
    ("triage", "agent.triage"),    # first: free, and stops papers crowding out news
    ("extract", "agent.extract"),
    ("embed", "agent.embed"),
    ("score", "agent.score"),
    ("cluster", "agent.cluster"),
    ("threads", "agent.threads"),
    ("publish_static", "agent.publish_static"),  # website data first, so it never waits on Notion
    ("publish", "agent.publish"),                # optional Notion digest; needs NOTION_* settings
]


def run(dry_run: bool = False, stage: str | None = None, limit: int | None = None) -> int:
    """Run pipeline stages in sequence."""
    start_idx = 0
    if stage:
        for i, (name, _) in enumerate(STAGES):
            if name == stage:
                start_idx = i
                break
        else:
            print(f"Unknown stage: {stage}")
            print(f"Available: {', '.join(name for name, _ in STAGES)}")
            return 1

    stages_to_run = STAGES[start_idx:]

    print(f"\n{'=' * 60}")
    print(f"  Pipeline: {len(stages_to_run)} stages" + (" (DRY RUN)" if dry_run else ""))
    print(f"{'=' * 60}\n")

    for name, module in stages_to_run:
        print(f">> Stage: {name}")
        print("-" * 40)

        try:
            mod = __import__(module, fromlist=["run"])
            kwargs = {}
            if dry_run:
                kwargs["dry_run"] = True
            if limit and name in ("ingest", "extract", "embed", "score"):
                kwargs["limit"] = limit

            result = mod.run(**kwargs)
            if result != 0:
                print(f"\n[X] Stage {name} failed with code {result}")
                return result
        except Exception as e:
            print(f"\n[X] Stage {name} error: {e}")
            if not dry_run:
                return 1
        print()

    print(f"{'=' * 60}")
    print("  Pipeline complete" + (" (DRY RUN)" if dry_run else ""))
    print(f"{'=' * 60}\n")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Run the full news agent pipeline.")
    ap.add_argument("--dry-run", action="store_true", help="test without DB/API writes")
    ap.add_argument("--stage", type=str, help="start from specific stage")
    ap.add_argument("--limit", type=int, help="limit items per stage")
    args = ap.parse_args()
    return run(dry_run=args.dry_run, stage=args.stage, limit=args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
