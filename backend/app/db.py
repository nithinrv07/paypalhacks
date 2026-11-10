"""SQLite storage. Tables follow the concept doc (users, events, policies,
weather_readings, payments) so a payout can always be explained later."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY, name TEXT, email TEXT, paypal_email TEXT
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id), name TEXT, venue TEXT,
    lat REAL, lon REAL, start_time TEXT, end_time TEXT
);
CREATE TABLE IF NOT EXISTS policies (
    id INTEGER PRIMARY KEY, event_id INTEGER REFERENCES events(id),
    threshold_mm REAL, payout_amount REAL, premium REAL, probability REAL,
    status TEXT,                 -- QUOTED / ACTIVE / TRIGGERED / PAID / EXPIRED / FLAGGED
    quote_json TEXT, decision_json TEXT, summary TEXT,
    demo INTEGER DEFAULT 0, demo_scenario TEXT DEFAULT 'rain', replay_started_at TEXT,
    created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS weather_readings (
    id INTEGER PRIMARY KEY, policy_id INTEGER REFERENCES policies(id),
    source TEXT, timestamp TEXT, rain_mm REAL
);
CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY, policy_id INTEGER REFERENCES policies(id),
    type TEXT,                   -- PREMIUM / PAYOUT / REFUND
    paypal_id TEXT, amount REAL, currency TEXT, status TEXT, raw TEXT, created_at TEXT
);
"""


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@contextmanager
def conn():
    c = sqlite3.connect(config.DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init():
    with conn() as c:
        c.executescript(SCHEMA)
        cols = [r["name"] for r in c.execute("PRAGMA table_info(policies)")]
        if "demo_scenario" not in cols:  # databases created before the dry scenario existed
            c.execute("ALTER TABLE policies ADD COLUMN demo_scenario TEXT DEFAULT 'rain'")


def one(sql: str, *args) -> dict | None:
    with conn() as c:
        r = c.execute(sql, args).fetchone()
        return dict(r) if r else None


def all_(sql: str, *args) -> list[dict]:
    with conn() as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]


def run(sql: str, *args) -> int:
    with conn() as c:
        return c.execute(sql, args).lastrowid


def set_status(policy_id: int, status: str, **fields):
    cols = ", ".join(f"{k} = ?" for k in fields)
    sql = f"UPDATE policies SET status = ?, updated_at = ?{', ' + cols if cols else ''} WHERE id = ?"
    run(sql, status, now(), *fields.values(), policy_id)
