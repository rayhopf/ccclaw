import sqlite3
import os
import threading

_local = threading.local()


def _get_conn(db_path):
    if not hasattr(_local, "conn") or _local.conn is None:
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        _local.conn = sqlite3.connect(db_path)
        _local.conn.row_factory = sqlite3.Row
    return _local.conn


def init_db(db_path):
    conn = _get_conn(db_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
            direction TEXT NOT NULL,
            chat_id INTEGER NOT NULL,
            username TEXT,
            content TEXT NOT NULL,
            file_path TEXT
        );
        CREATE TABLE IF NOT EXISTS inbox_counter (
            prefix TEXT PRIMARY KEY,
            next_id INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS outbox_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filepath TEXT UNIQUE NOT NULL,
            created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
            sent_at TEXT,
            content TEXT
        );
        CREATE TABLE IF NOT EXISTS pane_snapshots (
            session TEXT PRIMARY KEY,
            content TEXT,
            timestamp TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
        );
    """)
    conn.commit()


def store_message(db_path, direction, chat_id, username, content, file_path=None):
    conn = _get_conn(db_path)
    conn.execute(
        "INSERT INTO messages (direction, chat_id, username, content, file_path) VALUES (?,?,?,?,?)",
        (direction, chat_id, username, content, file_path),
    )
    conn.commit()


def get_next_inbox_id(db_path, prefix):
    conn = _get_conn(db_path)
    conn.execute(
        "INSERT OR IGNORE INTO inbox_counter (prefix, next_id) VALUES (?, 1)", (prefix,)
    )
    row = conn.execute(
        "SELECT next_id FROM inbox_counter WHERE prefix = ?", (prefix,)
    ).fetchone()
    next_id = row["next_id"]
    conn.execute(
        "UPDATE inbox_counter SET next_id = ? WHERE prefix = ?", (next_id + 1, prefix)
    )
    conn.commit()
    return next_id


def get_processed_outbox_files(db_path):
    conn = _get_conn(db_path)
    rows = conn.execute("SELECT filepath FROM outbox_messages").fetchall()
    return {row["filepath"] for row in rows}


def record_outbox_message(db_path, filepath, content):
    conn = _get_conn(db_path)
    conn.execute(
        "INSERT OR IGNORE INTO outbox_messages (filepath, sent_at, content) VALUES (?, strftime('%Y-%m-%dT%H:%M:%SZ','now'), ?)",
        (filepath, content),
    )
    conn.commit()


def get_pane_snapshot(db_path, session):
    conn = _get_conn(db_path)
    row = conn.execute(
        "SELECT content FROM pane_snapshots WHERE session = ?", (session,)
    ).fetchone()
    return row["content"] if row else None


def set_pane_snapshot(db_path, session, content):
    conn = _get_conn(db_path)
    conn.execute(
        "INSERT OR REPLACE INTO pane_snapshots (session, content, timestamp) VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%SZ','now'))",
        (session, content),
    )
    conn.commit()
