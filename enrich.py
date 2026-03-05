# enrich.py
from __future__ import annotations

import json
from typing import Dict, List

from llm_client import LocalOpenAIClient
from models import CandidateArtist


SYSTEM = (
    "You enrich scraped music candidates.\n"
    "Rules:\n"
    "- Use ONLY the input text provided.\n"
    "- If unsure, use: \"unknown\" or [].\n"
    "- Output VALID JSON ONLY. No markdown. No extra words.\n"
    "- Keep why_match to ONE short sentence.\n"
)


_BAD_WHY_MATCH = {"[]", "{}", "\"[]\"", "\"{}\""}


def _compact_evidence_text(c: CandidateArtist, limit_titles: int = 4) -> str:
    titles = [ev.title for ev in c.evidence if ev.title]
    urls = [ev.url for ev in c.evidence if ev.url]
    titles = titles[:limit_titles]
    urls = urls[:3]
    return (
        f"name: {c.name}\n"
        f"primary_url: {c.primary_url}\n"
        f"notes: {c.notes or ''}\n"
        f"evidence_titles: {titles}\n"
        f"evidence_urls: {urls}\n"
    )


def build_user_prompt(allowed_genres: List[str], c: CandidateArtist) -> str:
    schema = (
        '{\n'
        '  "normalized_name": "string",\n'
        '  "genre_guesses": ["string"],\n'
        '  "why_match": "string",\n'
        '  "confidence": "low|medium|high",\n'
        '  "needs_human_check": true\n'
        '}\n'
    )

    allowed = ", ".join(allowed_genres)
    return (
        f"Allowed genres (pick 0-3 max, must be from this list): [{allowed}]\n"
        f"{_compact_evidence_text(c)}\n"
        f"Return JSON with EXACT keys and types:\n{schema}"
    )


def _coerce_enrichment(data: Dict, allowed_genres: List[str], fallback_name: str) -> Dict:
    allowed_map = {g.lower(): g for g in allowed_genres}

    genre_guesses = []
    for g in (data.get("genre_guesses") or [])[:3]:
        if isinstance(g, str) and g.lower() in allowed_map:
            genre_guesses.append(allowed_map[g.lower()])

    normalized_name = data.get("normalized_name")
    if not isinstance(normalized_name, str) or not normalized_name.strip():
        normalized_name = fallback_name

    why_match = data.get("why_match")
    if not isinstance(why_match, str):
        why_match = "unknown"
    why_match = why_match.strip()

    # sanitize weird outputs small models sometimes produce
    if not why_match or why_match.lower() == "unknown" or why_match in _BAD_WHY_MATCH:
        why_match = "Title-based match only; needs verification."

    # keep it short
    if len(why_match) > 220:
        why_match = why_match[:220].rsplit(" ", 1)[0] + "…"

    confidence = data.get("confidence")
    if confidence not in ("low", "medium", "high"):
        confidence = "low"

    needs_human_check = data.get("needs_human_check")
    if not isinstance(needs_human_check, bool):
        needs_human_check = True

    return {
        "normalized_name": normalized_name,
        "genre_guesses": genre_guesses,
        "why_match": why_match,
        "confidence": confidence,
        "needs_human_check": needs_human_check,
    }


def enrich_candidate(
    client: LocalOpenAIClient,
    allowed_genres: List[str],
    c: CandidateArtist,
) -> Dict:
    prompt = build_user_prompt(allowed_genres, c)
    raw = client.chat(SYSTEM, prompt, temperature=0.15, max_tokens=220)

    # Strict parse first
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return _coerce_enrichment(data, allowed_genres, c.name)
    except Exception:
        pass

    # Salvage first JSON object inside output
    try:
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            snippet = raw[start : end + 1]
            data = json.loads(snippet)
            if isinstance(data, dict):
                return _coerce_enrichment(data, allowed_genres, c.name)
    except Exception:
        pass

    return {
        "normalized_name": c.name,
        "genre_guesses": [],
        "why_match": "Title-based match only; needs verification.",
        "confidence": "low",
        "needs_human_check": True,
    }