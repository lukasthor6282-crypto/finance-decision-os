from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from sqlite3 import Connection

from .analytics import money, summarize
from .repository import list_commitments


@dataclass(frozen=True)
class StrategicPlanInput:
    goal_name: str | None
    monthly_income: float | None
    target_amount: float | None
    current_age: int | None
    target_age: int | None
    months_left: int | None
    growth_rate_annual: float | None


def asks_strategic_plan(message: str) -> bool:
    text = soft_normalize(message)
    plan_terms = ["plano", "planejamento", "estrategia", "estrategico", "melhor plano"]
    goal_terms = ["comprar", "juntar", "guardar", "meta", "objetivo", "conquistar"]
    future_terms = ["antes dos", "ate os", "ate meus", "daqui", "vou ganhar mais", "prazo", "anos", "meses"]
    if any(term in text for term in plan_terms) and any(term in text for term in goal_terms):
        return True
    if "melhor plano" in text or "plano para" in text:
        return True
    return any(term in text for term in goal_terms) and any(term in text for term in future_terms)


def answer_strategic_plan(conn: Connection, message: str) -> dict:
    parsed = parse_strategic_plan(message)
    summary = summarize(conn)
    kpis = summary["kpis"]
    commitments = list_commitments(conn)
    fixed_expenses = sum(float(item["amount"]) for item in commitments if item["kind"] == "expense")
    fixed_income = sum(float(item["amount"]) for item in commitments if item["kind"] == "income")

    monthly_income = parsed.monthly_income or positive(kpis["income"]) or positive(fixed_income)
    monthly_expenses = max(float(kpis["expenses"] or 0), fixed_expenses)
    current_savings = max(float(kpis["balance"] or 0), 0)

    target_amount = parsed.target_amount
    months_left = parsed.months_left
    monthly_required = None
    required_rate = None
    available_now = None
    gap = None
    if target_amount and months_left:
        monthly_required = max((target_amount - current_savings) / months_left, 0)
        if monthly_income:
            required_rate = (monthly_required / monthly_income) * 100
            available_now = max(monthly_income - monthly_expenses, 0)
            gap = monthly_required - available_now

    scenarios = build_growth_scenarios(monthly_income, monthly_expenses, target_amount, current_savings, months_left)
    missing = missing_inputs(parsed)
    answer = build_answer(parsed, monthly_income, monthly_expenses, current_savings, monthly_required, required_rate, available_now, gap, missing)

    return {
        "answer": answer,
        "actions": build_actions(parsed, missing),
        "confidence": 0.88 if monthly_income or target_amount else 0.72,
        "mode": "deterministic",
        "intent": "strategic_plan",
        "data": {
            "goalName": parsed.goal_name,
            "monthlyIncome": round(monthly_income, 2) if monthly_income is not None else None,
            "monthlyExpenses": round(monthly_expenses, 2),
            "currentSavings": round(current_savings, 2),
            "targetAmount": round(target_amount, 2) if target_amount is not None else None,
            "currentAge": parsed.current_age,
            "targetAge": parsed.target_age,
            "monthsLeft": months_left,
            "growthRateAnnual": parsed.growth_rate_annual,
            "monthlyRequired": round(monthly_required, 2) if monthly_required is not None else None,
            "requiredIncomeShare": round(required_rate, 1) if required_rate is not None else None,
            "availableNow": round(available_now, 2) if available_now is not None else None,
            "monthlyGap": round(gap, 2) if gap is not None else None,
            "missing": missing,
            "scenarios": scenarios,
        },
    }


def parse_strategic_plan(message: str) -> StrategicPlanInput:
    text = soft_normalize(message)
    current_age = extract_current_age(text)
    target_age = extract_target_age(text)
    months_left = extract_months_left(text, current_age, target_age)
    return StrategicPlanInput(
        goal_name=extract_goal_name(text),
        monthly_income=extract_monthly_income(text),
        target_amount=extract_target_amount(text),
        current_age=current_age,
        target_age=target_age,
        months_left=months_left,
        growth_rate_annual=extract_growth_rate(text),
    )


def build_answer(
    parsed: StrategicPlanInput,
    monthly_income: float | None,
    monthly_expenses: float,
    current_savings: float,
    monthly_required: float | None,
    required_rate: float | None,
    available_now: float | None,
    gap: float | None,
    missing: list[str],
) -> str:
    goal = parsed.goal_name or "essa meta"
    lines = [f"Plano estrategico para {goal}."]

    used = []
    if monthly_income is not None:
        used.append(f"renda base {money(monthly_income)}/mes")
    if parsed.target_amount is not None:
        used.append(f"meta {money(parsed.target_amount)}")
    if parsed.months_left is not None:
        used.append(f"prazo aproximado {parsed.months_left} meses")
    if used:
        lines.append("Dados usados: " + ", ".join(used) + ".")

    if missing:
        lines.append("Conta exata ainda falta: " + ", ".join(missing) + ". Nao vou inventar esses valores.")

    if monthly_required is not None:
        rate_text = f" ({required_rate:.1f}% da renda)" if required_rate is not None else ""
        lines.append(f"Aporte necessario: {money(monthly_required)}/mes{rate_text}.")
        if available_now is not None:
            if gap is not None and gap <= 0:
                lines.append(f"Com gastos atuais, caberia: sobra estimada {money(available_now)}/mes.")
            else:
                lines.append(f"Com gastos atuais, falta abrir {money(max(gap or 0, 0))}/mes de folga.")

    lines.extend(
        [
            "Plano: 1) fechar custo real mensal por 30 dias; 2) guardar primeiro reserva de 1 a 3 meses de gastos; 3) separar fundo da meta em conta aparte; 4) subir renda antes de assumir parcela grande; 5) comprar so quando parcela + seguro + uso nao travar o caixa.",
            "Regra de decisao: se aporte da meta passar de 30% da renda, plano depende mais de aumentar renda do que cortar gasto pequeno.",
            "Proximo passo: mande idade atual, preco alvo/entrada e gasto mensal medio. Eu recalculo com numeros fechados.",
        ]
    )
    return " ".join(lines)


def build_actions(parsed: StrategicPlanInput, missing: list[str]) -> list[str]:
    actions = []
    if "preco alvo ou entrada desejada" in missing:
        actions.append("Informar preco alvo ou entrada desejada.")
    if "idade atual ou prazo em meses/anos" in missing:
        actions.append("Informar idade atual ou prazo real.")
    actions.extend(
        [
            "Registrar despesas fixas e variaveis por 30 dias.",
            "Definir aporte mensal automatico para a meta.",
            "Revisar plano quando renda mudar.",
        ]
    )
    return actions[:5]


def build_growth_scenarios(
    monthly_income: float | None,
    monthly_expenses: float,
    target_amount: float | None,
    current_savings: float,
    months_left: int | None,
) -> list[dict]:
    if not monthly_income or not target_amount or not months_left:
        return []

    result = []
    remaining = max(target_amount - current_savings, 0)
    for annual_growth in (0.0, 0.1, 0.2):
        final_income = monthly_income * ((1 + annual_growth) ** (months_left / 12))
        avg_income = (monthly_income + final_income) / 2
        monthly_required = remaining / months_left
        avg_available = max(avg_income - monthly_expenses, 0)
        result.append(
            {
                "annualGrowth": round(annual_growth * 100, 1),
                "averageIncome": round(avg_income, 2),
                "finalIncome": round(final_income, 2),
                "monthlyRequired": round(monthly_required, 2),
                "averageAvailable": round(avg_available, 2),
                "gap": round(monthly_required - avg_available, 2),
                "feasible": avg_available >= monthly_required,
            }
        )
    return result


def missing_inputs(parsed: StrategicPlanInput) -> list[str]:
    missing = []
    if parsed.monthly_income is None:
        missing.append("renda mensal")
    if parsed.target_amount is None:
        missing.append("preco alvo ou entrada desejada")
    if parsed.months_left is None:
        missing.append("idade atual ou prazo em meses/anos")
    return missing


def extract_goal_name(text: str) -> str | None:
    match = re.search(r"\bcomprar\s+(?:um|uma|o|a)?\s*(.+?)(?=\s+(?:antes|ate|contando|qual|como|de r\$|por r\$)|$)", text)
    if match:
        return clean_goal_name(match.group(1))
    match = re.search(r"\b(?:meta|objetivo)\s+(?:de|para)\s+(.+?)(?=\s+(?:antes|ate|qual|como)|$)", text)
    if match:
        return clean_goal_name(match.group(1))
    return None


def clean_goal_name(value: str) -> str | None:
    clean = re.sub(r"\b(comprar|guardar|juntar|eu|quero|um|uma|o|a)\b", " ", value)
    clean = re.sub(r"\s+", " ", clean).strip(" .,;:-")
    if not clean:
        return None
    words = []
    for word in clean.split():
        if word in {"byd", "bmw"}:
            words.append(word.upper())
        else:
            words.append(word.capitalize())
    return " ".join(words[:8])


def extract_monthly_income(text: str) -> float | None:
    patterns = [
        rf"\b(?:ganho|recebo|renda|salario|faturamento)\s*(?:em media|media|mensal|por mes|ao mes|de)?\s*(?:de)?\s*({AMOUNT_RE})(?:\s*(mil))?\s*(?:por mes|ao mes|mensal|mes)?",
        rf"\b({AMOUNT_RE})(?:\s*(mil))?\s*(?:por mes|ao mes|mensal)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            amount = parse_amount(match.group(1), suffix=match.group(2) if len(match.groups()) > 1 else None)
            if amount and amount >= 50:
                return amount
    return None


def extract_target_amount(text: str) -> float | None:
    patterns = [
        rf"\b(?:meta|objetivo|preco|valor|custa|custando|entrada)\s*(?:de|por|alvo)?\s*({AMOUNT_RE})(?:\s*(mil))?",
        rf"\bcomprar\s+.+?\s+(?:de|por|custando)\s*({AMOUNT_RE})(?:\s*(mil))?",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        amount = parse_amount(match.group(1), suffix=match.group(2) if len(match.groups()) > 1 else None)
        if amount and amount >= 500:
            return amount
    return None


def extract_current_age(text: str) -> int | None:
    match = re.search(r"\b(?:tenho|idade atual|estou com)\s+(\d{1,2})\s*(?:anos)?\b", text)
    return int(match.group(1)) if match else None


def extract_target_age(text: str) -> int | None:
    match = re.search(r"\b(?:antes dos|antes de|ate os|ate meus|ate completar|ate)\s+(\d{1,2})\b", text)
    return int(match.group(1)) if match else None


def extract_months_left(text: str, current_age: int | None, target_age: int | None) -> int | None:
    match = re.search(r"\b(?:em|daqui a|daqui)\s+(\d{1,2})\s*(anos|ano|meses|mes)\b", text)
    if match:
        value = int(match.group(1))
        unit = match.group(2)
        return value * 12 if unit.startswith("ano") else value
    if current_age is not None and target_age is not None and target_age > current_age:
        return (target_age - current_age) * 12
    return None


def extract_growth_rate(text: str) -> float | None:
    match = re.search(r"(\d{1,2}(?:[,.]\d{1,2})?)\s*%\s*(?:ao ano|por ano|a a|ano)", text)
    if not match:
        return None
    return parse_amount(match.group(1)) / 100


NUMBER_RE = r"\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:[.,]\d{1,2})?"
AMOUNT_RE = rf"(?:r\$\s*)?(?:{NUMBER_RE})"


def parse_amount(value: str, suffix: str | None = None) -> float:
    clean = value.replace("r$", "").replace(" ", "").strip()
    if "," in clean and "." in clean:
        clean = clean.replace(".", "").replace(",", ".")
    elif "," in clean:
        clean = clean.replace(",", ".")
    elif "." in clean:
        left, right = clean.rsplit(".", 1)
        if len(right) == 3 and left.isdigit():
            clean = left + right
    amount = float(clean)
    if suffix == "mil":
        amount *= 1000
    return amount


def soft_normalize(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("r $", "r$")
    text = re.sub(r"[()?!;:,]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def positive(value: float | int | None) -> float | None:
    if value is None:
        return None
    numeric = float(value)
    return numeric if numeric > 0 else None
