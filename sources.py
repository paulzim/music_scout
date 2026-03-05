from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, List, Optional

import feedparser
import requests
from bs4 import BeautifulSoup

from models import CandidateArtist, Evidence


def _canonical_id_from_url(url: str) -> str:
    return f"url|{url.strip()}"


def _canonical_id_from_name(name: str) -> str:
    norm = "".join(ch.lower() for ch in name.strip() if ch.isalnum() or ch.isspace())
    h = hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]
    return f"namehash|{h}"


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
    Safe default: RSS feeds from blogs/labels/curators.
    You provide an RSS URL; we extract candidate artists from titles.
    """
    def __init__(self, source_id: str, rss_url: str):
        self.source_id = source_id
        self.rss_url = rss_url

    def fetch(self, genres: List[str], cursor: Optional[str]) -> SourceResult:
        feed = feedparser.parse(self.rss_url)
        cands: List[CandidateArtist] = []

        # cursor could be "last_seen_published"
        for entry in feed.entries[:50]:
            published = entry.get("published") or entry.get("updated") or ""
            link = entry.get("link") or ""
            title = entry.get("title") or ""

            # naive heuristic: assume "Artist – Track" or "Artist: ..."
            artist_name = title.split("–")[0].split("-")[0].split(":")[0].strip()
            if not artist_name or len(artist_name) < 2:
                continue

            canonical = _canonical_id_from_url(link) if link else _canonical_id_from_name(artist_name)
            primary_url = link if link else ""

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
    Another decent default: subreddit JSON (still respect rate limits).
    Example endpoint:
      https://www.reddit.com/r/darkwave/new.json?limit=50
    """
    def __init__(self, source_id: str, subreddit: str, limiter: RateLimiter | None = None):
        self.source_id = source_id
        self.subreddit = subreddit.strip().lstrip("r/").strip()
        self.limiter = limiter or RateLimiter(1.5)

    def fetch(self, genres: List[str], cursor: Optional[str]) -> SourceResult:
        self.limiter.wait()
        url = f"https://www.reddit.com/r/{self.subreddit}/new.json?limit=50"
        headers = {"User-Agent": "new-artist-scout/0.1 (learning project)"}
        resp = requests.get(url, headers=headers, timeout=20)
        resp.raise_for_status()
        data = resp.json()

        cands: List[CandidateArtist] = []

        for child in data.get("data", {}).get("children", []):
            post = child.get("data", {})
            title = post.get("title") or ""
            permalink = "https://www.reddit.com" + (post.get("permalink") or "")
            outbound = post.get("url") or permalink

            # naive: take first chunk as artist-ish
            artist_name = title.split("–")[0].split("-")[0].split(":")[0].strip()
            if not artist_name or len(artist_name) < 2:
                continue

            canonical = _canonical_id_from_url(outbound) if outbound else _canonical_id_from_name(artist_name)

            ev = Evidence(
                source_id=self.source_id,
                url=permalink,
                date=datetime.now().date().isoformat(),
                title=title[:200],
            )

            cands.append(CandidateArtist(
                name=artist_name,
                canonical_id=canonical,
                primary_url=outbound,
                evidence=[ev],
                notes="From Reddit title heuristic; verify link.",
            ))

        return SourceResult(candidates=cands, cursor=None)