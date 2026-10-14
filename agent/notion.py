"""Notion client, shared by publish, addendum and retention."""

from __future__ import annotations

from notion_client import Client

from .config import env


def get_client() -> Client:
    return Client(
        auth=env("NOTION_TOKEN", required=True),
        notion_version=env("NOTION_VERSION", "2022-06-28"),
    )
