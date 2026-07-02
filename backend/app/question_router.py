from __future__ import annotations

import re
from datetime import date
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


MONTHS = {
    "janeiro": "01",
    "fevereiro": "02",
    "marco": "03",
    "março": "03",
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
}


def answer_question(conn: Connection, message: str) -> dict | None:
    text = normalize_text(message)
    month_key = infer_month_key(text)
    transactions = get_transactions(conn, 2000)
    if not transactions:
        return reply(
            "no_data",
            "Ainda nao ha dados suficientes. Registre receitas/despesas ou importe um extrato primeiro.",
            [],
            0.95,
            {"month": month_key},
        )

    category = infer_category(text)
    month_transactions = [tx for tx in transactions if tx["date"].startswith(month_key)]

    if asks_category_spend(text, category):
        return category_spend_answer(month_transactions, month_key, category)

    if asks_total_spend(text):
        total = expense_total(month_transactions)
        return reply(
            "total_expense",
            f"Em {month_key}, voce gastou {money(total)} em despesas reais.",
            ["Revise as maiores categorias.", "Compare com o mes anterior."],
            0.92,
            {"month": month_key, "expenses": round(total, 2)},
        )

    if asks_top_spend(text):
        categories = build_category_spend(month_transactions)
        if not categories:
            return no_scope_data("Nao encontrei despesas reais classificadas nesse periodo.", month_key)
        top = categories[0]
        return reply(
            "top_category",
            f"Maior categoria em {month_key}: {top['category']} com {money(top['value'])} ({top['share']}% dos gastos).",
            ["Veja transacoes dessa categoria.", "Defina limite se for gasto recorrente."],
            0.9,
            {"month": month_key, "topCategory": top, "categories": categories[:5]},
        )

    if asks_largest_expense(text):
        expenses = [tx for tx in month_transactions if is_real_expense(tx)]
        if not expenses:
            return no_scope_data("Nao encontrei despesas reais nesse periodo.", month_key)
        top = max(expenses, key=lambda tx: abs(tx["amount"]))
        return reply(
            "largest_expense",
            f"Maior despesa em {month_key}: {top['description']} ({top['category']}) de {money(abs(top['amount']))}.",
            ["Confirme se a categoria esta correta.", "Verifique se foi gasto pontual ou recorrente."],
            0.9,
            {"month": month_key, "transaction": top},
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
        income = income_total(month_transactions)
        expenses = expense_total(month_transactions)
        net = income - expenses
        return reply(
            "monthly_leftover",
            f"Em {month_key}, entrou {money(income)}, saiu {money(expenses)} e sobrou {money(net)}.",
            ["Se sobrou positivo, direcione parte para reserva.", "Se negativo, revise maiores categorias."],
            0.92,
            {"month": month_key, "income": round(income, 2), "expenses": round(expenses, 2), "net": round(net, 2)},
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
        return cuts_answer(month_transactions, transactions, month_key)

    if asks_financial_health(text):
        return financial_health_answer(conn, month_key)

    return None


def reply(intent: str, answer: str, actions: list[str], confidence: float, data: dict | list | None = None) -> dict:
    return {"answer": answer, "actions": actions, "confidence": confidence, "mode": "deterministic", "intent": intent, "data": data}


def infer_month_key(text: str) -> str:
    today = date.today()
    current = today.strftime("%Y-%m")
    if "mes passado" in text or "mês passado" in text:
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


def infer_category(text: str) -> str | None:
    for alias, category in CATEGORY_ALIASES.items():
        if alias in text:
            return category
    return None


def asks_category_spend(text: str, category: str | None) -> bool:
    return bool(category and any(word in text for word in ["gastei", "gasto", "gastou", "despesa", "quanto"]))


def asks_total_spend(text: str) -> bool:
    return any(phrase in text for phrase in ["quanto gastei", "gasto este mes", "gastei este mes", "despesa total", "total de despesas"])


def asks_top_spend(text: str) -> bool:
    return any(phrase in text for phrase in ["onde estou gastando mais", "onde gasto mais", "maior categoria", "categoria mais"])


def asks_largest_expense(text: str) -> bool:
    return any(phrase in text for phrase in ["maior gasto", "maior despesa", "compra mais cara"])


def asks_recurring(text: str) -> bool:
    return any(word in text for word in ["recorrente", "recorrencia", "assinatura", "fixo"])


def asks_leftover(text: str) -> bool:
    return any(word in text for word in ["sobrou", "sobra", "liquido", "saldo do mes"])


def asks_month_comparison(text: str) -> bool:
    return any(phrase in text for phrase in ["mes passado", "mês passado", "aumentou", "diminuiu", "melhorou", "piorou"]) and "vida financeira" not in text


def asks_budget_limits(text: str) -> bool:
    return any(phrase in text for phrase in ["passaram do limite", "limite", "orcamento", "orçamento", "estourou"])


def asks_cuts(text: str) -> bool:
    return any(word in text for word in ["reduzir", "cortar", "economizar", "cortes"])


def asks_financial_health(text: str) -> bool:
    return "vida financeira" in text or "saude financeira" in text or "saúde financeira" in text


def income_total(transactions: list[dict]) -> float:
    return sum(tx["amount"] for tx in transactions if is_real_income(tx))


def expense_total(transactions: list[dict]) -> float:
    gross = abs(sum(tx["amount"] for tx in transactions if is_real_expense(tx)))
    refunds = sum(refund_amount(tx) for tx in transactions)
    return max(gross - refunds, 0)


def category_spend_answer(transactions: list[dict], month_key: str, category: str | None) -> dict:
    if not category:
        return no_scope_data("Nao encontrei categoria na pergunta.", month_key)
    selected = [tx for tx in transactions if tx["category"] == category]
    total = expense_total(selected)
    count = len([tx for tx in selected if is_real_expense(tx)])
    if count == 0:
        return no_scope_data(f"Nao encontrei gastos em {category} em {month_key}.", month_key)
    return reply(
        "category_spend",
        f"Em {month_key}, voce gastou {money(total)} com {category}, considerando {count} transacao(oes).",
        ["Confira se todas as transacoes foram classificadas corretamente."],
        0.94,
        {"month": month_key, "category": category, "value": round(total, 2), "count": count},
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


def no_scope_data(message: str, month_key: str) -> dict:
    return reply("insufficient_data", message, ["Importe extratos ou registre transacoes pelo chat."], 0.9, {"month": month_key})
