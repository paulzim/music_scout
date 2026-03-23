# sources.py
from __future__ import annotations

import hashlib
import html
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, List, Optional
from urllib.parse import urlparse, urlunparse

import feedparser
import requests

from models import CandidateArtist, Evidence


# Domains we consider "music links" for v1.
# Add/remove to taste.
ALLOWED_MUSIC_DOMAINS = {
    "bandcamp.com",
    "soundcloud.com",
    "youtube.com",
    "youtu.be",
    "open.spotify.com",
    "spotify.com",
    "music.apple.com",
    "audiomack.com",
    "mixcloud.com",
}


# Common Reddit post title noise tags/prefixes
TITLE_PREFIX_PATTERNS = [
    r"^\s*\[.*?\]\s*",      # [FRESH], [PREMIERE], etc.
    r"^\s*\(.*?\)\s*",      # (Official Video), etc.
    r"^\s*premiere\s*:\s*", # PREMIERE:
    r"^\s*exclusive\s*:\s*",# Exclusive:
    r"^\s*new\s*:\s*",      # New:
    r"^\s*video\s*:\s*",    # Video:
]


def _safe_str(value: Any) -> str:
    """
    Coerce loosely-typed feedparser values into a safe string.
    This keeps runtime behavior simple and makes Pylance happy.
    """
    if isinstance(value, str):
        return value
    return ""


def _strip_title_noise(title: str) -> str:
    t = title.strip()
    changed = True
    while changed:
        changed = False
        for pat in TITLE_PREFIX_PATTERNS:
            new = re.sub(pat, "", t, flags=re.IGNORECASE)
            if new != t:
                t = new.strip()
                changed = True
    return t


def _extract_artist_from_title(title: str) -> Optional[str]:
    """
    Heuristic extraction from common patterns:
      Artist – Track
      Artist - Track
      Artist: Track
      Artist | Track
    Falls back to None if it looks like a discussion/request.
    """
    t = _strip_title_noise(title)

    lower = t.lower()
    non_music_markers = [
        "looking for", "help me find", "help identify", "what is this song",
        "anyone know", "recommendations", "discussion", "question", "playlist",
        "tour", "ticket", "gig", "bassist", "drummer", "singer wanted"
    ]
    if any(m in lower for m in non_music_markers):
        return None

    for sep in [" – ", " - ", ": ", " | "]:
        if sep in t:
            left = t.split(sep, 1)[0].strip()
            if 2 <= len(left) <= 80:
                return left

    if 2 <= len(t) <= 40:
        return t

    return None


def _canonical_id_from_url(url: str) -> str:
    return f"url|{url.strip()}"


def _canonical_id_from_name(name: str) -> str:
    norm = "".join(ch.lower() for ch in name.strip() if ch.isalnum() or ch.isspace())
    h = hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]
    return f"namehash|{h}"


def _normalize_url(raw_url: str) -> str:
    """
    Normalize URLs so dedupe is consistent:
    - HTML-unescape (&amp; -> &)
    - Trim whitespace
    - Remove fragments (#...)
    """
    if not raw_url:
        return ""

    u = html.unescape(raw_url.strip())

    if u.startswith("/"):
        u = "https://www.reddit.com" + u

    try:
        p = urlparse(u)
        p = p._replace(fragment="")
        netloc = (p.netloc or "").lower()
        p = p._replace(netloc=netloc)

        if not p.scheme:
            return u

        return urlunparse(p)
    except Exception:
        return u


def _is_allowed_music_link(url: str) -> bool:
    """
    Gate candidates to posts that point to a music platform
    (or a subdomain of one).
    """
    if not url:
        return False
    try:
        p = urlparse(url)
        host = (p.netloc or "").lower()
        for dom in ALLOWED_MUSIC_DOMAINS:
            if host == dom or host.endswith("." + dom):
                return True
        return False
    except Exception:
        return False


@dataclass
class SourceResult:
    candidates: List[CandidateArtist]
    cursor: Optional[str] = None


class RateLimiter:
    def __init__(self, min_seconds: float = 1.0):
        self.min_seconds = min_seconds
        self._last = 0.0

    def wait(self):
        now = time.time()
        delta = now - self._last
        if delta < self.min_seconds:
            time.sleep(self.min_seconds - delta)
        self._last = time.time()


class BaseSource:
    source_id: str

    def fetch(self, genres: List[str], cursor: Optional[str]) -> SourceResult:
        raise NotImplementedError


class RSSSource(BaseSource):
    """
    Safe default: RSS feeds.
    v1 extraction is still title-based; you can add per-feed parsing later.
    """
    def __init__(self, source_id: str, rss_url: str):
        self.source_id = source_id
        self.rss_url = rss_url

    def fetch(self, genres: List[str], cursor: Optional[str]) -> SourceResult:
        feed = feedparser.parse(self.rss_url)
        cands: List[CandidateArtist] = []

        for entry in feed.entries[:50]:
            raw_link = _safe_str(entry.get("link"))
            raw_title = _safe_str(entry.get("title"))

            link = _normalize_url(raw_link)
            title = raw_title.strip()

            if not title:
                continue

            artist_name = _extract_artist_from_title(title)
            if not artist_name:
                continue

            # RSS links can be non-music pages; we don't gate RSS by default.
            canonical = _canonical_id_from_url(link) if link else _canonical_id_from_name(artist_name)
            primary_url = link

            ev = Evidence(
                source_id=self.source_id,
                url=link,
                date=datetime.now().date().isoformat(),
                title=title[:200] if title else None,
            )

            cands.append(CandidateArtist(
                name=artist_name,
                canonical_id=canonical,
                primary_url=primary_url or link or "",
                genres_detected=[],
                evidence=[ev],
                notes="From RSS title heuristic.",
            ))

        return SourceResult(candidates=cands, cursor=None)


class RedditJSONSource(BaseSource):
    """
    Reddit JSON endpoint (be polite and rate-limit).
    We apply a "music link gate" so you mostly get posts that point to actual music.
    """
    def __init__(self, source_id: str, subreddit: str, limiter: RateLimiter | None = None):
        self.source_id = source_id
        self.subreddit = subreddit.strip().lstrip("r/").strip()
        self.limiter = limiter or RateLimiter(1.5)

    def fetch(self, genres: List[str], cursor: Optional[str]) -> SourceResult:
        self.limiter.wait()
        url = f"https://www.reddit.com/r/{self.subreddit}/new.json?limit=50"
        headers = {"User-Agent": "new-artist-scout/0.2 (learning project; respectful rate limits)"}
        resp = requests.get(url, headers=headers, timeout=20)
        resp.raise_for_status()
        data = resp.json()

        cands: List[CandidateArtist] = []
        today = datetime.now().date().isoformat()

        for child in data.get("data", {}).get("children", []):
            post = child.get("data", {})
            title = _safe_str(post.get("title")).strip()
            if not title:
                continue

            permalink = _normalize_url("https://www.reddit.com" + _safe_str(post.get("permalink")))
            outbound = _normalize_url(_safe_str(post.get("url")))

            # Gate: only keep posts with an outbound music-platform link
            # If outbound is just the Reddit permalink (self-post), skip.
            if not _is_allowed_music_link(outbound):
                continue

            artist_name = _extract_artist_from_title(title)
            if not artist_name:
                continue

            canonical = _canonical_id_from_url(outbound) if outbound else _canonical_id_from_name(artist_name)

            ev = Evidence(
                source_id=self.source_id,
                url=permalink,
                date=today,
                title=title[:200],
            )

            cands.append(CandidateArtist(
                name=artist_name,
                canonical_id=canonical,
                primary_url=outbound,
                evidence=[ev],
                notes="From Reddit title heuristic; outbound link gated to music platforms.",
            ))

        return SourceResult(candidates=cands, cursor=None)