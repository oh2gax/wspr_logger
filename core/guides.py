"""Guides: the PDF documents in the doc/ folder that the page lists under "Guides".

The optional manifest doc/guides.json gives each file a title, a short description
and a date (and sets the order); a PDF that is not in the manifest is still listed,
with a title made from its file name. Only plain *.pdf names directly inside doc/
are ever served.
"""
import json
import os
import re

_NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*\.pdf$')


def is_safe_name(name):
    """True for a plain PDF file name (no path separators, no leading dot)."""
    return bool(name) and bool(_NAME.match(name)) and '..' not in name


def list_guides(doc_dir):
    """Return [{file, title, description, date, size_kb}] for the PDFs in doc_dir."""
    manifest = []
    try:
        with open(os.path.join(doc_dir, "guides.json"), encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            manifest = [g for g in data if isinstance(g, dict) and isinstance(g.get("file"), str)]
    except (OSError, ValueError):
        pass
    meta = {g["file"]: g for g in manifest}
    try:
        present = {n for n in os.listdir(doc_dir) if is_safe_name(n) and os.path.isfile(os.path.join(doc_dir, n))}
    except OSError:
        return []
    ordered = [g["file"] for g in manifest if g["file"] in present]
    ordered += sorted(present - set(ordered))
    out = []
    for name in ordered:
        m = meta.get(name, {})
        out.append({
            "file": name,
            "title": str(m.get("title") or name[:-4].replace("_", " ")),
            "description": str(m.get("description") or ""),
            "date": str(m.get("date") or ""),
            "size_kb": round(os.path.getsize(os.path.join(doc_dir, name)) / 1024),
        })
    return out
