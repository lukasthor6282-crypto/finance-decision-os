from __future__ import annotations

import time
from dataclasses import dataclass
from sqlite3 import Connection, IntegrityError

from .categorizer import INTERNAL_TYPES, Categorization, categorize, editable_rules, infer_signed_type
from .db import is_postgres
from .duplicate_detector import duplicate_group_key, transaction_fingerprint
from .normalization import merchant_from_description, normalize_text
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
    resolved = resolve_category(conn, tx["description"], amount, tx.get("category"), tx.get("transaction_type"), tx.get("is_internal"))
    category = resolved.category
    transaction_type = resolved.transaction_type
    is_internal = int(resolved.is_internal)
    account = tx.get("account") or "Principal"
    merchant = merchant_from_description(tx["description"])
    normalized = normalize_text(tx["description"])
    fingerprint = transaction_fingerprint(tx["date"], tx["description"], amount, account, transaction_type)
    if source == "agent":
        fingerprint = f"{fingerprint}:agent:{time.time_ns()}"
    group_key = duplicate_group_key(tx["date"], tx["description"], amount, account)

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
                merchant, normalized_description, fingerprint, transaction_type, is_internal, duplicate_group, category_locked
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                transaction_type,
                is_internal,
                group_key,
                int(bool(tx.get("category_locked", False))),
            ),
        )
        inserted_id = cursor.fetchone()["id"] if is_postgres(conn) else cursor.lastrowid
        remember_pattern(conn, tx["description"], category, amount)
        return InsertResult(inserted_id, category, False)
    except IntegrityError:
        row = conn.execute("SELECT id, category FROM transactions WHERE fingerprint = ?", (fingerprint,)).fetchone()
        return InsertResult(row["id"] if row else None, row["category"] if row else category, True)


def resolve_category(
    conn: Connection,
    description: str,
    amount: float,
    explicit_category: str | None = None,
    explicit_type: str | None = None,
    explicit_internal: bool | None = None,
) -> Categorization:
    categorized = categorize(description, amount)
    custom = custom_category(conn, description, amount)
    learned = learned_category(conn, description, amount)
    category = explicit_category or (custom.category if custom else None) or (categorized.category if categorized.confidence >= 0.8 else learned) or categorized.category
    transaction_type = explicit_type or (custom.transaction_type if custom else None) or categorized.transaction_type
    is_internal = (transaction_type in INTERNAL_TYPES) if explicit_internal is None else bool(explicit_internal)
    return Categorization(
        category=category,
        transaction_type=transaction_type,
        confidence=1.0 if explicit_category else custom.confidence if custom else categorized.confidence,
        reason="manual" if explicit_category else custom.reason if custom else categorized.reason,
        is_internal=is_internal,
    )


def custom_category(conn: Connection, description: str, amount: float) -> Categorization | None:
    normalized = normalize_text(description)
    rows = conn.execute(
        """
        SELECT pattern, category, transaction_type, is_internal
        FROM category_rules
        ORDER BY priority DESC, LENGTH(pattern) DESC, id DESC
        """
    ).fetchall()
    for row in rows:
        pattern = normalize_text(row["pattern"])
        if not pattern or pattern not in normalized:
            continue
        tx_type = infer_signed_type(row["transaction_type"], amount)
        if tx_type == "income" and amount < 0:
            continue
        if tx_type == "expense" and amount > 0:
            continue
        return Categorization(
            category=row["category"],
            transaction_type=tx_type,
            confidence=0.99,
            reason=f"custom:{pattern}",
            is_internal=bool(row["is_internal"]) or tx_type in INTERNAL_TYPES,
        )
    return None


def update_transaction_category(
    conn: Connection,
    transaction_id: int,
    category: str | None = None,
    transaction_type: str | None = None,
    is_internal: bool | None = None,
) -> dict | None:
    row = conn.execute(
        """
        SELECT id, date, description, amount, category, transaction_type, is_internal
        FROM transactions
        WHERE id = ?
        """,
        (transaction_id,),
    ).fetchone()
    if not row:
        return None
    tx_type = transaction_type or row["transaction_type"]
    internal = int((tx_type in INTERNAL_TYPES) if is_internal is None else bool(is_internal))
    next_category = category or row["category"]
    conn.execute(
        """
        UPDATE transactions
        SET category = ?, transaction_type = ?, is_internal = ?, category_locked = 1
        WHERE id = ?
        """,
        (next_category, tx_type, internal, transaction_id),
    )
    return {"id": transaction_id, "category": next_category, "transaction_type": tx_type, "is_internal": bool(internal)}


def reprocess_transactions(conn: Connection, include_locked: bool = False) -> dict:
    where = "" if include_locked else "WHERE category_locked = 0"
    rows = conn.execute(
        f"""
        SELECT id, description, amount
        FROM transactions
        {where}
        """
    ).fetchall()
    updated = 0
    for row in rows:
        resolved = resolve_category(conn, row["description"], float(row["amount"]))
        conn.execute(
            """
            UPDATE transactions
            SET category = ?, transaction_type = ?, is_internal = ?
            WHERE id = ?
            """,
            (resolved.category, resolved.transaction_type, int(resolved.is_internal), row["id"]),
        )
        updated += 1
    return {"ok": True, "updated": updated, "preservedManual": not include_locked}


def list_category_rules(conn: Connection) -> list[dict]:
    custom_rows = conn.execute(
        """
        SELECT id, pattern, category, transaction_type, is_internal, priority, created_at
        FROM category_rules
        ORDER BY priority DESC, created_at DESC
        """
    ).fetchall()
    custom = [
        {
            **dict(row),
            "source": "custom",
            "patterns": [row["pattern"]],
        }
        for row in custom_rows
    ]
    system = [
        {
            "id": None,
            "pattern": ", ".join(rule["patterns"][:3]),
            "category": rule["category"],
            "transaction_type": rule["transactionType"],
            "is_internal": rule["transactionType"] in INTERNAL_TYPES,
            "priority": 0,
            "created_at": None,
            "source": "system",
            "patterns": rule["patterns"],
        }
        for rule in editable_rules()
    ]
    return custom + system


def create_category_rule(conn: Connection, rule: dict) -> dict:
    pattern = normalize_text(rule["pattern"])
    if len(pattern) < 2:
        raise ValueError("pattern too short")
    transaction_type = rule.get("transaction_type") or "expense"
    is_internal = int(bool(rule.get("is_internal")) or transaction_type in INTERNAL_TYPES)
    returning = " RETURNING id" if is_postgres(conn) else ""
    cursor = conn.execute(
        f"""
        INSERT INTO category_rules (pattern, category, transaction_type, is_internal, priority)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(pattern) DO UPDATE SET
            category = excluded.category,
            transaction_type = excluded.transaction_type,
            is_internal = excluded.is_internal,
            priority = excluded.priority
        {returning}
        """,
        (pattern, rule["category"].strip(), transaction_type, is_internal, int(rule.get("priority", 100))),
    )
    if is_postgres(conn):
        rule_id = cursor.fetchone()["id"]
    else:
        row = conn.execute("SELECT id FROM category_rules WHERE pattern = ?", (pattern,)).fetchone()
        rule_id = row["id"]
    return {"id": rule_id, "pattern": pattern, "category": rule["category"].strip(), "transaction_type": transaction_type, "is_internal": bool(is_internal), "source": "custom"}


def delete_category_rule(conn: Connection, rule_id: int) -> bool:
    cursor = conn.execute("DELETE FROM category_rules WHERE id = ?", (rule_id,))
    return cursor.rowcount > 0


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


def find_work_session_for_correction(conn: Connection, session: ParsedWorkSession) -> dict | None:
    if session.start_time:
        rows = conn.execute(
            """
            SELECT id, transaction_id, date, start_time, end_time, hours, gross_amount
            FROM work_sessions
            WHERE date = ? AND start_time = ?
            ORDER BY id DESC
            """,
            (session.date, session.start_time),
        ).fetchall()
        if rows:
            return correction_group(rows)

    row = conn.execute(
        """
        SELECT id, transaction_id, date, start_time, end_time, hours, gross_amount
        FROM work_sessions
        WHERE date = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (session.date,),
    ).fetchone()
    return dict(row) if row else None


def correction_group(rows) -> dict:
    items = [dict(row) for row in rows]
    keep = items[0]
    keep["duplicate_ids"] = [item["id"] for item in items[1:]]
    keep["duplicate_transaction_ids"] = [item["transaction_id"] for item in items[1:] if item.get("transaction_id")]
    keep["total_hours"] = round(sum(float(item["hours"]) for item in items), 4)
    keep["total_gross_amount"] = round(sum(float(item["gross_amount"]) for item in items), 2)
    keep["duplicate_count"] = len(items) - 1
    return keep


def update_work_session(conn: Connection, session_id: int, session: ParsedWorkSession) -> WorkSessionResult:
    row = conn.execute(
        "SELECT id, transaction_id FROM work_sessions WHERE id = ?",
        (session_id,),
    ).fetchone()
    if not row:
        return WorkSessionResult(None, None, False)

    if session.start_time:
        duplicates = conn.execute(
            """
            SELECT id, transaction_id
            FROM work_sessions
            WHERE date = ? AND start_time = ? AND id <> ?
            """,
            (session.date, session.start_time, session_id),
        ).fetchall()
        for duplicate in duplicates:
            if duplicate["transaction_id"]:
                conn.execute("DELETE FROM transactions WHERE id = ?", (duplicate["transaction_id"],))
            conn.execute("DELETE FROM work_sessions WHERE id = ?", (duplicate["id"],))

    conn.execute(
        """
        UPDATE work_sessions
        SET date = ?,
            start_time = ?,
            end_time = ?,
            break_minutes = ?,
            hourly_rate = ?,
            hours = ?,
            gross_amount = ?,
            description = ?,
            notes = ?
        WHERE id = ?
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
            session_id,
        ),
    )

    transaction_id = row["transaction_id"]
    if transaction_id:
        description = session.description
        account = "Principal"
        fingerprint = transaction_fingerprint(session.date, description, session.gross_amount, account, "income")
        fingerprint = f"{fingerprint}:work_session:{session_id}"
        conn.execute(
            """
            UPDATE transactions
            SET date = ?,
                description = ?,
                amount = ?,
                category = 'Receita',
                account = ?,
                notes = ?,
                merchant = ?,
                normalized_description = ?,
                fingerprint = ?,
                transaction_type = 'income',
                is_internal = 0
            WHERE id = ?
            """,
            (
                session.date,
                description,
                session.gross_amount,
                account,
                session.notes,
                merchant_from_description(description),
                normalize_text(description),
                fingerprint,
                transaction_id,
            ),
        )

    return WorkSessionResult(session_id, transaction_id, False)


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
