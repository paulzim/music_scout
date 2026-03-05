from __future__ import annotations

import os
from datetime import datetime
from typing import List, Tuple

from models import CandidateArtist


def write_shortlist(path: str, scored: List[Tuple[CandidateArtist, float]], top_n: int = 10) -> str:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    lines = []
    lines.append(f"# New Artist Scout Shortlist ({datetime.now().date().isoformat()})\n")
    lines.append(f"Top {top_n} candidates. Each entry includes provenance.\n")

    for i, (c, score) in enumerate(scored[:top_n], start=1):
        lines.append(f"## {i}. {c.name}  (score: {score:.2f})\n")
        if c.primary_url:
            lines.append(f"- Link: {c.primary_url}\n")
        if c.notes:
            lines.append(f"- Notes: {c.notes}\n")
        if c.evidence:
            lines.append("- Found at:\n")
            for ev in c.evidence[:5]:
                title = f" — {ev.title}" if ev.title else ""
                lines.append(f"  - [{ev.source_id}] {ev.date}: {ev.url}{title}\n")
        lines.append("\n")

    content = "".join(lines)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

    return path