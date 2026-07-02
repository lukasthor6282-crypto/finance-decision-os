from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from sqlite3 import Connection

from .classifier import classify
from .normalization import normalize_text
from .repository import list_budgets, list_goals


def money(value: float) -> str:
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def rows_to_dicts(rows) -> list[dict]:
    return [dict(row) for row in rows]


def get_transactions(
    conn: Connection,
    limit: int = 500,
    start: str | None = None,
    end: str | None = None,
    category: str | None = None,
    account: str | None = None,
    search: str | None = None,
) -> list[dict]:
    clauses: list[str] = []
    params: list[object] = []
    if start:
        clauses.append("date >= ?")
        params.append(start)
    if end:
        clauses.append("date <= ?")
        params.append(end)
    if category:
        clauses.append("category = ?")
        params.append(category)
    if account:
        clauses.append("account = ?")
        params.append(account)
    if search:
        clauses.append("(description LIKE ? OR merchant LIKE ? OR notes LIKE ?)")
        term = f"%{search}%"
        params.extend([term, term, term])

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(max(1, min(limit, 2000)))
    rows = conn.execute(
        f"""
        SELECT id, date, description, amount, category, account, source, notes,
               merchant, normalized_description, is_recurring
        FROM transactions
        {where}
        ORDER BY date DESC, id DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return rows_to_dicts(rows)


def summarize(conn: Connection, month: str | None = None) -> dict:
    transactions = get_transactions(conn, 2000)
    today = date.today()
    month_key = month or today.strftime("%Y-%m")
    current_month = [tx for tx in transactions if tx["date"].startswith(month_key)]
    if not current_month and transactions and month is None:
        month_key = max(tx["date"][:7] for tx in transactions)
        current_month = [tx for tx in transactions if tx["date"].startswith(month_key)]

    previous_month = previous_month_key(month_key)
    previous_month_txs = [tx for tx in transactions if tx["date"].startswith(previous_month)]

    income = sum(tx["amount"] for tx in current_month if tx["amount"] > 0)
    expenses = abs(sum(tx["amount"] for tx in current_month if tx["amount"] < 0))
    previous_expenses = abs(sum(tx["amount"] for tx in previous_month_txs if tx["amount"] < 0))
    balance = sum(tx["amount"] for tx in transactions)
    net = income - expenses
    savings_rate = (net / income * 100) if income else 0

    observed_days = observed_day_count(current_month, today)
    days_in_month = 30
    daily_burn = expenses / max(observed_days, 1)
    projected_expense = daily_burn * days_in_month
    projected_balance = balance - max(projected_expense - expenses, 0)
    runway_days = round(balance / daily_burn, 1) if daily_burn > 0 else None

    monthly_series = build_monthly_series(transactions)
    category_spend = build_category_spend(transactions)
    budget_status = build_budget_status(conn, current_month, daily_burn, observed_days, days_in_month)
    recurring = detect_recurring(transactions)
    anomalies = detect_anomalies(transactions)
    goals = enrich_goals(list_goals(conn))
    risk_score = score_cash_risk(savings_rate, projected_balance, anomalies, budget_status)
    health = financial_health_score(savings_rate, risk_score["label"], budget_status, recurring, goals)
    action_plan = build_action_plan(savings_rate, category_spend, budget_status, anomalies, recurring, goals)

    return {
        "asOf": today.isoformat(),
        "month": month_key,
        "kpis": {
            "balance": round(balance, 2),
            "income": round(income, 2),
            "expenses": round(expenses, 2),
            "previousExpenses": round(previous_expenses, 2),
            "net": round(net, 2),
            "savingsRate": round(savings_rate, 1),
            "projectedExpense": round(projected_expense, 2),
            "projectedBalance": round(projected_balance, 2),
            "dailyBurn": round(daily_burn, 2),
            "runwayDays": runway_days,
            "cashRisk": risk_score["label"],
            "riskLevel": risk_score["level"],
            "healthScore": health["score"],
            "healthLabel": health["label"],
        },
        "monthlySeries": monthly_series,
        "categorySpend": category_spend,
        "budgetStatus": budget_status,
        "recurring": recurring[:10],
        "anomalies": anomalies[:8],
        "recentTransactions": transactions[:12],
        "actionPlan": action_plan,
        "goals": goals,
        "insights": build_insights(savings_rate, category_spend, budget_status, anomalies, recurring, goals),
    }


def previous_month_key(month_key: str) -> str:
    year, month = [int(part) for part in month_key.split("-")]
    if month == 1:
        return f"{year - 1}-12"
    return f"{year}-{month - 1:02d}"


def observed_day_count(transactions: list[dict], today: date) -> int:
    days = [datetime.fromisoformat(tx["date"]).day for tx in transactions]
    return max(days, default=today.day)


def build_monthly_series(transactions: list[dict]) -> list[dict]:
    monthly = defaultdict(lambda: {"month": "", "income": 0.0, "expenses": 0.0, "net": 0.0})
    for tx in transactions:
        key = tx["date"][:7]
        monthly[key]["month"] = key
        if tx["amount"] >= 0:
            monthly[key]["income"] += tx["amount"]
        else:
            monthly[key]["expenses"] += abs(tx["amount"])
        monthly[key]["net"] += tx["amount"]
    return [
        {
            "month": value["month"],
            "income": round(value["income"], 2),
            "expenses": round(value["expenses"], 2),
            "net": round(value["net"], 2),
        }
        for _, value in sorted(monthly.items())[-12:]
    ]


def build_category_spend(transactions: list[dict], current_only: bool = False) -> list[dict]:
    today = date.today()
    month_key = today.strftime("%Y-%m")
    categories = defaultdict(float)
    category_counts = defaultdict(int)
    for tx in transactions:
        if current_only and not tx["date"].startswith(month_key):
            continue
        if tx["amount"] < 0:
            categories[tx["category"]] += abs(tx["amount"])
            category_counts[tx["category"]] += 1
    total = sum(categories.values())
    return [
        {
            "category": category,
            "value": round(value, 2),
            "count": category_counts[category],
            "share": round((value / total) * 100, 1) if total else 0,
        }
        for category, value in sorted(categories.items(), key=lambda item: item[1], reverse=True)
    ][:10]


def build_budget_status(
    conn: Connection,
    current_month: list[dict],
    daily_burn: float,
    observed_days: int,
    days_in_month: int,
) -> list[dict]:
    budgets = list_budgets(conn)
    current_categories = defaultdict(float)
    for tx in current_month:
        if tx["amount"] < 0:
            current_categories[tx["category"]] += abs(tx["amount"])

    status = []
    for budget in budgets:
        spent = current_categories.get(budget["category"], 0)
        limit = budget["monthly_limit"]
        category_daily = spent / max(observed_days, 1)
        projected = category_daily * days_in_month
        ratio = (spent / limit) * 100 if limit else 0
        projected_ratio = (projected / limit) * 100 if limit else 0
        label = "ok"
        if projected_ratio >= 105 or ratio >= 95:
            label = "danger"
        elif projected_ratio >= 85 or ratio >= 75:
            label = "warn"
        status.append(
            {
                "category": budget["category"],
                "spent": round(spent, 2),
                "limit": round(limit, 2),
                "remaining": round(limit - spent, 2),
                "ratio": round(ratio, 1),
                "projected": round(projected, 2),
                "projectedRatio": round(projected_ratio, 1),
                "status": label,
            }
        )
    return sorted(status, key=lambda item: item["projectedRatio"], reverse=True)


def score_cash_risk(
    savings_rate: float,
    projected_balance: float,
    anomalies: list[dict],
    budget_status: list[dict],
) -> dict:
    points = 0
    if savings_rate < 5:
        points += 2
    elif savings_rate < 15:
        points += 1
    if projected_balance < 0:
        points += 3
    elif projected_balance < 3000:
        points += 1
    if len(anomalies) >= 3:
        points += 1
    if any(item["status"] == "danger" for item in budget_status):
        points += 1

    if points >= 4:
        return {"label": "Alto", "level": "danger"}
    if points >= 2:
        return {"label": "Medio", "level": "warn"}
    return {"label": "Baixo", "level": "ok"}


def detect_anomalies(transactions: list[dict]) -> list[dict]:
    by_category = defaultdict(list)
    for tx in transactions:
        if tx["amount"] < 0:
            by_category[tx["category"]].append(abs(tx["amount"]))

    averages = {
        category: (sum(values) / len(values))
        for category, values in by_category.items()
        if len(values) >= 4
    }
    anomalies = []
    for tx in transactions:
        amount = abs(tx["amount"])
        avg = averages.get(tx["category"])
        if tx["amount"] < 0 and avg and amount > avg * 2.2 and amount > 250:
            anomalies.append(
                {
                    "date": tx["date"],
                    "description": tx["description"],
                    "category": tx["category"],
                    "amount": round(amount, 2),
                    "baseline": round(avg, 2),
                    "message": f"{tx['category']} acima do padrao: {money(amount)} vs media {money(avg)}",
                }
            )
    return anomalies


def detect_recurring(transactions: list[dict]) -> list[dict]:
    groups = defaultdict(list)
    for tx in transactions:
        if tx["amount"] >= 0:
            continue
        key = normalize_text(tx.get("merchant") or tx["description"])
        if not key:
            continue
        groups[key].append(tx)

    recurring = []
    for merchant, rows in groups.items():
        months = {row["date"][:7] for row in rows}
        if len(months) < 3:
            continue
        amounts = [abs(row["amount"]) for row in rows]
        avg = sum(amounts) / len(amounts)
        if avg < 15:
            continue
        last = max(rows, key=lambda item: item["date"])
        recurring.append(
            {
                "merchant": merchant.title(),
                "category": last["category"],
                "averageAmount": round(avg, 2),
                "lastDate": last["date"],
                "monthsDetected": len(months),
                "annualizedCost": round(avg * 12, 2),
            }
        )
    return sorted(recurring, key=lambda item: item["annualizedCost"], reverse=True)


def enrich_goals(goals: list[dict]) -> list[dict]:
    enriched = []
    today = date.today()
    for goal in goals:
        target = float(goal["target_amount"])
        current = float(goal["current_amount"])
        progress = (current / target) * 100 if target else 0
        monthly_required = None
        if goal.get("due_date"):
            due = datetime.fromisoformat(goal["due_date"]).date()
            days_left = max((due - today).days, 1)
            months_left = max(days_left / 30, 1)
            monthly_required = max((target - current) / months_left, 0)
        enriched.append(
            {
                **goal,
                "progress": round(progress, 1),
                "remaining": round(max(target - current, 0), 2),
                "monthlyRequired": round(monthly_required, 2) if monthly_required is not None else None,
            }
        )
    return enriched


def financial_health_score(
    savings_rate: float,
    risk_label: str,
    budget_status: list[dict],
    recurring: list[dict],
    goals: list[dict],
) -> dict:
    score = 100
    if savings_rate < 20:
        score -= min(28, int((20 - savings_rate) * 1.2))
    if risk_label == "Alto":
        score -= 25
    elif risk_label == "Medio":
        score -= 12
    score -= min(18, 6 * sum(1 for item in budget_status if item["status"] == "danger"))
    score -= min(10, 2 * len([item for item in recurring if item["annualizedCost"] > 1000]))
    score += min(8, 2 * len([goal for goal in goals if goal["progress"] >= 25]))
    score = max(0, min(100, score))
    label = "Forte" if score >= 80 else "Estavel" if score >= 60 else "Atencao"
    return {"score": score, "label": label}


def build_action_plan(
    savings_rate: float,
    category_spend: list[dict],
    budget_status: list[dict],
    anomalies: list[dict],
    recurring: list[dict],
    goals: list[dict],
) -> list[dict]:
    actions = []
    over_budget = [item for item in budget_status if item["status"] == "danger"]
    if over_budget:
        top = sorted(over_budget, key=lambda item: item["projectedRatio"], reverse=True)[0]
        actions.append(
            {
                "priority": "alta",
                "title": f"Travar {top['category']} esta semana",
                "detail": f"Projecao em {top['projectedRatio']}% do limite. Restante: {money(top['remaining'])}.",
                "impact": "evita estouro de orcamento",
            }
        )
    if savings_rate < 20:
        actions.append(
            {
                "priority": "alta",
                "title": "Subir poupanca para 20%",
                "detail": "Direcione sobra para reserva antes de liberar gasto variavel.",
                "impact": "reduz risco de caixa",
            }
        )
    if recurring:
        top_recurring = recurring[0]
        actions.append(
            {
                "priority": "media",
                "title": f"Revisar recorrencia: {top_recurring['merchant']}",
                "detail": f"Custo anual estimado: {money(top_recurring['annualizedCost'])}.",
                "impact": "corta vazamento recorrente",
            }
        )
    if category_spend:
        top_category = category_spend[0]
        actions.append(
            {
                "priority": "media",
                "title": f"Auditar {top_category['category']}",
                "detail": f"Maior saida acumulada: {money(top_category['value'])}.",
                "impact": "maior alavanca de economia",
            }
        )
    if anomalies:
        actions.append(
            {
                "priority": "media",
                "title": "Validar gastos fora do padrao",
                "detail": f"{len(anomalies)} gasto(s) acima do historico detectado(s).",
                "impact": "corrige erro ou fraude cedo",
            }
        )
    late_goals = [goal for goal in goals if goal.get("monthlyRequired") and goal["progress"] < 50]
    if late_goals:
        goal = sorted(late_goals, key=lambda item: item["monthlyRequired"], reverse=True)[0]
        actions.append(
            {
                "priority": "media",
                "title": f"Recalibrar meta: {goal['name']}",
                "detail": f"Precisa de {money(goal['monthlyRequired'])}/mes para bater prazo.",
                "impact": "evita meta atrasada",
            }
        )
    if not actions:
        actions.append(
            {
                "priority": "baixa",
                "title": "Manter plano atual",
                "detail": "Risco baixo. Proximo ganho vem de automatizar aportes.",
                "impact": "mantem consistencia",
            }
        )
    return actions[:6]


def build_insights(
    savings_rate: float,
    category_spend: list[dict],
    budget_status: list[dict],
    anomalies: list[dict],
    recurring: list[dict],
    goals: list[dict],
) -> list[dict]:
    insights = []
    if savings_rate < 20:
        insights.append(
            {
                "type": "risk",
                "severity": "high" if savings_rate < 10 else "medium",
                "title": "Poupanca abaixo da faixa alvo",
                "message": f"Taxa atual: {round(savings_rate, 1)}%. Alvo operacional: 20%.",
            }
        )
    for budget in budget_status[:3]:
        if budget["status"] != "ok":
            insights.append(
                {
                    "type": "budget",
                    "severity": "high" if budget["status"] == "danger" else "medium",
                    "title": f"{budget['category']} pede controle",
                    "message": f"Projetado: {money(budget['projected'])} de {money(budget['limit'])}.",
                }
            )
    if recurring:
        insights.append(
            {
                "type": "recurring",
                "severity": "medium",
                "title": "Recorrencias detectadas",
                "message": f"{len(recurring)} possiveis gastos fixos. Maior: {recurring[0]['merchant']} ({money(recurring[0]['annualizedCost'])}/ano).",
            }
        )
    if anomalies:
        insights.append(
            {
                "type": "anomaly",
                "severity": "medium",
                "title": "Gastos fora do padrao",
                "message": anomalies[0]["message"],
            }
        )
    if goals:
        top_goal = sorted(goals, key=lambda item: item["progress"])[0]
        insights.append(
            {
                "type": "goal",
                "severity": "low",
                "title": f"Meta em foco: {top_goal['name']}",
                "message": f"Falta {money(top_goal['remaining'])}. Progresso: {top_goal['progress']}%.",
            }
        )
    if category_spend:
        top = category_spend[0]
        insights.append(
            {
                "type": "category",
                "severity": "low",
                "title": f"Maior categoria: {top['category']}",
                "message": f"{money(top['value'])} acumulado, {top['share']}% dos gastos classificados.",
            }
        )
    return insights[:8]


def scenario(conn: Connection, description: str, amount: float, category: str | None = None) -> dict:
    summary = summarize(conn)
    guessed_category = category or classify(description, -abs(amount)).category
    income = summary["kpis"]["income"]
    expenses = summary["kpis"]["expenses"] + amount
    net = income - expenses
    rate = (net / income * 100) if income else 0
    old_rate = summary["kpis"]["savingsRate"]

    budget = next((item for item in summary["budgetStatus"] if item["category"] == guessed_category), None)
    budget_after = None
    if budget:
        spent_after = budget["spent"] + amount
        ratio_after = (spent_after / budget["limit"]) * 100 if budget["limit"] else 0
        budget_after = {
            "category": guessed_category,
            "spentAfter": round(spent_after, 2),
            "ratioAfter": round(ratio_after, 1),
            "remainingAfter": round(budget["limit"] - spent_after, 2),
        }

    if rate >= 20 and (not budget_after or budget_after["ratioAfter"] <= 85):
        verdict = "Aprovado com folga"
        level = "ok"
    elif rate >= 10 and (not budget_after or budget_after["ratioAfter"] <= 100):
        verdict = "Aprovado com ajuste"
        level = "warn"
    else:
        verdict = "Segurar compra"
        level = "danger"

    return {
        "description": description,
        "amount": amount,
        "category": guessed_category,
        "verdict": verdict,
        "level": level,
        "newSavingsRate": round(rate, 1),
        "deltaSavingsRate": round(rate - old_rate, 1),
        "budgetAfter": budget_after,
        "message": f"{description} de {money(amount)} leva poupanca de {old_rate}% para {round(rate, 1)}%.",
    }
