"""Telegram messaging, shared by alerts, the Monday audit and failure notices."""

from __future__ import annotations

import sys

import httpx

from .config import env


def is_configured() -> bool:
    return bool(env("TELEGRAM_TOKEN") and env("TELEGRAM_CHAT"))


def send(text: str, *, link_preview: bool = False) -> bool:
    """Send an HTML-formatted message. Returns False (never raises) on failure."""
    if not is_configured():
        print("telegram: not configured (set TELEGRAM_TOKEN and TELEGRAM_CHAT)", file=sys.stderr)
        return False
    try:
        httpx.post(
            f"https://api.telegram.org/bot{env('TELEGRAM_TOKEN')}/sendMessage",
            json={
                "chat_id": env("TELEGRAM_CHAT"),
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": not link_preview,
            },
            timeout=15,
        ).raise_for_status()
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"telegram: send failed: {exc}", file=sys.stderr)
        return False
