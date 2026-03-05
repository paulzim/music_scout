# scout.py
from __future__ import annotations

import argparse
import os
from datetime import datetime
from typing import List, Tuple

from enrich import enrich_candidate
from llm_client import LocalOpenAIClient
from memory_store import load_memory, save_memory
from models import CandidateArtist, MemorySnapshot
from ranker import score_candidates
from shortlist import write_shortlist
from sources import RedditJSONSource


DEFAULT_MEMORY_PATH = "memory.json"
DEFAULT_OUTPUT_PATH = "output/shortlist.md"


def _today() -> str:
    return datetime.now().date().isoformat()


def _now_iso() -> str:
    return datetime.now().isoformat()


def _merge_evidence(existing_evidence: List[dict], new_evidence: List[dict]) -> List[dict]:
    """
    Merge evidence lists, avoiding duplicates.
    Dedup key: (source_id, url, title)
    """
    def key(ev: dict) -> tuple:
        return (
            (ev.get("source_id") or "").strip(),
            (ev.get("url") or "").strip(),
            (ev.get("title") or "").strip(),
        )

    seen = {key(ev) for ev in (existing_evidence or [])}
    merged = list(existing_evidence or [])

    for ev in (new_evidence or []):
        k = key(ev)
        if k in seen:
            continue
        merged.append(ev)
        seen.add(k)

    # Cap evidence to keep memory size reasonable
    if len(merged) > 30:
        merged = merged[-30:]

    return merged


def _append_seen_history(rec: dict, source_id: str) -> None:
    """
    Append a tiny history item so you can visualize "momentum" over time.
    Capped to last 20 entries.
    """
    hist = rec.get("seen_history")
    if not isinstance(hist, list):
        hist = []

    hist.append({
        "date": _today(),
        "source_id": source_id,
    })

    if len(hist) > 20:
        hist = hist[-20:]

    rec["seen_history"] = hist


def apply_seen_updates(snap: MemorySnapshot, candidates: List[CandidateArtist]) -> Tuple[List[CandidateArtist], int]:
    """
    Splits candidates into:
      - new_candidates: not in registry
      - existing updates: append evidence + update last_seen + increment seen_count
    Returns (new_candidates, updated_existing_count)
    """
    today = _today()
    updated_existing = 0
    new_candidates: List[CandidateArtist] = []

    for c in candidates:
        cid = c.canonical_id
        if cid not in snap.artist_registry:
            new_candidates.append(c)
            continue

        rec = snap.artist_registry.get(cid) or {}

        # Update last_seen
        rec["last_seen"] = today

        # Increment seen_count (initialize if missing)
        prev = rec.get("seen_count")
        if not isinstance(prev, int):
            prev = 1  # treat the existing record as already "seen" once
        rec["seen_count"] = prev + 1

        # Append a tiny history record (use first evidence source_id if available)
        source_id = (c.evidence[0].source_id if c.evidence else "unknown_source")
        _append_seen_history(rec, source_id)

        # Merge evidence
        existing_evidence = rec.get("evidence") or []
        new_evidence = [ev.__dict__ for ev in c.evidence]
        rec["evidence"] = _merge_evidence(existing_evidence, new_evidence)

        # Merge genres_detected (only add new ones; don't overwrite)
        existing_genres = rec.get("genres_detected") or []
        existing_set = {g.lower() for g in existing_genres if isinstance(g, str)}
        for g in (c.genres_detected or []):
            if isinstance(g, str) and g.lower() not in existing_set:
                existing_genres.append(g)
                existing_set.add(g.lower())
        rec["genres_detected"] = existing_genres

        # Keep existing notes; only set if missing
        if not (isinstance(rec.get("notes"), str) and rec["notes"]):
            rec["notes"] = c.notes

        snap.artist_registry[cid] = rec
        updated_existing += 1

    return new_candidates, updated_existing


def persist_candidates(
    snap: MemorySnapshot,
    candidates: List[CandidateArtist],
    enriched_map: dict | None = None,
    skipped_ids: set | None = None,
) -> None:
    """
    Persist NEW candidates only (existing ones are handled in apply_seen_updates).
    Writes seen_count=1 at creation time.
    """
    today = _today()
    enriched_map = enriched_map or {}
    skipped_ids = skipped_ids or set()

    for c in candidates:
        enrich = enriched_map.get(c.canonical_id)

        record = {
            "name": (enrich.get("normalized_name") if isinstance(enrich, dict) else None) or c.name,
            "primary_url": c.primary_url,
            "first_seen": today,
            "last_seen": today,
            "seen_count": 1,
            "seen_history": [{"date": today, "source_id": (c.evidence[0].source_id if c.evidence else "unknown_source")}],
            "genres_detected": c.genres_detected,
            "evidence": [ev.__dict__ for ev in c.evidence],
            "status": "candidate",
            "notes": c.notes,
        }

        if isinstance(enrich, dict) and enrich:
            record["llm_enrichment"] = enrich
        elif c.canonical_id in skipped_ids:
            record["llm_enrichment"] = {"skipped": True, "reason": "budget_clamp"}

        snap.artist_registry[c.canonical_id] = record


def update_ledger(snap: MemorySnapshot, source_id: str, cursor: str | None, status: str = "ok", notes: str | None = None):
    snap.crawl_ledger[source_id] = {
        "last_checked": _now_iso(),
        "cursor": cursor,
        "status": status,
        "notes": notes,
    }


def build_sources() -> List:
    return [
        RedditJSONSource("reddit:darkwave", "darkwave"),
        RedditJSONSource("reddit:postpunk", "postpunk"),
        RedditJSONSource("reddit:shoegaze", "shoegaze"),
    ]


def enrich_candidates_with_llm(
    snap: MemorySnapshot,
    new_candidates: List[CandidateArtist],
    max_enrich: int = 30,
) -> tuple[dict, set]:
    llm_base_url = os.getenv("LLM_BASE_URL", "http://localhost:1234/v1")
    llm_model = os.getenv("LLM_MODEL", "google_gemma-3-1b-it")
    llm_api_key = os.getenv("LLM_API_KEY", "lm-studio")

    client = LocalOpenAIClient(base_url=llm_base_url, api_key=llm_api_key, model=llm_model)

    def _priority(c: CandidateArtist) -> int:
        score = 0
        if c.primary_url:
            score += 2
        if any(ev.title for ev in c.evidence):
            score += 1
        return score

    ordered = sorted(new_candidates, key=_priority, reverse=True)

    enriched_map: dict = {}
    skipped_ids: set = set()

    for i, c in enumerate(ordered):
        if i >= max_enrich:
            skipped_ids.add(c.canonical_id)
            continue

        enrich = enrich_candidate(client, snap.user_profile.genres, c)
        enriched_map[c.canonical_id] = enrich

        # Copy back for ranking/shortlist
        c.genres_detected = enrich.get("genre_guesses", []) or []
        why = enrich.get("why_match", "Title-based match only; needs verification.")
        conf = enrich.get("confidence", "low")

        c.notes = (c.notes or "").strip()
        suffix = f"LLM: {why} (conf: {conf})"
        c.notes = f"{c.notes} | {suffix}" if c.notes else suffix

    return enriched_map, skipped_ids


def run(genres: List[str], memory_path: str, output_path: str, top_n: int):
    snap = load_memory(memory_path)

    if genres:
        snap.user_profile.genres = genres
        snap.user_profile.last_confirmed = _today()

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

    new_candidates, updated_existing_count = apply_seen_updates(snap, all_candidates)

    enriched_map = {}
    skipped_ids: set = set()

    if new_candidates:
        try:
            enriched_map, skipped_ids = enrich_candidates_with_llm(snap, new_candidates, max_enrich=30)
        except Exception as e:
            print(f"[warn] LLM enrichment failed: {e}")

    persist_candidates(snap, new_candidates, enriched_map=enriched_map, skipped_ids=skipped_ids)

    scored = score_candidates(snap.user_profile, new_candidates)
    out = write_shortlist(output_path, scored, top_n=top_n)

    save_memory(memory_path, snap)

    print(f"Candidates fetched: {len(all_candidates)}")
    print(f"New after dedupe:   {len(new_candidates)}")
    print(f"Existing updated:   {updated_existing_count}")
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