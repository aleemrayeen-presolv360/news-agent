"""Telegram notice when a scheduled job fails.

Called from the `if: failure()` step of every workflow. A scheduled pipeline
that fails silently is worse than no pipeline, because you keep trusting it.

    python -m agent.notify_failure
"""

from __future__ import annotations

import os

from . import telegram


def main() -> int:
    job = os.environ.get("GITHUB_WORKFLOW", "news-agent")
    run_url = os.environ.get("RUN_URL", "")
    message = f"⚠️ <b>{job}</b> failed\n{run_url}\n\nThe news pipeline needs a look."
    if not telegram.send(message):
        print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
