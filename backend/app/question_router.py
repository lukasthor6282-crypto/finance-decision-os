from __future__ import annotations

import re
from calendar import monthrange
from datetime import date, timedelta
from sqlite3 import Connection

from .analytics import (
    build_category_spend,
    detect_recurring,
    get_transactions,
    is_real_expense,
    is_real_income,
    money,
    previous_month_key,
    refund_amount,
    summarize,
)
from .normalization import normalize_text
from .repository import get_float_fact
from .strategic_planner import answer_strategic_plan, asks_strategic_plan


MONTHS = {
    "janeiro": "01",
    "fevereiro": "02",
    "marco": "03",
    "abril": "04",
    "maio": "05",
    "junho": "06",
    "julho": "07",
    "agosto": "08",
    "setembro": "09",
    "outubro": "10",
    "novembro": "11",
    "dezembro": "12",
}

CATEGORY_ALIASES = {
    "alimentacao": "Alimentacao",
    "comida": "Alimentacao",
    "restaurante": "Alimentacao",
    "padaria": "Alimentacao",
    "ifood": "Alimentacao",
    "mercado": "Supermercado",
    "supermercado": "Supermercado",
    "transporte": "Transporte",
    "uber": "Transporte",
    "assinatura": "Assinaturas",
    "assinaturas": "Assinaturas",
    "saude": "Saude",
    "educacao": "Educacao",
    "moradia": "Moradia",
    "aluguel": "Moradia",
    "investimento": "Investimentos",
    "investimentos": "Investimentos",
    "receita": "Receita",
    "renda": "Receita",
}


def answer_question(conn: Connection, message: str) -> dict | None:
    text = normalize_text(message)
    period_data = infer_period(text)
    month_key = period_data["month"]

    if asks_strategic_plan(message):
        return answer_strategic_plan(conn, message)

    if asks_hourly_rate_question(text):
        return hourly_rate_answer(conn)

    if asks_work_total(text):
        return work_total_answer(conn, period_data)

    transactions = get_transactions(conn, 2000)
    if not transactions:
        return reply(
            "no_data",
            "Ainda nao ha dados suficientes. Registre receitas/despesas ou importe um extrato primeiro.",
            [],
            0.95,
            {"period": period_data},
        )

    category = infer_category(text)
    period_transactions = filter_period(transactions, period_data)

    if asks_balance(text):
        summary = summarize(conn, month_key)
        kpis = summary["kpis"]
        return reply(
            "balance",
            f"Saldo atual: {money(kpis['balance'])}. No mes {month_key}: receitas {money(kpis['income'])}, despesas {money(kpis['expenses'])}, liquido {money(kpis['net'])}.",
            ["Veja despesas reais, sem transferencias e fatura duplicada."],
            0.93,
            {"month": month_key, "kpis": kpis},
        )

    if asks_income_total(text):
        return income_answer(period_transactions, period_data)

    if asks_category_trend(text, category):
        return category_trend_answer(transactions, month_key, category)

    if asks_category_spend(text, category):
        return category_spend_answer(period_transactions, period_data, category)

    if asks_total_spend(text):
        total = expense_total(period_transactions)
        return reply(
            "total_expense",
            f"{period_data['label']}: voce gastou {money(total)} em despesas reais.",
            ["Revise as maiores categorias.", "Compare com o mes anterior."],
            0.92,
            {"period": period_data, "expenses": round(total, 2)},
        )

    if asks_top_spend(text):
        categories = build_category_spend(period_transactions)
        if not categories:
            return no_scope_data("Nao encontrei despesas reais classificadas nesse periodo.", month_key)
        top = categories[0]
        return reply(
            "top_category",
            f"{period_data['label']}: maior categoria foi {top['category']} com {money(top['value'])} ({top['share']}% dos gastos).",
            ["Veja transacoes dessa categoria.", "Defina limite se for gasto recorrente."],
            0.9,
            {"period": period_data, "topCategory": top, "categories": categories[:5]},
        )

    if asks_largest_expense(text):
        expenses = [tx for tx in period_transactions if is_real_expense(tx)]
        if not expenses:
            return no_scope_data("Nao encontrei despesas reais nesse periodo.", month_key)
        top = max(expenses, key=lambda tx: abs(tx["amount"]))
        return reply(
            "largest_expense",
            f"{period_data['label']}: maior despesa foi {top['description']} ({top['category']}) de {money(abs(top['amount']))}.",
            ["Confirme se a categoria esta correta.", "Verifique se foi gasto pontual ou recorrente."],
            0.9,
            {"period": period_data, "transaction": top},
        )

    if asks_recurring(text):
        recurring = detect_recurring(transactions)
        if not recurring:
            return no_scope_data("Ainda nao detectei gastos recorrentes fortes. Preciso de pelo menos 3 meses parecidos.", month_key)
        top = recurring[0]
        return reply(
            "recurring",
            f"Maior recorrencia: {top['merchant']} em {top['category']}, media {money(top['averageAmount'])}/mes.",
            ["Revise se ainda usa esse servico.", "Cancele ou renegocie recorrencias sem uso."],
            0.88,
            {"recurring": recurring[:8]},
        )

    if asks_leftover(text):
        income = income_total(period_transactions)
        expenses = expense_total(period_transactions)
        net = income - expenses
        return reply(
            "period_leftover",
            f"{period_data['label']}: entrou {money(income)}, saiu {money(expenses)} e sobrou {money(net)}.",
            ["Se sobrou positivo, direcione parte para reserva.", "Se negativo, revise maiores categorias."],
            0.92,
            {"period": period_data, "income": round(income, 2), "expenses": round(expenses, 2), "net": round(net, 2)},
        )

    if asks_month_comparison(text):
        return compare_months_answer(transactions, month_key)

    if asks_budget_limits(text):
        summary = summarize(conn, month_key)
        exceeded = [item for item in summary["budgetStatus"] if item["status"] != "ok"]
        if not exceeded:
            return reply("budget_limits", "Nenhuma categoria passou do limite com os dados atuais.", [], 0.86, {"month": month_key, "items": []})
        top = exceeded[0]
        return reply(
            "budget_limits",
            f"{top['category']} pede atencao: projetado {money(top['projected'])} de limite {money(top['limit'])}.",
            [item["category"] for item in exceeded[:3]],
            0.88,
            {"month": month_key, "items": exceeded},
        )

    if asks_cuts(text):
        return cuts_answer(period_transactions, transactions, month_key)

    if asks_financial_health(text):
        return financial_health_answer(conn, month_key)

    if asks_transaction_list(text):
        return transaction_list_answer(period_transactions, period_data, category)

    return None


def reply(intent: str, answer: str, actions: list[str], confidence: float, data: dict | list | None = None) -> dict:
    return {"answer": answer, "actions": actions, "confidence": confidence, "mode": "deterministic", "intent": intent, "data": data}


def infer_month_key(text: str) -> str:
    today = date.today()
    current = today.strftime("%Y-%m")
    if "mes passado" in text:
        return previous_month_key(current)
    match = re.search(r"\b(20\d{2})(?:[-/]|\s+)(\d{1,2})\b", text)
    if match:
        return f"{match.group(1)}-{int(match.group(2)):02d}"
    for name, number in MONTHS.items():
        if re.search(rf"\b{re.escape(name)}\b", text):
            year_match = re.search(rf"{name}\s+de\s+(20\d{{2}})", text)
            year = int(year_match.group(1)) if year_match else today.year
            return f"{year}-{number}"
    return current


def infer_period(text: str) -> dict:
    today = date.today()
    current = today.strftime("%Y-%m")
    if "hoje" in text:
        return period("day", "hoje", today.isoformat(), today.isoformat(), current)
    if "ontem" in text:
        target = today - timedelta(days=1)
        return period("day", "ontem", target.isoformat(), target.isoformat(), target.strftime("%Y-%m"))
    if "semana passada" in text:
        start = today - timedelta(days=today.weekday() + 7)
        end = start + timedelta(days=6)
        return period("week", "semana passada", start.isoformat(), end.isoformat(), current)
    if "semana" in text or "ultimos 7 dias" in text or "ultimos sete dias" in text:
        start = today - timedelta(days=6 if "ultimos" in text else today.weekday())
        label = "ultimos 7 dias" if "ultimos" in text else "semana atual"
        return period("week", label, start.isoformat(), today.isoformat(), current)

    month_key = infer_month_key(text)
    year, month = [int(part) for part in month_key.split("-")]
    last_day = monthrange(year, month)[1]
    return period("month", f"mes {month_key}", f"{month_key}-01", f"{month_key}-{last_day:02d}", month_key)


def period(kind: str, label: str, start: str, end: str, month_key: str) -> dict:
    return {"kind": kind, "label": label, "start": start, "end": end, "month": month_key}


def filter_period(transactions: list[dict], period_data: dict) -> list[dict]:
    return [tx for tx in transactions if period_data["start"] <= tx["date"] <= period_data["end"]]


def infer_category(text: str) -> str | None:
    for alias, category in CATEGORY_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", text):
            return category
    return None


def asks_balance(text: str) -> bool:
    return any(phrase in text for phrase in ["saldo atual", "saldo agora", "qual meu saldo", "quanto tenho"])


def asks_category_spend(text: str, category: str | None) -> bool:
    return bool(category and any(word in text for word in ["gastei", "gasto", "gastou", "despesa", "quanto"]))


def asks_total_spend(text: str) -> bool:
    return any(
        phrase in text
        for phrase in [
            "quanto gastei",
            "quanto foi meus gastos",
            "quanto foram meus gastos",
            "gasto este mes",
            "gastei este mes",
            "despesa total",
            "total de despesas",
            "minhas despesas",
        ]
    )


def asks_income_total(text: str) -> bool:
    return any(
        phrase in text
        for phrase in ["quanto ganhei", "quanto recebi", "quanto entrou", "receita total", "total de receitas", "minha renda", "renda total"]
    )


def asks_top_spend(text: str) -> bool:
    return any(phrase in text for phrase in ["onde estou gastando mais", "onde gasto mais", "maior categoria", "categoria mais"])


def asks_largest_expense(text: str) -> bool:
    return any(phrase in text for phrase in ["maior gasto", "maior despesa", "compra mais cara"])


def asks_recurring(text: str) -> bool:
    return any(word in text for word in ["recorrente", "recorrencia", "assinatura", "fixo"])


def asks_leftover(text: str) -> bool:
    return any(word in text for word in ["sobrou", "sobra", "liquido", "saldo do mes", "saldo deste mes"])


def asks_month_comparison(text: str) -> bool:
    return any(phrase in text for phrase in ["mes passado", "aumentou", "diminuiu", "melhorou", "piorou"]) and "vida financeira" not in text


def asks_budget_limits(text: str) -> bool:
    return any(phrase in text for phrase in ["passaram do limite", "limite", "orcamento", "estourou"])


def asks_cuts(text: str) -> bool:
    return any(word in text for word in ["reduzir", "cortar", "economizar", "cortes"])


def asks_financial_health(text: str) -> bool:
    return "vida financeira" in text or "saude financeira" in text


def asks_work_total(text: str) -> bool:
    work_words = ["trabalhei", "horas trabalhadas", "hora trabalhada", "jornada", "turno", "ganhei trabalhando"]
    return any(word in text for word in work_words) and any(word in text for word in ["quanto", "total", "mes", "semana", "hoje", "ontem"])


def asks_hourly_rate_question(text: str) -> bool:
    return any(phrase in text for phrase in ["qual meu valor hora", "qual minha hora", "quanto ganho por hora", "meu valor por hora"])


def asks_transaction_list(text: str) -> bool:
    return any(word in text for word in ["liste", "listar", "mostre", "extrato", "transacoes", "lancamentos"])


def asks_category_trend(text: str, category: str | None) -> bool:
    if not category:
        return False
    return any(word in text for word in ["aumentou", "diminuiu", "caiu", "subiu", "tendencia", "evolucao", "comparar"])


def income_total(transactions: list[dict]) -> float:
    return sum(tx["amount"] for tx in transactions if is_real_income(tx))


def expense_total(transactions: list[dict]) -> float:
    gross = abs(sum(tx["amount"] for tx in transactions if is_real_expense(tx)))
    refunds = sum(refund_amount(tx) for tx in transactions)
    return max(gross - refunds, 0)


def income_answer(transactions: list[dict], period_data: dict) -> dict:
    rows = [tx for tx in transactions if is_real_income(tx)]
    total = income_total(rows)
    if not rows:
        return no_scope_data(f"Nao encontrei receitas em {period_data['label']}.", period_data["month"])
    return reply(
        "total_income",
        f"{period_data['label']}: entrou {money(total)} em receitas reais, considerando {len(rows)} lancamento(s).",
        ["Confira se transferencias recebidas nao sao entre contas proprias."],
        0.93,
        {"period": period_data, "income": round(total, 2), "count": len(rows)},
    )


def category_spend_answer(transactions: list[dict], period_data: dict, category: str | None) -> dict:
    if not category:
        return no_scope_data("Nao encontrei categoria na pergunta.", period_data["month"])
    selected = [tx for tx in transactions if tx["category"] == category]
    total = expense_total(selected)
    count = len([tx for tx in selected if is_real_expense(tx)])
    if count == 0:
        return no_scope_data(f"Nao encontrei gastos em {category} em {period_data['label']}.", period_data["month"])
    return reply(
        "category_spend",
        f"{period_data['label']}: voce gastou {money(total)} com {category}, considerando {count} transacao(oes).",
        ["Confira se todas as transacoes foram classificadas corretamente."],
        0.94,
        {"period": period_data, "category": category, "value": round(total, 2), "count": count},
    )


def compare_months_answer(transactions: list[dict], month_key: str) -> dict:
    previous = previous_month_key(month_key)
    current_txs = [tx for tx in transactions if tx["date"].startswith(month_key)]
    previous_txs = [tx for tx in transactions if tx["date"].startswith(previous)]
    current = expense_total(current_txs)
    old = expense_total(previous_txs)
    if not previous_txs:
        return no_scope_data(f"Sem dados de {previous} para comparar.", month_key)
    delta = current - old
    percent = (delta / old * 100) if old else 0
    direction = "aumentou" if delta > 0 else "caiu" if delta < 0 else "ficou igual"
    return reply(
        "month_comparison",
        f"Em {month_key}, seus gastos {direction} {money(abs(delta))} vs {previous} ({round(percent, 1)}%).",
        ["Compare as categorias com maior variacao."],
        0.9,
        {"month": month_key, "previousMonth": previous, "currentExpenses": round(current, 2), "previousExpenses": round(old, 2), "delta": round(delta, 2), "percent": round(percent, 1)},
    )


def category_trend_answer(transactions: list[dict], month_key: str, category: str | None) -> dict:
    if not category:
        return no_scope_data("Nao encontrei categoria para comparar.", month_key)
    previous = previous_month_key(month_key)
    current_rows = [tx for tx in transactions if tx["date"].startswith(month_key) and tx["category"] == category]
    previous_rows = [tx for tx in transactions if tx["date"].startswith(previous) and tx["category"] == category]
    current = expense_total(current_rows)
    old = expense_total(previous_rows)
    if not previous_rows:
        return no_scope_data(f"Sem dados de {category} em {previous} para comparar.", month_key)
    delta = current - old
    percent = (delta / old * 100) if old else 0
    direction = "aumentou" if delta > 0 else "caiu" if delta < 0 else "ficou igual"
    return reply(
        "category_trend",
        f"{category}: gasto {direction} {money(abs(delta))} em {month_key} vs {previous} ({round(percent, 1)}%).",
        ["Revise lancamentos que explicam a variacao."],
        0.9,
        {"category": category, "month": month_key, "previousMonth": previous, "current": round(current, 2), "previous": round(old, 2), "delta": round(delta, 2), "percent": round(percent, 1)},
    )


def cuts_answer(month_transactions: list[dict], all_transactions: list[dict], month_key: str) -> dict:
    categories = build_category_spend(month_transactions)
    recurring = detect_recurring(all_transactions)
    if not categories and not recurring:
        return no_scope_data("Ainda nao ha dados suficientes para sugerir cortes.", month_key)
    actions = []
    if categories:
        top = categories[0]
        actions.append(f"Revise {top['category']}: {money(top['value'])} no periodo.")
    if recurring:
        actions.append(f"Cheque recorrencia {recurring[0]['merchant']}: {money(recurring[0]['annualizedCost'])}/ano.")
    return reply(
        "cut_suggestions",
        "Cortes com maior impacto: " + " ".join(actions),
        actions,
        0.86,
        {"month": month_key, "categories": categories[:5], "recurring": recurring[:5]},
    )


def financial_health_answer(conn: Connection, month_key: str) -> dict:
    summary = summarize(conn, month_key)
    kpis = summary["kpis"]
    alerts = summary.get("alerts", [])
    alert_text = f" Alertas: {alerts[0]['title']}." if alerts else ""
    return reply(
        "financial_health",
        f"Saude financeira em {month_key}: {kpis['healthScore']}/100 ({kpis['healthLabel']}). Poupanca {kpis['savingsRate']}%, saldo projetado {money(kpis['projectedBalance'])}.{alert_text}",
        [item["title"] for item in alerts[:3]],
        0.88,
        {"month": month_key, "kpis": kpis, "alerts": alerts},
    )


def transaction_list_answer(transactions: list[dict], period_data: dict, category: str | None) -> dict:
    rows = transactions
    if category:
        rows = [tx for tx in rows if tx["category"] == category]
    rows = [tx for tx in rows if is_real_income(tx) or is_real_expense(tx) or refund_amount(tx)]
    if not rows:
        label = f" em {category}" if category else ""
        return no_scope_data(f"Nao encontrei lancamentos{label} em {period_data['label']}.", period_data["month"])
    top = rows[:6]
    lines = "; ".join(f"{tx['date']}: {tx['description']} {money(tx['amount'])}" for tx in top)
    return reply(
        "transaction_list",
        f"{period_data['label']}: encontrei {len(rows)} lancamento(s). {lines}.",
        ["Use filtros por categoria para revisar melhor."],
        0.9,
        {"period": period_data, "category": category, "transactions": top, "count": len(rows)},
    )


def work_total_answer(conn: Connection, period_data: dict) -> dict:
    rows = conn.execute(
        """
        SELECT date, start_time, end_time, break_minutes, hourly_rate, hours, gross_amount, description
        FROM work_sessions
        WHERE date >= ? AND date <= ?
        ORDER BY date DESC, id DESC
        """,
        (period_data["start"], period_data["end"]),
    ).fetchall()
    sessions = [dict(row) for row in rows]
    if not sessions:
        return no_scope_data(f"Nao encontrei jornadas em {period_data['label']}.", period_data["month"])
    hours = sum(float(item["hours"]) for item in sessions)
    gross = sum(float(item["gross_amount"]) for item in sessions)
    avg_rate = gross / hours if hours else 0
    return reply(
        "work_total",
        f"{period_data['label']}: voce trabalhou {hours:.2f}h e gerou {money(gross)} bruto. Valor medio/hora: {money(avg_rate)}.",
        ["Confira jornadas duplicadas.", "Registre intervalos quando existirem."],
        0.94,
        {"period": period_data, "hours": round(hours, 4), "gross": round(gross, 2), "averageRate": round(avg_rate, 2), "sessions": sessions[:8]},
    )


def hourly_rate_answer(conn: Connection) -> dict:
    rate = get_float_fact(conn, "hourly_rate")
    if rate is None:
        return reply(
            "hourly_rate_missing",
            "Ainda nao tenho seu valor/hora salvo. Diga algo como: minha hora e R$ 20.",
            ["Salvar valor/hora pelo chat."],
            0.9,
            {},
        )
    return reply(
        "hourly_rate",
        f"Seu valor/hora salvo e {money(rate)}.",
        ["Quando voce registrar uma jornada, calculo horas e receita automaticamente."],
        0.96,
        {"hourlyRate": rate},
    )


def no_scope_data(message: str, month_key: str) -> dict:
    return reply("insufficient_data", message, ["Importe extratos ou registre transacoes pelo chat."], 0.9, {"month": month_key})
