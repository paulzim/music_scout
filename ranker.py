from __future__ import annotations

from typing import List, Tuple
from models import CandidateArtist, UserProfile


def score_candidates(user: UserProfile, candidates: List[CandidateArtist]) -> List[Tuple[CandidateArtist, float]]:
    """
    v1 heuristic scorer:
    - slight boost if candidate notes/evidence contains genre keywords
    - boost if name looks non-generic (weak)
    - later you can add embedding similarity, followers, recency, etc.
    """
    wanted = set(g.lower() for g in user.genres)
    scored: List[Tuple[CandidateArtist, float]] = []

    for c in candidates:
        s = 0.0
        text = " ".join(filter(None, [
            c.name,
            c.notes or "",
            " ".join(ev.title or "" for ev in c.evidence),
            " ".join(c.genres_detected),
        ])).lower()

        for g in wanted:
            if g in text:
                s += 1.0

        if len(c.name) > 6:
            s += 0.2

        # Prefer candidates with outbound links
        if c.primary_url:
            s += 0.2

        scored.append((c, s))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored