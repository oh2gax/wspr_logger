"""
changelog.py — reads doc/whats_new.md for the "What's new" window.

The file holds short, plain-language notes for the users of the page, newest first,
one section per day of development:

    ## v.06112026 — A headline in a few words

    - **Short lead** — one or two sentences of what changed and what it means for the user.

The technical history (Added / Changed / Fixed) stays in CHANGELOG.md and is not shown in
the window. The version label under the page title is the newest heading, ``v.DDMMYYYY``.
"""
from __future__ import annotations

import re

_HEAD = re.compile(r"^##\s+v\.(\d{2})(\d{2})(\d{4})\s*(?:[—–-]+\s*(.*))?$")
_LEAD = re.compile(r"^\*\*(.+?)\*\*\s*(?:[—–:-]+\s*)?(.*)$")


def _item(text: str) -> dict:
    text = " ".join(text.split())
    m = _LEAD.match(text)
    if m:
        return {"lead": m.group(1).strip(), "text": m.group(2).strip()}
    return {"lead": "", "text": text}


def parse(text: str) -> list[dict]:
    """[{"date": "YYYY-MM-DD", "version": "v.DDMMYYYY", "headline": str, "items": [{"lead", "text"}]}],
    newest first (sorted by date)."""
    entries: list[dict] = []
    cur: dict | None = None
    bullet: list[str] | None = None

    def flush():
        nonlocal bullet
        if bullet is not None and cur is not None:
            it = _item(" ".join(bullet))
            if it["lead"] or it["text"]:
                cur["items"].append(it)
        bullet = None

    for line in text.splitlines():
        h = _HEAD.match(line)
        if h:
            flush()
            dd, mm, yyyy, head = h.groups()
            cur = {"date": f"{yyyy}-{mm}-{dd}", "version": f"v.{dd}{mm}{yyyy}",
                   "headline": (head or "").strip(), "items": []}
            entries.append(cur)
            continue
        if line.startswith("- "):
            flush()
            bullet = [line[2:]]
        elif bullet is not None:
            if line.startswith("  ") and line.strip():
                bullet.append(line.strip())            # a wrapped line of the same bullet
            else:
                flush()
    flush()
    entries = [e for e in entries if e["items"]]
    entries.sort(key=lambda e: e["date"], reverse=True)
    return entries


def whats_new(text: str, limit: int = 10) -> dict:
    """The newest *limit* versions and the version label of the newest."""
    entries = parse(text)
    if not entries:
        return {"version": "", "latest": "", "entries": []}
    return {"version": entries[0]["version"], "latest": entries[0]["date"], "entries": entries[:limit]}
