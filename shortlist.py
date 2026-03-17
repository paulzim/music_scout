# shortlist.py
from __future__ import annotations

import os
from datetime import datetime
from typing import List, Tuple, Optional

from models import CandidateArtist


def write_shortlist(
    path: str,
    scored: List[Tuple[CandidateArtist, float]],
    top_n: int = 10,
    title_override: Optional[str] = None
) -> str:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    title = title_override or f"New Artist Scout Shortlist ({datetime.now().date().isoformat()})"

    lines: List[str] = []
    lines.append(f"# {title}\n\n")
    lines.append(f"Top {top_n} candidates. Each entry includes provenance.\n\n")

    for i, (c, score) in enumerate(scored[:top_n], start=1):
        lines.append(f"## {i}. {c.name}  (score: {score:.2f})\n\n")

        if c.primary_url:
            lines.append(f"- Link: {c.primary_url}\n")

        if c.notes:
            lines.append(f"- Notes: {c.notes}\n")

        if c.evidence:
            lines.append("- Found at:\n")
            for ev in c.evidence[:5]:
                title_suffix = f" — {ev.title}" if ev.title else ""
                lines.append(f"  - [{ev.source_id}] {ev.date}: {ev.url}{title_suffix}\n")

        lines.append("\n")

    content = "".join(lines)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

    return path