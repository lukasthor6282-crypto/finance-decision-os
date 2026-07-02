from __future__ import annotations

from dataclasses import dataclass
from sqlite3 import Connection, IntegrityError

from .classifier import classify
from .db import is_postgres
from .normalization import merchant_from_description, normalize_text, transaction_fingerprint


@dataclass(frozen=True)
class InsertResult:
    id: int | None
    category: str
    duplicated: bool = False


def insert_transaction(conn: Connection, tx: dict, source: str = "manual") -> InsertResult:
    amount = float(tx["amount"])
    category = tx.get("category") or classify(tx["description"], amount).category
    account = tx.get("account") or "Principal"
    merchant = merchant_from_description(tx["description"])
    normalized = normalize_text(tx["description"])
    fingerprint = transaction_fingerprint(tx["date"], tx["description"], amount, account)

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
