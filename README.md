# music_scout

A lightweight “New Artist Scout” agent that scans a few web sources for emerging artists in your favorite genres, writes a weekly shortlist, and—most importantly—maintains **agent memory** in a transparent JSON file.

This repo is intentionally simple and demo-friendly:

- **Memory lives outside the LLM** (in `memory.json`)
- The LLM is used for **bounded enrichment** (short rationales + light genre hints), not for scraping or truth
- Every recommendation includes **provenance** (where it was found + when)

---

## What it does

On each run, the scout:

1. Loads `memory.json` (preferences + crawl ledger + artist registry)
2. Fetches new posts from configured sources
3. Filters to posts that link to real music platforms (YouTube, Bandcamp, SoundCloud, etc.)
4. Extracts a candidate artist name from the title (heuristic)
5. **Dedupes** by canonical URL and:
   - If **new**: stores the candidate and optional LLM enrichment
   - If **already seen**: appends evidence, increments `seen_count`, updates `last_seen`
6. Writes a shortlist to `output/shortlist.md`

---

## File structure

    music_scout/
      scout.py
      sources.py
      memory_store.py
      models.py
      llm_client.py
      enrich.py
      ranker.py
      shortlist.py
      requirements.txt
      memory.json            # generated after first run
      output/
        shortlist.md         # generated each run
      cache/                 # optional (if you add caching later)

---

## Script overview

### `scout.py` — Orchestrator / runner

Main entry point and “agent loop.”

Responsibilities:

- Load/save `memory.json`
- Run each source adapter
- Split candidates into **new** vs **already known**
- Update memory for already-known artists:
  - append evidence
  - update `last_seen`
  - increment `seen_count`
  - append `seen_history` (capped)
- Optionally call the local LLM to enrich *new* candidates
- Rank + write the shortlist markdown

Run it:

    python scout.py run --genres darkwave post-punk shoegaze --top 10

---

### `sources.py` — Source adapters + parsing + link gating

Holds the “connectors” to external sources.

Includes:

- `RedditJSONSource`: pulls `/new.json` for a subreddit (politely rate-limited)
- (Optional) `RSSSource`: easy, safe source type if you add RSS feeds later

Key behavior:

- Normalizes URLs (fixes `&amp;`, relative URLs, drops fragments)
- Filters candidates with a **music link gate** (only keep posts linking to platforms like YouTube/Bandcamp)
- Extracts an artist name from common title patterns (heuristic)

---

### `models.py` — Data models

Defines the core dataclasses used throughout the app:

- `CandidateArtist` and `Evidence` (what the sources return)
- `UserProfile`, `CrawlState`, and `MemorySnapshot` (what’s stored in memory)

---

### `memory_store.py` — Memory persistence (JSON)

Loads and saves the agent’s durable state:

- `user_profile`
- `conversation_summary`
- `crawl_ledger`
- `artist_registry`

This is the “agent memory” module. It keeps the system transparent and easy to debug.

---

### `llm_client.py` — Local LLM connector (LM Studio / OpenAI-compatible)

A tiny HTTP client for OpenAI-compatible endpoints (LM Studio server).

Default assumptions:

- Base URL: `http://localhost:1234/v1`
- Model: `google_gemma-3-1b-it`

Used by `enrich.py` / `scout.py`.

---

### `enrich.py` — LLM enrichment (bounded + safe)

Uses the local LLM to produce small, structured enrichment for candidates:

- normalized name
- 0–3 genre guesses (clamped to allowed list)
- one-sentence `why_match`
- confidence + human-check flag

Important notes:

- The LLM is **not** allowed to invent facts.
- Output is validated and sanitized (small-model-friendly).

---

### `ranker.py` — Scoring / ranking

A simple heuristic scoring function for ordering candidates for the shortlist.

This is intentionally basic in v1. Easy future upgrades:

- add recency boosts
- add per-source weighting
- add embedding similarity for “taste anchors”

---

### `shortlist.py` — Markdown output writer

Generates `output/shortlist.md` in a clean format:

- ranked candidates
- primary link
- notes (including the LLM blurb, if present)
- provenance (“Found at” evidence list)

---

## Configuration

### Environment variables (optional)

If you’re using LM Studio (OpenAI-compatible server):

PowerShell (Windows):

    $env:LLM_BASE_URL="http://localhost:1234/v1"
    $env:LLM_MODEL="google_gemma-3-1b-it"
    $env:LLM_API_KEY="lm-studio"

Defaults should work if LM Studio is running on `localhost:1234`.

---

## Quickstart

Step 1. Create and activate a virtual environment

    python -m venv .venv

Windows PowerShell

    .venv\Scripts\Activate.ps1

macOS or Linux

    source .venv/bin/activate

Step 2. Install dependencies

    pip install -r requirements.txt

Step 3. Start your local LLM in LM Studio

Load the model named `google_gemma-3-1b-it`.

Start the OpenAI-compatible server. The default is commonly `http://localhost:1234/v1`.

Optional environment variables in Windows PowerShell

    $env:LLM_BASE_URL="http://localhost:1234/v1"
    $env:LLM_MODEL="google_gemma-3-1b-it"
    $env:LLM_API_KEY="lm-studio"

Step 4. Run the scout

    python scout.py run --genres darkwave post-punk shoegaze --top 10

Output files

    output/shortlist.md
    memory.json

---

## How memory works

This project treats agent memory as durable state outside the LLM, stored in `memory.json`. The LLM helps with short, bounded enrichment, but the JSON file is the source of truth for continuity.

Memory file sections

`user_profile`  
Stores stable preferences and constraints such as genres, filters, anchors, and `last_confirmed`. This guides enrichment prompts and ranking.

`crawl_ledger`  
Stores per-source run tracking such as `last_checked`, status, and optional cursors. This prevents the agent from losing track of where it left off.

`artist_registry`  
Stores the long-term record of discovered artists and candidates. Each entry keeps provenance and momentum signals.

What changes on each run

New artists are added with `seen_count` set to 1.

If an existing artist is encountered again, the record is updated by setting `last_seen` to today, incrementing `seen_count`, appending a small entry in `seen_history`, and merging new provenance into `evidence` with duplicates removed.

That is the core demo. The scout is not just generating a list. It is building a reliable, inspectable memory of what it has seen over time.

---

## Notes on scraping & ethics

This project is for learning and demos. Be respectful:

- Use rate limits (built in for Reddit)
- Prefer APIs or RSS feeds where possible
- Don’t hammer sites or bypass restrictions

---

## Roadmap ideas

If you want to extend it:

- Add RSS sources for blogs/labels/curators
- Add YouTube Data API adapter (official + clean provenance)
- Add a `trending` command (e.g., `seen_count >= 3`)
- Move registry/ledger to Postgres for multi-user / concurrency
- Add caching + backoff (Redis or filesystem cache)
- Add vector similarity for “sounds like” matching
