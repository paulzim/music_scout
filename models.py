from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional


@dataclass
class Evidence:
    source_id: str
    url: str
    date: str  # ISO date string
    title: Optional[str] = None


@dataclass
class CandidateArtist:
    name: str
    canonical_id: str  # e.g. "url|https://..." or "namehash|..."
    primary_url: str
    genres_detected: List[str] = field(default_factory=list)
    evidence: List[Evidence] = field(default_factory=list)
    notes: Optional[str] = None


@dataclass
class UserProfile:
    genres: List[str] = field(default_factory=list)
    constraints: Dict[str, bool] = field(default_factory=lambda: {
        "exclude_major_labels": True,
        "must_have_bandcamp": False,  # start false until you add that adapter
        "exclude_ai_music": True,
    })
    regions: List[str] = field(default_factory=list)
    taste_anchors: List[str] = field(default_factory=list)
    last_confirmed: str = field(default_factory=lambda: datetime.now().date().isoformat())


@dataclass
class CrawlState:
    last_checked: str
    cursor: Optional[str] = None
    status: str = "ok"
    notes: Optional[str] = None


@dataclass
class MemorySnapshot:
    user_profile: UserProfile = field(default_factory=UserProfile)
    conversation_summary: str = (
        "Weekly emerging-artist scouting. DIY/indie focus. Track provenance and avoid repeats."
    )
    crawl_ledger: Dict[str, CrawlState] = field(default_factory=dict)
    artist_registry: Dict[str, Dict] = field(default_factory=dict)  # stored as dict for JSON simplicity