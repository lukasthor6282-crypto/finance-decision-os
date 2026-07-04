from __future__ import annotations

import re
from datetime import date, timedelta
from sqlite3 import Connection
from typing import Any

from .analytics import money
from .categorizer import categorize
from .db import is_postgres
from .normalization import normalize_text, parse_amount
from .worktime import parse_hourly_rate, parse_work_session_message


SUMMARY_WORDS = (
    "resumo",
    "quanto ganhei",
    "quanto gastei",
    "falta pagar",
    "pendencia",
    "pendencias",
    "faturas abertas",
    "lancamentos",
    "saldo",
)
PAY_WORDS = ("paguei", "pago", "quitei", "abati", "baixei")
PENDING_WORDS = ("para pagar", "a pagar", "pendente", "em aberto", "tenho que pagar")
INCOME_WORDS = ("ganhei", "recebi", "entrou", "salario", "renda", "faturei")
EXPENSE_WORDS = ("gastei", "paguei", "comprei", "saiu")
STOP_WORDS = {
    "hoje",
    "ontem",
    "amanha",
    "paguei",
    "pago",
    "quitei",
    "abati",
    "baixei",
    "gastei",
    "comprei",
    "ganhei",
    "recebi",
    "entrou",
    "tenho",
    "conta",
    "de",
    "do",
    "da",
    "dos",
    "das",
    "no",
    "na",
    "em",
    "com",
    "para",
    "pagar",
    "pendente",
    "reais",
    "real",
    "r",
}


def handle_simple_message(conn: Connection, message: str) -> dict | None:
    original = message.strip()
    normalized = normalize_text(original)
    if not normalized:
        return None

    amounts = extract_amounts(original)

    if _is_work_query(normalized):
        return _work_week_reply(conn)
    hourly_rate = parse_hourly_rate(original)
    parsed_work = parse_work_session_message(original, _known_hourly_rate(conn))
    if parsed_work:
        return _record_work_session(conn, parsed_work)
    if hourly_rate and any(marker in normalized for marker in ("minha hora", "valor da hora", "por hora")):
        _remember_hourly_rate(conn, hourly_rate)
        return {
            "answer": f"Salvei seu valor/hora: {money(hourly_rate)}.",
            "actions": ["valor_hora_salvo"],
            "confidence": 0.9,
            "mode": "simple",
            "intent": "salvar_valor_hora",
            "data": {"hourlyRate": hourly_rate},
        }

    if _is_summary_query(normalized):
        return _summary_reply(conn)
    if "fatura" in normalized and any(word in normalized for word in PAY_WORDS):
        return _pay_invoice(conn, amounts, normalized)
    if "fatura" in normalized and amounts:
        return _record_invoice(conn, original, normalized, amounts)
    if any(word in normalized for word in PAY_WORDS):
        paid = _pay_pending_entry(conn, normalized, amounts)
        if paid:
            return paid
    if amounts and any(word in normalized for word in INCOME_WORDS):
        return _record_income(conn, original, amounts[0])
    if amounts and any(word in normalized for word in PENDING_WORDS):
        return _record_pending_expense(conn, original, normalized, amounts[0])
    if amounts and any(word in normalized for word in EXPENSE_WORDS):
        return _record_paid_expense(conn, original, normalized, amounts[0])

    return None


def simple_summary(conn: Connection, month: str | None = None) -> dict:
    month_key = month or date.today().strftime("%Y-%m")
    entries = _rows(
        conn.execute(
            """
            SELECT id, kind, description, amount, date, status, category, origin, invoice_id, created_at
            FROM simple_entries
            WHERE date LIKE ?
            ORDER BY date DESC, id DESC
            LIMIT 500
            """,
            (f"{month_key}%",),
        ).fetchall()
    )
    pending_entries = _rows(
        conn.execute(
            """
            SELECT id, kind, description, amount, date, status, category, origin, invoice_id, created_at
            FROM simple_entries
            WHERE kind = 'despesa' AND status = 'pendente'
            ORDER BY date ASC, id ASC
            """
        ).fetchall()
    )
    invoices = _list_invoices(conn)

    income = _round(sum(row["amount"] for row in entries if row["kind"] == "receita" and row["status"] == "pago"))
    paid_expenses = _round(
        sum(row["amount"] for row in entries if row["kind"] in {"despesa", "pagamento"} and row["status"] == "pago")
    )
    pending_total = _round(sum(row["amount"] for row in pending_entries))
    invoice_remaining = _round(sum(row["remaining_amount"] for row in invoices if row["status"] != "paga"))
    net = _round(income - paid_expenses)
    after_pending = _round(net - pending_total - invoice_remaining)

    recent = _recent_activity(conn)
    work_week = work_week_summary(conn)
    return {
        "month": month_key,
        "asOf": date.today().isoformat(),
        "totals": {
            "income": income,
            "paidExpenses": paid_expenses,
            "pendingExpenses": pending_total,
            "openInvoices": invoice_remaining,
            "netBalance": net,
            "balanceAfterPending": after_pending,
        },
        "pendingEntries": pending_entries,
        "openInvoices": invoices,
        "recentEntries": recent,
        "workWeek": work_week,
    }


def work_week_summary(conn: Connection, anchor_date: str | None = None) -> dict:
    current = date.fromisoformat(anchor_date) if anchor_date else date.today()
    week_start = current - timedelta(days=current.weekday())
    week_end = week_start + timedelta(days=6)
    archived_weeks = _archive_closed_work_weeks(conn, week_start)
    rows = _rows(
        conn.execute(
            """
            SELECT id, date, start_time, end_time, break_minutes, hourly_rate, hours, gross_amount, description, notes, created_at
            FROM work_sessions
            WHERE date >= ? AND date <= ?
            ORDER BY date ASC, start_time ASC, id ASC
            """,
            (week_start.isoformat(), week_end.isoformat()),
        ).fetchall()
    )
    hours = _round(sum(float(row["hours"]) for row in rows))
    gross = _round(sum(float(row["gross_amount"]) for row in rows))
    days = _work_week_days(week_start, rows)
    return {
        "weekStart": week_start.isoformat(),
        "weekEnd": week_end.isoformat(),
        "weekKey": f"{week_start.isoformat()}:{week_end.isoformat()}",
        "hours": hours,
        "gross": gross,
        "archivedWeeks": archived_weeks,
        "days": days,
        "sessions": rows,
    }


def _archive_closed_work_weeks(conn: Connection, current_week_start: date) -> int:
    rows = _rows(
        conn.execute(
            """
            SELECT date, hours, gross_amount
            FROM work_sessions
            WHERE date < ?
            """,
            (current_week_start.isoformat(),),
        ).fetchall()
    )
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        session_date = date.fromisoformat(row["date"])
        week_start = session_date - timedelta(days=session_date.weekday())
        week_end = week_start + timedelta(days=6)
        key = week_start.isoformat()
        if key not in grouped:
            grouped[key] = {
                "week_start": key,
                "week_end": week_end.isoformat(),
                "hours": 0.0,
                "gross_amount": 0.0,
                "session_count": 0,
            }
        grouped[key]["hours"] = _round(grouped[key]["hours"] + float(row["hours"]))
        grouped[key]["gross_amount"] = _round(grouped[key]["gross_amount"] + float(row["gross_amount"]))
        grouped[key]["session_count"] += 1

    for item in grouped.values():
        conn.execute(
            """
            INSERT INTO work_week_archives (week_start, week_end, hours, gross_amount, session_count, updated_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(week_start) DO UPDATE SET
                week_end = excluded.week_end,
                hours = excluded.hours,
                gross_amount = excluded.gross_amount,
                session_count = excluded.session_count,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                item["week_start"],
                item["week_end"],
                item["hours"],
                item["gross_amount"],
                item["session_count"],
            ),
        )
    return len(grouped)


def _work_week_days(week_start: date, sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    days: list[dict[str, Any]] = []
    for index in range(5):
        current = week_start + timedelta(days=index)
        current_key = current.isoformat()
        day_sessions = [session for session in sessions if session["date"] == current_key]
        hours = _round(sum(float(session["hours"]) for session in day_sessions))
        gross = _round(sum(float(session["gross_amount"]) for session in day_sessions))
        days.append(
            {
                "date": current_key,
                "weekday": ["segunda", "terca", "quarta", "quinta", "sexta"][index],
                "hours": hours,
                "gross": gross,
                "sessions": day_sessions,
                "status": "salvo" if day_sessions else "vazio",
            }
        )
    return days


def _record_invoice(conn: Connection, original: str, normalized: str, amounts: list[float]) -> dict:
    total = _round(amounts[0])
    if total <= 0:
        return _ask("Valor da fatura inválido.")

    item_amounts = [_round(value) for value in amounts[1:] if value > 0]
    items: list[dict[str, Any]] = []
    used = 0.0
    for index, value in enumerate(item_amounts):
        if used + value > total:
            continue
        description = _invoice_item_description(normalized, index)
        items.append({"description": description, "amount": value, "status": "pendente"})
        used = _round(used + value)

    rest = _round(total - used)
    if rest > 0.009 and item_amounts:
        items.append({"description": "compras avulsas", "amount": rest, "status": "pendente"})
    elif not items:
        items.append({"description": "fatura", "amount": total, "status": "pendente"})

    invoice_id = _insert_invoice(conn, "Fatura", total, None)
    for item in items:
        _insert_invoice_item(conn, invoice_id, item["description"], item["amount"])

    parts = ", ".join(f"{money(item['amount'])} como {item['description']}" for item in items)
    return {
        "answer": f"Registrei sua fatura de {money(total)}. Separei {parts}. Falta pagar {money(total)}.",
        "actions": ["fatura_registrada"],
        "confidence": 0.96,
        "mode": "simple",
        "intent": "registrar_fatura",
        "data": {"invoiceId": invoice_id, "total": total, "items": items, "remaining": total, "source": original},
    }


def _pay_invoice(conn: Connection, amounts: list[float], normalized: str) -> dict:
    invoice = _open_invoice(conn)
    if not invoice:
        return _ask("Não achei fatura aberta. Me diga o valor total da fatura primeiro.")

    remaining = float(invoice["remaining_amount"])
    amount = _round(amounts[0]) if amounts else remaining
    if amount <= 0:
        return _ask("Me diga quanto você pagou da fatura.")
    if amount > remaining + 0.009:
        return _ask(f"Esse valor é maior que falta na fatura ({money(remaining)}). Confirma?")

    paid = _round(float(invoice["paid_amount"]) + amount)
    new_remaining = _round(float(invoice["total_amount"]) - paid)
    status = "paga" if new_remaining <= 0.009 else "parcial"
    conn.execute(
        """
        UPDATE simple_invoices
        SET paid_amount = ?, remaining_amount = ?, status = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (paid, max(new_remaining, 0), status, invoice["id"]),
    )
    if status == "paga":
        conn.execute("UPDATE simple_invoice_items SET status = 'pago' WHERE invoice_id = ?", (invoice["id"],))
    _insert_entry(conn, "pagamento", "Pagamento da fatura", amount, _today(), "pago", "Fatura", "chat", invoice["id"])

    if status == "paga":
        answer = f"Abati {money(amount)} da fatura. Fatura paga."
    else:
        answer = f"Abati {money(amount)} da sua fatura. Agora falta pagar {money(new_remaining)}."
    return {
        "answer": answer,
        "actions": ["fatura_atualizada"],
        "confidence": 0.96,
        "mode": "simple",
        "intent": "pagar_fatura_parcial" if status == "parcial" else "pagar_fatura_total",
        "data": {"invoiceId": invoice["id"], "paid": paid, "remaining": max(new_remaining, 0), "status": status},
    }


def _record_income(conn: Connection, original: str, amount: float) -> dict:
    value = _round(amount)
    _insert_entry(conn, "receita", "Receita", value, _today(), "pago", "Receita", "chat")
    return {
        "answer": f"Registrei uma receita de {money(value)} para hoje.",
        "actions": ["receita_registrada"],
        "confidence": 0.94,
        "mode": "simple",
        "intent": "registrar_receita",
        "data": {"amount": value, "source": original},
    }


def _record_paid_expense(conn: Connection, original: str, normalized: str, amount: float) -> dict:
    value = _round(amount)
    description = _description_from_message(original, normalized) or "despesa"
    category = categorize(description, -value).category
    _insert_entry(conn, "despesa", description, value, _today(), "pago", category, "chat")
    return {
        "answer": f"Registrei uma despesa de {money(value)} em {description}.",
        "actions": ["despesa_registrada"],
        "confidence": 0.93,
        "mode": "simple",
        "intent": "registrar_despesa_paga",
        "data": {"amount": value, "description": description, "category": category},
    }


def _record_pending_expense(conn: Connection, original: str, normalized: str, amount: float) -> dict:
    value = _round(amount)
    description = _description_from_message(original, normalized) or "conta"
    category = categorize(description, -value).category
    _insert_entry(conn, "despesa", description, value, _today(), "pendente", category, "chat")
    return {
        "answer": f"Registrei {description} como conta pendente de {money(value)}.",
        "actions": ["pendencia_registrada"],
        "confidence": 0.93,
        "mode": "simple",
        "intent": "registrar_despesa_pendente",
        "data": {"amount": value, "description": description, "category": category, "status": "pendente"},
    }


def _pay_pending_entry(conn: Connection, normalized: str, amounts: list[float]) -> dict | None:
    if "fatura" in normalized:
        return None
    query = _payment_query(normalized)
    amount = _round(amounts[0]) if amounts else None
    matches = _find_pending_entries(conn, query, amount)
    if not matches:
        return None
    if len(matches) > 1:
        names = ", ".join(row["description"] for row in matches[:4])
        return _ask(f"Achei mais de uma pendência: {names}. Qual você pagou?")

    row = matches[0]
    if amount is not None and abs(float(row["amount"]) - amount) > 0.009:
        return _ask(f"{row['description']} está em {money(row['amount'])}. Confirma pagamento de {money(amount)}?")
    conn.execute("UPDATE simple_entries SET status = 'pago', date = ? WHERE id = ?", (_today(), row["id"]))
    return {
        "answer": f"Marquei {row['description']} como paga.",
        "actions": ["pendencia_paga"],
        "confidence": 0.9,
        "mode": "simple",
        "intent": "pagar_despesa",
        "data": {"entryId": row["id"], "description": row["description"], "amount": row["amount"]},
    }


def _summary_reply(conn: Connection) -> dict:
    summary = simple_summary(conn)
    totals = summary["totals"]
    answer = (
        f"Entradas: {money(totals['income'])}. Saídas pagas: {money(totals['paidExpenses'])}. "
        f"Pendências: {money(totals['pendingExpenses'] + totals['openInvoices'])}. "
        f"Saldo líquido: {money(totals['netBalance'])}. "
        f"Depois das pendências: {money(totals['balanceAfterPending'])}."
    )
    return {
        "answer": answer,
        "actions": ["resumo_consultado"],
        "confidence": 0.92,
        "mode": "simple",
        "intent": "consultar_resumo_mes",
        "data": summary,
    }


def _record_work_session(conn: Connection, parsed: Any) -> dict:
    existing = _find_work_session(conn, parsed.date, parsed.start_time, parsed.end_time)
    _remember_hourly_rate(conn, parsed.hourly_rate)
    if existing:
        week = work_week_summary(conn, parsed.date)
        return {
            "answer": f"Essa jornada já estava salva. Total da semana: {_format_hours(week['hours'])} e {money(week['gross'])}.",
            "actions": ["jornada_duplicada"],
            "confidence": 0.86,
            "mode": "simple",
            "intent": "registrar_jornada_trabalho",
            "data": {"duplicated": True, "workWeek": week, "session": dict(existing)},
        }

    returning = " RETURNING id" if is_postgres(conn) else ""
    cursor = conn.execute(
        f"""
        INSERT INTO work_sessions (
            date, start_time, end_time, break_minutes, hourly_rate, hours, gross_amount, description, notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        {returning}
        """,
        (
            parsed.date,
            parsed.start_time,
            parsed.end_time,
            parsed.break_minutes,
            parsed.hourly_rate,
            parsed.hours,
            parsed.gross_amount,
            parsed.description,
            parsed.notes,
        ),
    )
    session_id = int(cursor.fetchone()["id"] if is_postgres(conn) else cursor.lastrowid)
    week = work_week_summary(conn, parsed.date)
    interval = f" ({parsed.start_time}-{parsed.end_time})" if parsed.start_time and parsed.end_time else ""
    return {
        "answer": (
            f"Registrei sua jornada{interval}: {_format_hours(parsed.hours)} x {money(parsed.hourly_rate)}/h = "
            f"{money(parsed.gross_amount)}. Total da semana: {_format_hours(week['hours'])} e {money(week['gross'])}."
        ),
        "actions": ["jornada_registrada"],
        "confidence": 0.94,
        "mode": "simple",
        "intent": "registrar_jornada_trabalho",
        "data": {"sessionId": session_id, "hours": parsed.hours, "gross": parsed.gross_amount, "workWeek": week},
    }


def _work_week_reply(conn: Connection) -> dict:
    week = work_week_summary(conn)
    if not week["sessions"]:
        answer = "Ainda não tenho horas salvas nesta semana."
    else:
        answer = f"Nesta semana você trabalhou {_format_hours(week['hours'])}. Total bruto: {money(week['gross'])}."
    return {
        "answer": answer,
        "actions": ["horas_semana_consultadas"],
        "confidence": 0.91,
        "mode": "simple",
        "intent": "consultar_banco_horas",
        "data": week,
    }


def _find_work_session(conn: Connection, session_date: str, start_time: str | None, end_time: str | None) -> dict | None:
    if start_time and end_time:
        row = conn.execute(
            """
            SELECT id, date, start_time, end_time, break_minutes, hourly_rate, hours, gross_amount, description, notes, created_at
            FROM work_sessions
            WHERE date = ? AND start_time = ? AND end_time = ?
            LIMIT 1
            """,
            (session_date, start_time, end_time),
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT id, date, start_time, end_time, break_minutes, hourly_rate, hours, gross_amount, description, notes, created_at
            FROM work_sessions
            WHERE date = ? AND start_time IS NULL AND end_time IS NULL
            LIMIT 1
            """,
            (session_date,),
        ).fetchone()
    return dict(row) if row else None


def _known_hourly_rate(conn: Connection) -> float | None:
    row = conn.execute(
        """
        SELECT value
        FROM user_facts
        WHERE key IN ('simple:hourly_rate', 'hourly_rate')
        ORDER BY CASE WHEN key = 'simple:hourly_rate' THEN 0 ELSE 1 END
        LIMIT 1
        """
    ).fetchone()
    if not row:
        return None
    try:
        return parse_amount(row["value"])
    except Exception:
        return None


def _remember_hourly_rate(conn: Connection, hourly_rate: float) -> None:
    conn.execute(
        """
        INSERT INTO user_facts (key, value, value_type, confidence, updated_at)
        VALUES ('simple:hourly_rate', ?, 'number', 1, CURRENT_TIMESTAMP)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
        """,
        (f"{hourly_rate:.2f}",),
    )


def extract_amounts(text: str) -> list[float]:
    pattern = re.compile(r"(?:r\$\s*)?[-+]?\d[\d.\s]*(?:,\d{1,2})?\s*(?:r\$|reais|real)?", re.IGNORECASE)
    amounts: list[float] = []
    for match in pattern.finditer(text):
        raw = match.group(0).strip()
        if not raw or (match.start() > 0 and text[match.start() - 1] == ":") or (match.end() < len(text) and text[match.end()] == ":"):
            continue
        clean = re.sub(r"\b(reais|real)\b", "", raw, flags=re.IGNORECASE).replace(" ", "")
        try:
            value = parse_amount(clean)
        except Exception:
            continue
        if value > 0:
            amounts.append(_round(value))
    return amounts


def _insert_entry(
    conn: Connection,
    kind: str,
    description: str,
    amount: float,
    entry_date: str,
    status: str,
    category: str,
    origin: str,
    invoice_id: int | None = None,
) -> int:
    returning = " RETURNING id" if is_postgres(conn) else ""
    cursor = conn.execute(
        f"""
        INSERT INTO simple_entries (kind, description, amount, date, status, category, origin, invoice_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        {returning}
        """,
        (kind, description, amount, entry_date, status, category, origin, invoice_id),
    )
    return int(cursor.fetchone()["id"] if is_postgres(conn) else cursor.lastrowid)


def _insert_invoice(conn: Connection, name: str, total: float, due_date: str | None) -> int:
    returning = " RETURNING id" if is_postgres(conn) else ""
    cursor = conn.execute(
        f"""
        INSERT INTO simple_invoices (name, total_amount, paid_amount, remaining_amount, due_date, status)
        VALUES (?, ?, 0, ?, ?, 'aberta')
        {returning}
        """,
        (name, total, total, due_date),
    )
    return int(cursor.fetchone()["id"] if is_postgres(conn) else cursor.lastrowid)


def _insert_invoice_item(conn: Connection, invoice_id: int, description: str, amount: float) -> int:
    returning = " RETURNING id" if is_postgres(conn) else ""
    cursor = conn.execute(
        f"""
        INSERT INTO simple_invoice_items (invoice_id, description, amount, status)
        VALUES (?, ?, ?, 'pendente')
        {returning}
        """,
        (invoice_id, description, amount),
    )
    return int(cursor.fetchone()["id"] if is_postgres(conn) else cursor.lastrowid)


def _list_invoices(conn: Connection) -> list[dict]:
    invoices = _rows(
        conn.execute(
            """
            SELECT id, name, total_amount, paid_amount, remaining_amount, due_date, status, created_at, updated_at
            FROM simple_invoices
            WHERE status != 'paga'
            ORDER BY created_at DESC, id DESC
            """
        ).fetchall()
    )
    for invoice in invoices:
        invoice["items"] = _rows(
            conn.execute(
                """
                SELECT id, invoice_id, description, amount, status, created_at
                FROM simple_invoice_items
                WHERE invoice_id = ?
                ORDER BY id ASC
                """,
                (invoice["id"],),
            ).fetchall()
        )
    return invoices


def _open_invoice(conn: Connection) -> dict | None:
    row = conn.execute(
        """
        SELECT id, name, total_amount, paid_amount, remaining_amount, due_date, status, created_at, updated_at
        FROM simple_invoices
        WHERE status != 'paga'
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """
    ).fetchone()
    return dict(row) if row else None


def _find_pending_entries(conn: Connection, query: str, amount: float | None) -> list[dict]:
    rows = _rows(
        conn.execute(
            """
            SELECT id, kind, description, amount, date, status, category, origin, invoice_id, created_at
            FROM simple_entries
            WHERE kind = 'despesa' AND status = 'pendente'
            ORDER BY date ASC, id ASC
            """
        ).fetchall()
    )
    if query:
        rows = [row for row in rows if query in normalize_text(row["description"]) or normalize_text(row["description"]) in query]
    if amount is not None:
        amount_matches = [row for row in rows if abs(float(row["amount"]) - amount) < 0.009]
        if amount_matches:
            return amount_matches
    return rows


def _recent_activity(conn: Connection) -> list[dict]:
    entries = _rows(
        conn.execute(
            """
            SELECT id, kind, description, amount, date, status, category, origin, invoice_id, created_at
            FROM simple_entries
            ORDER BY created_at DESC, id DESC
            LIMIT 10
            """
        ).fetchall()
    )
    invoices = _rows(
        conn.execute(
            """
            SELECT id, name, total_amount, paid_amount, remaining_amount, due_date, status, created_at
            FROM simple_invoices
            ORDER BY created_at DESC, id DESC
            LIMIT 5
            """
        ).fetchall()
    )
    combined: list[dict] = entries + [
        {
            "id": row["id"],
            "kind": "fatura",
            "description": row["name"],
            "amount": row["total_amount"],
            "date": str(row["created_at"])[:10],
            "status": row["status"],
            "category": "Fatura",
            "origin": "chat",
            "invoice_id": row["id"],
            "created_at": row["created_at"],
        }
        for row in invoices
    ]
    return sorted(combined, key=lambda row: str(row.get("created_at", "")), reverse=True)[:10]


def _description_from_message(original: str, normalized: str) -> str:
    lower = original.lower()
    match = re.search(r"(?:no|na|em|com|de|do|da)\s+(.+?)(?:\s+para\s+pagar|\s+a\s+pagar|$)", lower)
    if match:
        candidate = match.group(1)
    else:
        candidate = re.sub(r"(?:r\$\s*)?\d[\d.\s]*(?:,\d{1,2})?\s*(?:r\$|reais|real)?", " ", lower, flags=re.I)
    return _clean_description(candidate)


def _payment_query(normalized: str) -> str:
    tokens = [token for token in normalized.split() if token not in STOP_WORDS and not token.isdigit()]
    return " ".join(tokens).strip()


def _clean_description(value: str) -> str:
    value = re.sub(r"(?:r\$\s*)?\d[\d.\s]*(?:,\d{1,2})?\s*(?:r\$|reais|real)?", " ", value, flags=re.I)
    normalized = normalize_text(value)
    tokens = [token for token in normalized.split() if token not in STOP_WORDS and not token.isdigit()]
    return " ".join(tokens).strip()[:80]


def _invoice_item_description(normalized: str, index: int) -> str:
    if "celular" in normalized:
        return "parcela do celular"
    if "parcela" in normalized:
        return "parcela"
    return f"item {index + 1} da fatura"


def _is_summary_query(normalized: str) -> bool:
    return any(word in normalized for word in SUMMARY_WORDS) and not any(word in normalized for word in PAY_WORDS)


def _is_work_query(normalized: str) -> bool:
    return any(
        marker in normalized
        for marker in (
            "quanto trabalhei",
            "horas da semana",
            "total da semana",
            "banco de horas",
            "minhas horas",
        )
    )


def _ask(text: str) -> dict:
    return {
        "answer": text,
        "actions": ["precisa_confirmacao"],
        "confidence": 0.68,
        "mode": "simple",
        "intent": "pedir_confirmacao",
        "data": {},
    }


def _rows(rows: list[Any]) -> list[dict]:
    return [dict(row) for row in rows]


def _round(value: float) -> float:
    return round(float(value), 2)


def _today() -> str:
    return date.today().isoformat()


def _format_hours(value: float) -> str:
    hours = int(value)
    minutes = int(round((float(value) - hours) * 60))
    if minutes == 60:
        hours += 1
        minutes = 0
    if minutes == 0:
        return f"{hours}h"
    return f"{hours}h{minutes:02d}"
