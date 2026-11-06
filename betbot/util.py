"""Βοηθητικά: HTTP με επαναλήψεις, κανονικοποίηση ονομάτων ομάδων, ημερομηνίες."""
from __future__ import annotations

import difflib
import logging
import re
import time
import unicodedata
from datetime import datetime, timezone

import requests

log = logging.getLogger("betbot")

UA = {"User-Agent": "Mozilla/5.0 (BetBot personal stats; +https://github.com)"}


def http_get(url, params=None, headers=None, timeout=25, retries=3, expect="json"):
    """GET με εκθετική αναμονή σε 429/5xx. Επιστρέφει (data, response)."""
    last = None
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers={**UA, **(headers or {})}, timeout=timeout)
            if r.status_code in (429, 500, 502, 503, 504):
                last = f"HTTP {r.status_code}"
                time.sleep(2 ** attempt * 2)
                continue
            r.raise_for_status()
            return (r.json() if expect == "json" else r.text), r
        except (requests.RequestException, ValueError) as e:
            last = str(e)
            time.sleep(2 ** attempt)
    raise RuntimeError(f"Αποτυχία GET {url}: {last}")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s: str) -> datetime:
    s = s.replace("Z", "+00:00")
    if len(s) == 16:  # 2026-10-27T18:00
        s += ":00+00:00"
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ---------- ονόματα ομάδων ----------
_STRIP = re.compile(r"\b(fc|cf|afc|sc|ac|as|ss|ssc|us|cd|ud|rc|rcd|sv|vfb|vfl|tsg|bc|bk|fk|sk|kv|pae|gs|ae|nps|aps|apo)\b")


def norm_team(name: str, aliases: dict | None = None) -> str:
    """'Olympiakos F.C.' -> 'olympiacos' (με alias). Χωρίς τόνους/σημεία στίξης."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = s.replace("&", " ").replace(".", " ").replace("-", " ")
    s = re.sub(r"[^a-z0-9' ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if aliases and s in aliases:
        return aliases[s]
    s2 = re.sub(r"\s+", " ", _STRIP.sub(" ", s)).strip() or s
    if aliases and s2 in aliases:
        return aliases[s2]
    return s2


def name_similarity(a: str, b: str) -> float:
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.9
    ta, tb = set(a.split()), set(b.split())
    jacc = len(ta & tb) / max(1, len(ta | tb))
    return max(difflib.SequenceMatcher(None, a, b).ratio(), jacc)


def match_fixture(home: str, away: str, candidates: list[dict], aliases: dict, threshold=0.62):
    """Βρίσκει ποιος αγώνας (από candidates με keys home/away) αντιστοιχεί στο ζευγάρι."""
    h, a = norm_team(home, aliases), norm_team(away, aliases)
    best, best_score = None, 0.0
    for c in candidates:
        ch, ca = norm_team(c["home"], aliases), norm_team(c["away"], aliases)
        score = (name_similarity(h, ch) + name_similarity(a, ca)) / 2
        if score > best_score:
            best, best_score = c, score
    return (best, best_score) if best_score >= threshold else (None, best_score)
