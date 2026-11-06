"""SQLite αποθήκη: αγώνες, αποδόσεις (+ιστορικό κινήσεων), στατιστικά ομάδων/παικτών,
ενδεκάδες/απουσίες, δελτία.

Όλοι οι collectors γράφουν εδώ στην ίδια μορφή, ώστε τα μοντέλα να μη χρειάζεται
να ξέρουν από ποια πηγή ήρθε κάθε δεδομένο.

Αν αλλάξεις το SCHEMA: οι νέοι πίνακες δημιουργούνται αυτόματα (CREATE IF NOT EXISTS).
Για νέες ΣΤΗΛΕΣ σε υπάρχοντα πίνακα, πρόσθεσέ τες στο MIGRATIONS παρακάτω.
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, asdict, field
from typing import Iterable, Optional

NULL_LINE = -999.0   # το PRIMARY KEY δεν δουλεύει σωστά με NULL -> βάζουμε -999

SCHEMA = """
CREATE TABLE IF NOT EXISTS matches (
    match_id   TEXT PRIMARY KEY,       -- '<πηγή>:<id πηγής>'
    sport      TEXT NOT NULL,          -- football | basketball
    league     TEXT NOT NULL,          -- id από config (EPL, NBA, ...)
    kickoff    TEXT NOT NULL,          -- ISO UTC
    home       TEXT NOT NULL,
    away       TEXT NOT NULL,
    home_score INTEGER,
    away_score INTEGER,
    status     TEXT NOT NULL,          -- scheduled | live | finished | postponed
    source     TEXT NOT NULL,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_matches_league_date ON matches(league, kickoff);

-- Τρέχουσα απόδοση ανά (αγώνας, αγορά, επιλογή, γραμμή, πηγή) + η πρώτη που είδαμε (open_price)
CREATE TABLE IF NOT EXISTS odds (
    match_id   TEXT NOT NULL,
    market     TEXT NOT NULL,          -- 1X2 DC OU BTTS | CORNERS CARDS THROWINS | ML TOTAL SPREAD | PLAYER
    selection  TEXT NOT NULL,          -- 1 X 2 1X X2 12 OVER UNDER YES NO HOME AWAY
    line       REAL NOT NULL,          -- 2.5, 9.5, 221.5, -4.5 ... ή -999 όταν δεν υπάρχει
    price      REAL NOT NULL,          -- δεκαδική απόδοση
    open_price REAL,                   -- αρχική απόδοση (από την πηγή ή η πρώτη που είδαμε)
    n_books    INTEGER DEFAULT 1,
    source     TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    first_seen TEXT,
    PRIMARY KEY (match_id, market, selection, line, source)
);

-- Κάθε λήψη αποδόσεων γράφεται εδώ -> βλέπουμε την πορεία (κινήσεις αγοράς)
CREATE TABLE IF NOT EXISTS odds_history (
    match_id   TEXT NOT NULL,
    market     TEXT NOT NULL,
    selection  TEXT NOT NULL,
    line       REAL NOT NULL,
    price      REAL NOT NULL,
    source     TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_oh_match ON odds_history(match_id);

-- Στατιστικά ομάδας ανά αγώνα (κόρνερ, κάρτες, πλάγια, σουτ, φάουλ)
CREATE TABLE IF NOT EXISTS team_stats (
    event_key  TEXT NOT NULL,          -- '<πηγή>:<id αγώνα στην πηγή>'
    match_id   TEXT,                   -- αντιστοίχιση στο matches (αν βρέθηκε)
    league     TEXT NOT NULL,
    kickoff    TEXT NOT NULL,
    team       TEXT NOT NULL,          -- όνομα όπως το δίνει η πηγή
    opponent   TEXT NOT NULL,
    is_home    INTEGER NOT NULL,
    goals      INTEGER,
    corners    INTEGER,
    yellow     INTEGER,
    red        INTEGER,
    fouls      INTEGER,
    shots      INTEGER,
    sot        INTEGER,                -- σουτ στην εστία
    throw_ins  INTEGER,                -- πλάγια άουτ
    possession REAL,
    referee    TEXT,
    source     TEXT NOT NULL,
    PRIMARY KEY (event_key, is_home)
);
CREATE INDEX IF NOT EXISTS ix_ts_team ON team_stats(team, kickoff);

-- Στατιστικά παίκτη ανά αγώνα
CREATE TABLE IF NOT EXISTS player_stats (
    event_key  TEXT NOT NULL,
    kickoff    TEXT NOT NULL,
    league     TEXT NOT NULL,
    team       TEXT NOT NULL,
    player     TEXT NOT NULL,
    starter    INTEGER,
    minutes    INTEGER,
    shots      INTEGER,
    sot        INTEGER,
    fouls      INTEGER,
    yellow     INTEGER,
    goals      INTEGER,
    source     TEXT NOT NULL,
    PRIMARY KEY (event_key, team, player)
);
CREATE INDEX IF NOT EXISTS ix_ps_player ON player_stats(player, kickoff);

-- Ενδεκάδες & απουσίες για επερχόμενους αγώνες
CREATE TABLE IF NOT EXISTS lineups (
    match_id   TEXT NOT NULL,
    team       TEXT NOT NULL,
    player     TEXT NOT NULL,
    status     TEXT NOT NULL,          -- starter | sub | missing | doubtful
    position   TEXT,                   -- G D M F
    reason     TEXT,                   -- τραυματισμός, τιμωρία ...
    confirmed  INTEGER DEFAULT 0,      -- 1 = επίσημη ενδεκάδα
    source     TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (match_id, team, player)
);

-- Διαιτητής επερχόμενου αγώνα
CREATE TABLE IF NOT EXISTS referees (
    match_id   TEXT PRIMARY KEY,
    referee    TEXT NOT NULL,
    source     TEXT NOT NULL
);

-- Αντιστοίχιση αγώνα με id σε άλλες πηγές (π.χ. sofascore)
CREATE TABLE IF NOT EXISTS ext_ids (
    match_id   TEXT NOT NULL,
    source     TEXT NOT NULL,
    ext_id     TEXT NOT NULL,
    PRIMARY KEY (match_id, source)
);

-- Τι έχει ήδη κατέβει (για να μην ξανακατεβάζουμε ίδια στατιστικά)
CREATE TABLE IF NOT EXISTS fetch_cache (
    key        TEXT PRIMARY KEY,
    fetched_at TEXT NOT NULL,
    ok         INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS slips (
    slip_id     TEXT PRIMARY KEY,      -- YYYY-MM-DD#<λίστα>
    created_at  TEXT NOT NULL,
    list_name   TEXT,                  -- recommended | safe | x10 | x30 | x100 | overs | ...
    total_odds  REAL NOT NULL,
    model_prob  REAL NOT NULL,
    stake       REAL NOT NULL,
    status      TEXT NOT NULL,         -- open | won | lost | void
    payout      REAL DEFAULT 0,
    legs_json   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    run_at   TEXT NOT NULL,
    step     TEXT NOT NULL,
    ok       INTEGER NOT NULL,
    message  TEXT
);
"""

# (πίνακας, στήλη, τύπος) – για βάσεις που φτιάχτηκαν με παλιότερη έκδοση
MIGRATIONS = [
    ("odds", "open_price", "REAL"),
    ("odds", "first_seen", "TEXT"),
    ("slips", "list_name", "TEXT"),
]


@dataclass
class Match:
    match_id: str
    sport: str
    league: str
    kickoff: str
    home: str
    away: str
    home_score: Optional[int]
    away_score: Optional[int]
    status: str
    source: str


@dataclass
class OddsRow:
    match_id: str
    market: str
    selection: str
    line: Optional[float]
    price: float
    n_books: int
    source: str
    fetched_at: str
    open_price: Optional[float] = None


@dataclass
class TeamStat:
    event_key: str
    match_id: Optional[str]
    league: str
    kickoff: str
    team: str
    opponent: str
    is_home: int
    goals: Optional[int] = None
    corners: Optional[int] = None
    yellow: Optional[int] = None
    red: Optional[int] = None
    fouls: Optional[int] = None
    shots: Optional[int] = None
    sot: Optional[int] = None
    throw_ins: Optional[int] = None
    possession: Optional[float] = None
    referee: Optional[str] = None
    source: str = ""


@dataclass
class PlayerStat:
    event_key: str
    kickoff: str
    league: str
    team: str
    player: str
    starter: Optional[int] = None
    minutes: Optional[int] = None
    shots: Optional[int] = None
    sot: Optional[int] = None
    fouls: Optional[int] = None
    yellow: Optional[int] = None
    goals: Optional[int] = None
    source: str = ""


@dataclass
class LineupRow:
    match_id: str
    team: str
    player: str
    status: str
    position: Optional[str] = None
    reason: Optional[str] = None
    confirmed: int = 0
    source: str = ""
    fetched_at: str = ""


class DB:
    def __init__(self, path: str):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._migrate()

    def _migrate(self):
        for table, col, typ in MIGRATIONS:
            cols = {r["name"] for r in self.conn.execute(f"PRAGMA table_info({table})")}
            if col not in cols:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
        self.conn.commit()

    @contextmanager
    def tx(self):
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    # ---------- matches ----------
    def upsert_matches(self, matches: Iterable[Match]) -> int:
        rows = [asdict(m) for m in matches]
        if not rows:
            return 0
        with self.tx() as c:
            c.executemany(
                """INSERT INTO matches(match_id,sport,league,kickoff,home,away,home_score,away_score,status,source)
                   VALUES(:match_id,:sport,:league,:kickoff,:home,:away,:home_score,:away_score,:status,:source)
                   ON CONFLICT(match_id) DO UPDATE SET
                     kickoff=excluded.kickoff, home_score=excluded.home_score,
                     away_score=excluded.away_score, status=excluded.status,
                     updated_at=CURRENT_TIMESTAMP""",
                rows,
            )
        return len(rows)

    def matches(self, sport=None, league=None, status=None, since=None, until=None):
        q, p = "SELECT * FROM matches WHERE 1=1", []
        for col, val, op in (("sport", sport, "="), ("league", league, "="), ("status", status, "="),
                             ("kickoff", since, ">="), ("kickoff", until, "<")):
            if val is not None:
                q += f" AND {col} {op} ?"
                p.append(val)
        return [dict(r) for r in self.conn.execute(q + " ORDER BY kickoff", p)]

    def get_match(self, match_id: str):
        r = self.conn.execute("SELECT * FROM matches WHERE match_id=?", (match_id,)).fetchone()
        return dict(r) if r else None

    # ---------- odds ----------
    def upsert_odds(self, rows: Iterable[OddsRow]) -> int:
        rows = [asdict(r) for r in rows]
        if not rows:
            return 0
        for r in rows:
            if r["line"] is None:
                r["line"] = NULL_LINE
            r["first_seen"] = r["fetched_at"]
        with self.tx() as c:
            # open_price: κρατάμε την πρώτη (ή αυτή που δίνει η πηγή), δεν την αντικαθιστούμε
            c.executemany(
                """INSERT INTO odds(match_id,market,selection,line,price,open_price,n_books,source,fetched_at,first_seen)
                   VALUES(:match_id,:market,:selection,:line,:price,COALESCE(:open_price,:price),:n_books,:source,:fetched_at,:first_seen)
                   ON CONFLICT(match_id,market,selection,line,source) DO UPDATE SET
                     price=excluded.price, n_books=excluded.n_books, fetched_at=excluded.fetched_at,
                     open_price=COALESCE(odds.open_price, excluded.open_price)""",
                rows,
            )
            c.executemany(
                """INSERT INTO odds_history(match_id,market,selection,line,price,source,fetched_at)
                   VALUES(:match_id,:market,:selection,:line,:price,:source,:fetched_at)""",
                rows,
            )
        return len(rows)

    def odds_for(self, match_id: str):
        out = []
        for r in self.conn.execute("SELECT * FROM odds WHERE match_id=?", (match_id,)):
            d = dict(r)
            if d["line"] == NULL_LINE:
                d["line"] = None
            out.append(d)
        return out

    def odds_history_for(self, match_id: str):
        out = []
        for r in self.conn.execute("SELECT * FROM odds_history WHERE match_id=? ORDER BY fetched_at", (match_id,)):
            d = dict(r)
            if d["line"] == NULL_LINE:
                d["line"] = None
            out.append(d)
        return out

    # ---------- stats ----------
    def upsert_team_stats(self, rows: Iterable[TeamStat]) -> int:
        rows = [asdict(r) for r in rows]
        if not rows:
            return 0
        cols = list(rows[0].keys())
        with self.tx() as c:
            c.executemany(
                f"INSERT OR REPLACE INTO team_stats({','.join(cols)}) VALUES({','.join(':' + k for k in cols)})", rows)
        return len(rows)

    def upsert_player_stats(self, rows: Iterable[PlayerStat]) -> int:
        rows = [asdict(r) for r in rows]
        if not rows:
            return 0
        cols = list(rows[0].keys())
        with self.tx() as c:
            c.executemany(
                f"INSERT OR REPLACE INTO player_stats({','.join(cols)}) VALUES({','.join(':' + k for k in cols)})", rows)
        return len(rows)

    def team_stats(self, since=None, league=None):
        q, p = "SELECT * FROM team_stats WHERE 1=1", []
        if since:
            q += " AND kickoff >= ?"; p.append(since)
        if league:
            q += " AND league = ?"; p.append(league)
        return [dict(r) for r in self.conn.execute(q + " ORDER BY kickoff", p)]

    def team_stats_for_match(self, match_id):
        return [dict(r) for r in self.conn.execute("SELECT * FROM team_stats WHERE match_id=?", (match_id,))]

    def player_stats(self, since=None):
        q, p = "SELECT * FROM player_stats", []
        if since:
            q += " WHERE kickoff >= ?"; p.append(since)
        return [dict(r) for r in self.conn.execute(q + " ORDER BY kickoff", p)]

    def player_stats_for_event(self, match_id):
        """Στατιστικά παικτών για αγώνα του matches (μέσω team_stats.event_key)."""
        keys = [r["event_key"] for r in self.conn.execute(
            "SELECT DISTINCT event_key FROM team_stats WHERE match_id=?", (match_id,))]
        if not keys:
            return []
        q = f"SELECT * FROM player_stats WHERE event_key IN ({','.join('?' * len(keys))})"
        return [dict(r) for r in self.conn.execute(q, keys)]

    # ---------- lineups / referees / ext ids ----------
    def upsert_lineups(self, rows: Iterable[LineupRow]) -> int:
        rows = [asdict(r) for r in rows]
        if not rows:
            return 0
        with self.tx() as c:
            # αν ήρθε νέα πληροφορία για τον αγώνα, σβήνουμε την παλιά της ίδιας πηγής
            for mid in {r["match_id"] for r in rows}:
                c.execute("DELETE FROM lineups WHERE match_id=? AND source=?", (mid, rows[0]["source"]))
            cols = list(rows[0].keys())
            c.executemany(
                f"INSERT OR REPLACE INTO lineups({','.join(cols)}) VALUES({','.join(':' + k for k in cols)})", rows)
        return len(rows)

    def lineups_for(self, match_id):
        return [dict(r) for r in self.conn.execute("SELECT * FROM lineups WHERE match_id=?", (match_id,))]

    def set_referee(self, match_id, referee, source):
        with self.tx() as c:
            c.execute("INSERT OR REPLACE INTO referees VALUES(?,?,?)", (match_id, referee, source))

    def referee_for(self, match_id):
        r = self.conn.execute("SELECT referee FROM referees WHERE match_id=?", (match_id,)).fetchone()
        return r["referee"] if r else None

    def set_ext_id(self, match_id, source, ext_id):
        with self.tx() as c:
            c.execute("INSERT OR REPLACE INTO ext_ids VALUES(?,?,?)", (match_id, source, str(ext_id)))

    def ext_id(self, match_id, source):
        r = self.conn.execute("SELECT ext_id FROM ext_ids WHERE match_id=? AND source=?", (match_id, source)).fetchone()
        return r["ext_id"] if r else None

    # ---------- cache ----------
    def cached(self, key) -> bool:
        r = self.conn.execute("SELECT ok FROM fetch_cache WHERE key=?", (key,)).fetchone()
        return bool(r and r["ok"])

    def mark_cached(self, key, at, ok=True):
        with self.tx() as c:
            c.execute("INSERT OR REPLACE INTO fetch_cache VALUES(?,?,?)", (key, at, int(ok)))

    # ---------- slips ----------
    def save_slip(self, slip_id, created_at, list_name, total_odds, model_prob, stake, legs, keep_first=False):
        """keep_first=True: αν υπάρχει ήδη δελτίο με αυτό το id (π.χ. από την πρωινή εκτέλεση), ΔΕΝ αντικαθίσταται –
        ώστε αυτό που πρότεινε το bot το πρωί να μένει το ίδιο όλη μέρα."""
        with self.tx() as c:
            c.execute(
                f"""INSERT OR {'IGNORE' if keep_first else 'REPLACE'} INTO slips(slip_id,created_at,list_name,total_odds,model_prob,stake,status,payout,legs_json)
                   VALUES(?,?,?,?,?,?,'open',0,?)""",
                (slip_id, created_at, list_name, total_odds, model_prob, stake, json.dumps(legs, ensure_ascii=False)),
            )

    def slips(self, status=None):
        q = "SELECT * FROM slips" + (" WHERE status=?" if status else "") + " ORDER BY created_at"
        rows = self.conn.execute(q, (status,) if status else ())
        return [dict(r) | {"legs": json.loads(r["legs_json"])} for r in rows]

    def update_slip(self, slip_id, status, payout, legs):
        with self.tx() as c:
            c.execute("UPDATE slips SET status=?, payout=?, legs_json=? WHERE slip_id=?",
                      (status, payout, json.dumps(legs, ensure_ascii=False), slip_id))

    # ---------- συντήρηση ----------
    def prune(self, odds_history_days=45, runs_days=90):
        """Σβήνει παλιό ιστορικό αποδόσεων/logs για να μη μεγαλώνει η βάση (το repo έχει όριο 100MB/αρχείο)."""
        from datetime import datetime, timedelta, timezone
        cut = (datetime.now(timezone.utc) - timedelta(days=odds_history_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        cut2 = (datetime.now(timezone.utc) - timedelta(days=runs_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self.tx() as c:
            c.execute("DELETE FROM odds_history WHERE fetched_at < ?", (cut,))
            c.execute("DELETE FROM runs WHERE run_at < ?", (cut2,))
            c.execute("DELETE FROM lineups WHERE fetched_at < ?", (cut,))
        self.conn.execute("VACUUM")

    # ---------- log ----------
    def log(self, run_at, step, ok, message=""):
        with self.tx() as c:
            c.execute("INSERT INTO runs VALUES(?,?,?,?)", (run_at, step, int(ok), message[:2000]))
