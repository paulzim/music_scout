# scout.py
from __future__ import annotations

import argparse
import os
from datetime import datetime
from typing import List

from enrich import enrich_candidate
from llm_client import LocalOpenAIClient
from memory_store import load_memory, save_memory
from models import CandidateArtist, MemorySnapshot
from ranker import score_candidates
from shortlist import write_shortlist
from sources import RedditJSONSource


DEFAULT_MEMORY_PATH = "memory.json"
DEFAULT_OUTPUT_PATH = "output/shortlist.md"


def dedupe_new_candidates(snap: MemorySnapshot, candidates: List[CandidateArtist]) -> List[CandidateArtist]:
    existing = set(snap.artist_registry.keys())
    new: List[CandidateArtist] = []
    for c in candidates:
        if c.canonical_id in existing:
            # For v1 simplicity, we don't update last_seen here.
            # You can add that later (it’s a good enhancement).
            continue
        new.append(c)
    return new


def persist_candidates(
    snap: MemorySnapshot,
    candidates: List[CandidateArtist],
    enriched_map: dict | None = None,
) -> None:
    today = datetime.now().date().isoformat()
    enriched_map = enriched_map or {}

    for c in candidates:
        enrich = enriched_map.get(c.canonical_id, {})

        snap.artist_registry[c.canonical_id] = {
            "name": enrich.get("normalized_name", c.name),
            "primary_url": c.primary_url,
            "first_seen": today,
            "last_seen": today,
            "genres_detected": c.genres_detected,
            "evidence": [ev.__dict__ for ev in c.evidence],
            "status": "candidate",
            "notes": c.notes,
            "llm_enrichment": enrich,
        }


def update_ledger(snap: MemorySnapshot, source_id: str, cursor: str | None, status: str = "ok", notes: str | None = None):
    snap.crawl_ledger[source_id] = {
        "last_checked": datetime.now().isoformat(),
        "cursor": cursor,
        "status": status,
        "notes": notes,
    }


def build_sources() -> List:
    # Safe-ish starting point: Reddit JSON endpoints with a polite user-agent and rate limiting.
    # Add RSS sources later (recommended).
    return [
        RedditJSONSource("reddit:darkwave", "darkwave"),
        RedditJSONSource("reddit:postpunk", "postpunk"),
        RedditJSONSource("reddit:shoegaze", "shoegaze"),
    ]


def enrich_candidates_with_llm(
    snap: MemorySnapshot,
    new_candidates: List[CandidateArtist],
) -> dict:
    """
    Enrich candidates using a local OpenAI-compatible server (LM Studio).
    Stores structured enrichment + copies genre guesses and a short rationale into the candidate fields.
    """
    # Defaults tuned for LM Studio and your model name
    llm_base_url = os.getenv("LLM_BASE_URL", "http://localhost:1234/v1")
    llm_model = os.getenv("LLM_MODEL", "google_gemma-3-1b-it")
    llm_api_key = os.getenv("LLM_API_KEY", "lm-studio")

    client = LocalOpenAIClient(base_url=llm_base_url, api_key=llm_api_key, model=llm_model)

    enriched_map: dict = {}

    # Clamp to avoid runaway time if sources return a ton of posts
    for c in new_candidates[:40]:
        enrich = enrich_candidate(client, snap.user_profile.genres, c)
        enriched_map[c.canonical_id] = enrich

        # Copy back into candidate so ranking + shortlist uses it
        c.genres_detected = enrich.get("genre_guesses", []) or []
        why = enrich.get("why_match", "unknown")
        conf = enrich.get("confidence", "low")
        c.notes = (c.notes or "").strip()
        suffix = f"LLM: {why} (conf: {conf})"
        c.notes = f"{c.notes} | {suffix}" if c.notes else suffix

    return enriched_map


def run(genres: List[str], memory_path: str, output_path: str, top_n: int):
    snap = load_memory(memory_path)

    # Set/refresh genres for this run
    if genres:
        snap.user_profile.genres = genres
        snap.user_profile.last_confirmed = datetime.now().date().isoformat()

    all_candidates: List[CandidateArtist] = []

    for src in build_sources():
        source_id = src.source_id
        cursor = None
        ledger_entry = snap.crawl_ledger.get(source_id)
        if isinstance(ledger_entry, dict):
            cursor = ledger_entry.get("cursor")

        try:
            res = src.fetch(snap.user_profile.genres, cursor)
            update_ledger(snap, source_id, res.cursor, status="ok")
            all_candidates.extend(res.candidates)
        except Exception as e:
            update_ledger(snap, source_id, cursor, status="error", notes=str(e))

    new_candidates = dedupe_new_candidates(snap, all_candidates)

    # LLM enrichment (local)
    enriched_map = {}
    if new_candidates:
        try:
            enriched_map = enrich_candidates_with_llm(snap, new_candidates)
        except Exception as e:
            # Keep the run working even if LLM is down
            print(f"[warn] LLM enrichment failed: {e}")

    persist_candidates(snap, new_candidates, enriched_map)

    scored = score_candidates(snap.user_profile, new_candidates)
    out = write_shortlist(output_path, scored, top_n=top_n)

    save_memory(memory_path, snap)

    print(f"Candidates fetched: {len(all_candidates)}")
    print(f"New after dedupe:   {len(new_candidates)}")
    print(f"Wrote shortlist:    {out}")
    print(f"Updated memory:     {memory_path}")


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="Run a scouting scan and write shortlist")
    r.add_argument("--genres", nargs="*", default=[], help="Genres for this run")
    r.add_argument("--memory", default=DEFAULT_MEMORY_PATH)
    r.add_argument("--out", default=DEFAULT_OUTPUT_PATH)
    r.add_argument("--top", type=int, default=10)

    args = p.parse_args()

    if args.cmd == "run":
        run(args.genres, args.memory, args.out, args.top)


if __name__ == "__main__":
    main()