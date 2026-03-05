from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import datetime
from typing import Any, Dict

from models import CrawlState, MemorySnapshot, UserProfile


def _safe_load_json(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_memory(path: str) -> MemorySnapshot:
    raw = _safe_load_json(path)
    snap = MemorySnapshot()

    if "user_profile" in raw:
        up = raw["user_profile"]
        snap.user_profile = UserProfile(
            genres=up.get("genres", []),
            constraints=up.get("constraints", snap.user_profile.constraints),
            regions=up.get("regions", []),
            taste_anchors=up.get("taste_anchors", []),
            last_confirmed=up.get("last_confirmed", snap.user_profile.last_confirmed),
        )

    snap.conversation_summary = raw.get("conversation_summary", snap.conversation_summary)

    ledger = raw.get("crawl_ledger", {})
    for source_id, st in ledger.items():
        snap.crawl_ledger[source_id] = CrawlState(
            last_checked=st.get("last_checked", datetime.now().isoformat()),
            cursor=st.get("cursor"),
            status=st.get("status", "ok"),
            notes=st.get("notes"),
        )

    snap.artist_registry = raw.get("artist_registry", {})
    return snap


def save_memory(path: str, snap: MemorySnapshot) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    # Convert dataclasses to plain dicts, keeping registry already as dict
    payload = asdict(snap)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)