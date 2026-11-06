"""
changelog.py — turns CHANGELOG.md into the data for the "What's new" window.

The changelog is the single source of truth: every bullet in it starts with a
bold title (``- **Title** — details``); only that title is shown in the window.
Entries are grouped by date, so two headings of the same day are merged.

Version label: ``v.DDMMYYYY`` taken from the date of the newest entry,
e.g. 6 November 2026 -> ``v.06112026``.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

_HEAD = re.compile(r"^## \[(\d{4}-\d{2}-\d{2})[^\]]*\]")
_SECT = re.compile(r"^### (\w+)")
MAX_TITLE = 140


def _title(text: str) -> str:
    """Short, plain-text title of one changelog bullet."""
    text = " ".join(text.split())
    m = re.match(r"\*\*(.+?)\*\*", text)
    if m:
        t = m.group(1)
    else:
        t = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)   # [text](url) -> text
    t = t.replace("`", "").replace("*", "").strip().rstrip(" .—-")
    if len(t) > MAX_TITLE:
        t = t[:MAX_TITLE - 1].rstrip() + "…"
    return t


def parse(text: str) -> list[dict]:
    """
    Return [{"date": "YYYY-MM-DD", "sections": [{"name": "Added", "items": [...]}]}]
    in file order (newest first), merging headings that share a date.
    """
    entries: dict[str, dict[str, list[str]]] = {}
    order: list[str] = []
    cur_date = cur_sect = None
    bullet: list[str] | None = None

    def flush():
        nonlocal bullet
        if bullet is not None and cur_date and cur_sect:
            title = _title(" ".join(bullet))
            if title:
                entries[cur_date].setdefault(cur_sect, []).append(title)
        bullet = None

    for line in text.splitlines():
        h = _HEAD.match(line)
        if h:
            flush()
            cur_date, cur_sect = h.group(1), None
            if cur_date not in entries:
                entries[cur_date] = {}
                order.append(cur_date)
            continue
        s = _SECT.match(line)
        if s:
            flush()
            cur_sect = s.group(1)
            continue
        if line.startswith("- "):
            flush()
            bullet = [line[2:]]
        elif bullet is not None:
            if line.startswith("  ") and line.strip():
                bullet.append(line.strip())
            elif not line.strip():
                flush()                      # blank line ends the bullet
            else:
                flush()
    flush()

    out = []
    for d in order:
        secs = [{"name": n, "items": items} for n, items in entries[d].items() if items]
        if secs:
            out.append({"date": d, "sections": secs})
    return out


def version_label(iso_date: str) -> str:
    """'2026-11-06' -> 'v.06112026'."""
    y, m, d = iso_date.split("-")
    return f"v.{d}{m}{y}"


def whats_new(text: str, today: date, days: int = 10) -> dict:
    """Entries of the last *days* days (newest first); the newest entry if none."""
    entries = parse(text)
    if not entries:
        return {"version": "", "latest": "", "days": days, "entries": []}
    cutoff = (today - timedelta(days=days)).isoformat()
    recent = [e for e in entries if e["date"] >= cutoff]
    if not recent:
        recent = entries[:1]
    latest = max(e["date"] for e in entries)
    return {"version": version_label(latest), "latest": latest,
            "days": days, "entries": recent}
