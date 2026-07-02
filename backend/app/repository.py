from __future__ import annotations

import time
from dataclasses import dataclass
from sqlite3 import Connection, IntegrityError

from .classifier import classify
from .db import is_postgres
from .normalization import merchant_from_description, normalize_text, transaction_fingerprint
from .worktime import ParsedWorkSession


@dataclass(frozen=True)
class InsertResult:
    id: int | None
    category: str
    duplicated: bool = False


@dataclass(frozen=True)
class WorkSessionResult:
    id: int | None
    transaction_id: int | None
    duplicated: bool = False


def insert_transaction(conn: Connection, tx: dict, source: str = "manual") -> InsertResult:
    amount = float(tx["amount"])
    category = tx.get("category") or learned_category(conn, tx["description"], amount) or classify(tx["description"], amount).category
    account = tx.get("account") or "Principal"
    merchant = merchant_from_description(tx["description"])
    normalized = normalize_text(tx["description"])
    fingerprint = transaction_fingerprint(tx["date"], tx["description"], amount, account)
    if source == "agent":
        fingerprint = f"{fingerprint}:agent:{time.time_ns()}"

    if source != "agent":
        row = conn.execute("SELECT id, category FROM transactions WHERE fingerprint = ?", (fingerprint,)).fetchone()
        if row:
            return InsertResult(row["id"], row["category"], True)

    try:
        returning = " RETURNING id" if is_postgres(conn) else ""
        cursor = conn.execute(
            f"""
            INSERT INTO transactions (
                date, description, amount, category, account, source, notes,
                merchant, normalized_description, fingerprint
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            {returning}
            """,
            (
                tx["date"],
                tx["description"],
                amount,
                category,
                account,
                source,
                tx.get("notes"),
                merchant,
                normalized,
                fingerprint,
            ),
        )
        inserted_id = cursor.fetchone()["id"] if is_postgres(conn) else cursor.lastrowid
        remember_pattern(conn, tx["description"], category, amount)
        return InsertResult(inserted_id, category, False)
    except IntegrityError:
        row = conn.execute("SELECT id, category FROM transactions WHERE fingerprint = ?", (fingerprint,)).fetchone()
        return InsertResult(row["id"] if row else None, row["category"] if row else category, True)


def list_budgets(conn: Connection) -> list[dict]:
    rows = conn.execute("SELECT id, category, monthly_limit, created_at FROM budgets ORDER BY category").fetchall()
    return [dict(row) for row in rows]


def list_goals(conn: Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT id, name, target_amount, current_amount, due_date, priority, created_at
        FROM goals
        ORDER BY
          CASE priority
            WHEN 'alta' THEN 1
            WHEN 'media' THEN 2
            WHEN 'média' THEN 2
            ELSE 3
          END,
          due_date
        """
    ).fetchall()
    return [dict(row) for row in rows]


def learned_category(conn: Connection, description: str, amount: float) -> str | None:
    normalized = normalize_text(description)
    if not normalized:
        return None
    direction = "income" if amount > 0 else "expense"
    rows = conn.execute(
        """
        SELECT pattern, category
        FROM learned_patterns
        WHERE direction = ?
        ORDER BY usage_count DESC, LENGTH(pattern) DESC
        LIMIT 50
        """,
        (direction,),
    ).fetchall()
    for row in rows:
        pattern = row["pattern"]
        if pattern and (pattern in normalized or normalized in pattern):
            return row["category"]
    return None


def remember_pattern(conn: Connection, description: str, category: str, amount: float) -> None:
    pattern = normalize_text(description)
    if len(pattern) < 3:
        return
    direction = "income" if amount > 0 else "expense"
    conn.execute(
        """
        INSERT INTO learned_patterns (pattern, category, direction, usage_count, last_amount, last_seen)
        VALUES (?, ?, ?, 1, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(pattern) DO UPDATE SET
            category = excluded.category,
            direction = excluded.direction,
            usage_count = learned_patterns.usage_count + 1,
            last_amount = excluded.last_amount,
            last_seen = CURRENT_TIMESTAMP
        """,
        (pattern, category, direction, abs(amount)),
    )


def list_learned_patterns(conn: Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT pattern, category, direction, usage_count, last_amount, last_seen, created_at
        FROM learned_patterns
        ORDER BY usage_count DESC, last_seen DESC
        LIMIT 100
        """
    ).fetchall()
    return [dict(row) for row in rows]


def set_fact(conn: Connection, key: str, value: str, value_type: str = "text", confidence: float = 1) -> None:
    conn.execute(
        """
        INSERT INTO user_facts (key, value, value_type, confidence, updated_at)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            value_type = excluded.value_type,
            confidence = excluded.confidence,
            updated_at = CURRENT_TIMESTAMP
        """,
        (key, value, value_type, confidence),
    )


def get_fact(conn: Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM user_facts WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def get_float_fact(conn: Connection, key: str) -> float | None:
    value = get_fact(conn, key)
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def list_facts(conn: Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT key, value, value_type, confidence, updated_at, created_at
        FROM user_facts
        ORDER BY updated_at DESC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def existing_work_session(conn: Connection, session: ParsedWorkSession) -> dict | None:
    if not session.start_time or not session.end_time:
        return None
    row = conn.execute(
        """
        SELECT id, transaction_id
        FROM work_sessions
        WHERE date = ? AND start_time = ? AND end_time = ?
        """,
        (session.date, session.start_time, session.end_time),
    ).fetchone()
    return dict(row) if row else None


def insert_work_session(conn: Connection, session: ParsedWorkSession, transaction_id: int | None) -> WorkSessionResult:
    existing = existing_work_session(conn, session)
    if existing:
        return WorkSessionResult(existing["id"], existing["transaction_id"], True)

    returning = " RETURNING id" if is_postgres(conn) else ""
    cursor = conn.execute(
        f"""
        INSERT INTO work_sessions (
            date, start_time, end_time, break_minutes, hourly_rate, hours,
            gross_amount, description, notes, transaction_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        {returning}
        """,
        (
            session.date,
            session.start_time,
            session.end_time,
            session.break_minutes,
            session.hourly_rate,
            session.hours,
            session.gross_amount,
            session.description,
            session.notes,
            transaction_id,
        ),
    )
    session_id = cursor.fetchone()["id"] if is_postgres(conn) else cursor.lastrowid
    return WorkSessionResult(session_id, transaction_id, False)


def list_work_sessions(conn: Connection, limit: int = 100) -> list[dict]:
    rows = conn.execute(
        """
        SELECT id, date, start_time, end_time, break_minutes, hourly_rate, hours,
               gross_amount, description, notes, transaction_id, created_at
        FROM work_sessions
        ORDER BY date DESC, id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]
