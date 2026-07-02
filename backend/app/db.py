from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from .normalization import merchant_from_description, normalize_text, transaction_fingerprint


BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = Path(os.getenv("FINANCE_DB_PATH", DATA_DIR / "finance.db"))


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                description TEXT NOT NULL,
                amount REAL NOT NULL,
                category TEXT NOT NULL,
                account TEXT NOT NULL DEFAULT 'Principal',
                source TEXT NOT NULL DEFAULT 'manual',
                notes TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS budgets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL UNIQUE,
                monthly_limit REAL NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS goals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                target_amount REAL NOT NULL,
                current_amount REAL NOT NULL DEFAULT 0,
                due_date TEXT,
                priority TEXT NOT NULL DEFAULT 'média',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        migrate_db(conn)


def migrate_db(conn: sqlite3.Connection) -> None:
    ensure_column(conn, "transactions", "merchant", "TEXT")
    ensure_column(conn, "transactions", "normalized_description", "TEXT")
    ensure_column(conn, "transactions", "fingerprint", "TEXT")
    ensure_column(conn, "transactions", "is_recurring", "INTEGER NOT NULL DEFAULT 0")
    backfill_transactions(conn)
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_transactions_fingerprint ON transactions(fingerprint)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions(date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_transactions_category ON transactions(category)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_transactions_account ON transactions(account)")


def ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def backfill_transactions(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT id, date, description, amount, account
        FROM transactions
        WHERE fingerprint IS NULL OR merchant IS NULL OR normalized_description IS NULL
        """
    ).fetchall()
    for row in rows:
        merchant = merchant_from_description(row["description"])
        normalized = normalize_text(row["description"])
        fingerprint = transaction_fingerprint(row["date"], row["description"], row["amount"], row["account"])
        conn.execute(
            """
            UPDATE transactions
            SET merchant = ?, normalized_description = ?, fingerprint = ?
            WHERE id = ?
            """,
            (merchant, normalized, fingerprint, row["id"]),
        )
