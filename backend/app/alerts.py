from __future__ import annotations


def money(value: float) -> str:
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def generate_alerts(summary: dict) -> list[dict]:
    alerts: list[dict] = []
    kpis = summary["kpis"]

    if kpis["balance"] < 0:
        alerts.append(
            {
                "type": "negative_balance",
                "severity": "high",
                "title": "Saldo negativo",
                "message": f"Saldo atual {money(kpis['balance'])}. Prioridade: reduzir saidas imediatas.",
            }
        )

    if kpis["expenses"] > kpis["income"] and kpis["income"] > 0:
        alerts.append(
            {
                "type": "cash_deficit",
                "severity": "high",
                "title": "Gasto acima da receita",
                "message": f"Gastos {money(kpis['expenses'])} contra receita {money(kpis['income'])}.",
            }
        )

    for budget in summary.get("budgetStatus", []):
        if budget["status"] == "danger":
            alerts.append(
                {
                    "type": "budget_overrun",
                    "severity": "high",
                    "title": f"{budget['category']} acima do limite",
                    "message": f"Projetado {money(budget['projected'])} de limite {money(budget['limit'])}.",
                }
            )

    for anomaly in summary.get("anomalies", [])[:3]:
        alerts.append(
            {
                "type": "anomaly",
                "severity": "medium",
                "title": "Despesa fora do padrao",
                "message": anomaly["message"],
            }
        )

    for recurring in summary.get("recurring", [])[:3]:
        if recurring["annualizedCost"] >= 600:
            alerts.append(
                {
                    "type": "recurring_expense",
                    "severity": "medium",
                    "title": f"Recorrencia: {recurring['merchant']}",
                    "message": f"Custo anual estimado {money(recurring['annualizedCost'])}.",
                }
            )

    monthly = summary.get("monthlySeries", [])
    if len(monthly) >= 2:
        previous = monthly[-2]["expenses"]
        current = monthly[-1]["expenses"]
        if previous > 0:
            growth = ((current - previous) / previous) * 100
            if growth >= 25:
                alerts.append(
                    {
                        "type": "monthly_growth",
                        "severity": "medium",
                        "title": "Despesas cresceram",
                        "message": f"Alta de {round(growth, 1)}% vs mes anterior.",
                    }
                )

    return alerts[:8]
