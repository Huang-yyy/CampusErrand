"""Shared SQLite helpers for CampusErrand."""

import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), "campus_errand.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    student_id  TEXT NOT NULL UNIQUE,
    balance     REAL NOT NULL DEFAULT 100.0,   -- virtual escrow balance
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS errands (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    title         TEXT NOT NULL,
    description   TEXT NOT NULL,
    category      TEXT NOT NULL DEFAULT 'parcel',  -- parcel | meal | print | shopping
    size          TEXT NOT NULL DEFAULT 'medium',  -- small | medium | large(物件大中小)
    pickup        TEXT NOT NULL,           -- where to collect (e.g. Hengqin courier point)
    delivery      TEXT NOT NULL DEFAULT 'Dormitory',  -- fixed: dorm / Qingtian Hui
    bounty        REAL NOT NULL,
    status        TEXT NOT NULL DEFAULT 'pending',  -- pending审核 | open | accepted | delivered | rejected | cancelled
    requester_id  INTEGER NOT NULL REFERENCES users(id),
    runner_id     INTEGER REFERENCES users(id),
    pickup_code   TEXT,                    -- revealed to runner only after accept
    -- 内容申报 + 平台审核(审核详情:仅发布方与平台可见)
    content       TEXT,                    -- 发布方申报的包裹内容(仅发布方/平台可见)
    audit_status  TEXT NOT NULL DEFAULT 'pending',  -- pending审核 | approved | rejected
    audit_note    TEXT,                    -- 平台审核备注(拒绝原因等,仅发布方/平台可见)
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    accepted_at   TEXT,
    delivered_at  TEXT,
    audited_at    TEXT
);

-- 迁移:为已存在的旧库补充新列(幂等)
"""


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _migrate(conn):
    """Add columns for the content-declaration + review flow to already-created DBs (idempotent)."""
    cols = {
        "status": "ADD COLUMN status TEXT NOT NULL DEFAULT 'pending'",
        "size": "ADD COLUMN size TEXT NOT NULL DEFAULT 'medium'",
        "content": "ADD COLUMN content TEXT",
        "audit_status": "ADD COLUMN audit_status TEXT NOT NULL DEFAULT 'pending'",
        "audit_note": "ADD COLUMN audit_note TEXT",
        "audited_at": "ADD COLUMN audited_at TEXT",
    }
    existing = {r["name"] for r in conn.execute("PRAGMA table_info(errands)").fetchall()}
    for name, ddl in cols.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE errands {ddl}")
    conn.commit()


def init_db():
    conn = get_conn()
    try:
        conn.executescript(SCHEMA)
        _migrate(conn)
        conn.commit()
    finally:
        conn.close()
