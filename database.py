# -*- coding: utf-8 -*-
"""SQLite 数据访问层：监控项、设置、检查日志。"""
import sqlite3
from datetime import datetime

from config import DB_PATH, DEFAULT_SETTINGS, MAX_LOGS_KEPT

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    url           TEXT NOT NULL UNIQUE,
    adapter       TEXT DEFAULT 'auto',
    enabled       INTEGER DEFAULT 1,
    status        TEXT DEFAULT 'unknown',
    status_text   TEXT DEFAULT '',
    last_checked  TEXT,
    last_notified TEXT,
    in_keywords   TEXT DEFAULT '',
    out_keywords  TEXT DEFAULT '',
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS logs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER,
    checked_at TEXT NOT NULL,
    status     TEXT,
    http_code  INTEGER,
    detail     TEXT
);
"""


def _conn():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = _conn()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


# ---------------- settings ----------------
def get_settings():
    conn = _conn()
    try:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    finally:
        conn.close()
    data = dict(DEFAULT_SETTINGS)
    data.update({r["key"]: r["value"] for r in rows})
    return data


def save_settings(items: dict):
    conn = _conn()
    try:
        for k, v in items.items():
            conn.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (k, str(v)),
            )
        conn.commit()
    finally:
        conn.close()


# ---------------- products ----------------
def list_products():
    conn = _conn()
    try:
        rows = conn.execute("SELECT * FROM products ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_product(pid):
    conn = _conn()
    try:
        r = conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()


def get_product_by_url(url):
    conn = _conn()
    try:
        r = conn.execute("SELECT * FROM products WHERE url=?", (url,)).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()


def create_product(name, url, adapter="auto", in_keywords="", out_keywords=""):
    conn = _conn()
    try:
        cur = conn.execute(
            "INSERT INTO products(name, url, adapter, in_keywords, out_keywords, created_at) "
            "VALUES(?, ?, ?, ?, ?, ?)",
            (name, url, adapter, in_keywords, out_keywords, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def update_product(pid, fields: dict):
    allowed = {"name", "adapter", "enabled", "in_keywords", "out_keywords"}
    sets, vals = [], []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k}=?")
            vals.append(v)
    if not sets:
        return
    vals.append(pid)
    conn = _conn()
    try:
        conn.execute(f"UPDATE products SET {', '.join(sets)} WHERE id=?", vals)
        conn.commit()
    finally:
        conn.close()


def update_status(pid, status, status_text, notified=False):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = _conn()
    try:
        if notified:
            conn.execute(
                "UPDATE products SET status=?, status_text=?, last_checked=?, last_notified=? WHERE id=?",
                (status, status_text, now, now, pid),
            )
        else:
            conn.execute(
                "UPDATE products SET status=?, status_text=?, last_checked=? WHERE id=?",
                (status, status_text, now, pid),
            )
        conn.commit()
    finally:
        conn.close()


def delete_product(pid):
    conn = _conn()
    try:
        conn.execute("DELETE FROM logs WHERE product_id=?", (pid,))
        conn.execute("DELETE FROM products WHERE id=?", (pid,))
        conn.commit()
    finally:
        conn.close()


# ---------------- logs ----------------
def add_log(product_id, status, http_code, detail):
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO logs(product_id, checked_at, status, http_code, detail) VALUES(?, ?, ?, ?, ?)",
            (product_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), status, http_code, detail),
        )
        conn.execute(
            "DELETE FROM logs WHERE id NOT IN (SELECT id FROM logs ORDER BY id DESC LIMIT ?)",
            (MAX_LOGS_KEPT,),
        )
        conn.commit()
    finally:
        conn.close()


def list_logs(limit=50, product_id=None):
    try:
        if product_id:
            conn = _conn()
            rows = conn.execute(
                "SELECT * FROM logs WHERE product_id=? ORDER BY id DESC LIMIT ?", (product_id, limit)
            ).fetchall()
        else:
            conn = _conn()
            rows = conn.execute("SELECT * FROM logs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]
