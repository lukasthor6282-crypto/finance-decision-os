from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from sqlite3 import Connection

from .analytics import money, summarize
from .repository import get_fact, get_float_fact, list_commitments, set_fact


CONTEXT_KEY = "strategic_plan_context"


@dataclass(frozen=True)
class StrategicPlanInput:
    goal_name: str | None
    monthly_income: float | None
    monthly_expenses: float | None
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


def continues_strategic_plan(conn: Connection, message: str) -> bool:
    if not load_plan_context(conn):
        return False
    text = soft_normalize(message)
    if asks_strategic_plan(message):
        return True
    cues = [
        "ate la",
        "pra meta",
        "para meta",
        "idade",
        "anos",
        "meses",
        "preco",
        "valor",
        "entrada",
        "custa",
        "custando",
        "gasto mensal",
        "despesa mensal",
        "custo mensal",
        "por mes",
        "ao mes",
        "mensal",
        "minhas despesas",
        "meus gastos",
    ]
    return any(cue in text for cue in cues) and bool(re.search(r"\d", text))


def answer_strategic_plan(conn: Connection, message: str) -> dict:
    parsed = merge_with_context(load_plan_context(conn), parse_strategic_plan(message))
    parsed = apply_profile_facts(conn, parsed)
    summary = summarize(conn)
    kpis = summary["kpis"]
    commitments = list_commitments(conn)
    fixed_expenses = sum(float(item["amount"]) for item in commitments if item["kind"] == "expense")
    fixed_income = sum(float(item["amount"]) for item in commitments if item["kind"] == "income")

    monthly_income = parsed.monthly_income or positive(kpis["income"]) or positive(fixed_income)
    monthly_expenses = parsed.monthly_expenses if parsed.monthly_expenses is not None else max(float(kpis["expenses"] or 0), fixed_expenses)
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
    if monthly_expenses <= 0 and "gasto mensal medio" not in missing:
        missing.append("gasto mensal medio")
    answer = build_answer(parsed, monthly_income, monthly_expenses, current_savings, monthly_required, required_rate, available_now, gap, missing)
    save_plan_context(conn, parsed)

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


def apply_profile_facts(conn: Connection, parsed: StrategicPlanInput) -> StrategicPlanInput:
    current_age = parsed.current_age
    income = parsed.monthly_income
    expenses = parsed.monthly_expenses
    if current_age is None:
        age = get_float_fact(conn, "profile:current_age")
        current_age = int(age) if age is not None else None
    if income is None:
        income = get_float_fact(conn, "profile:monthly_income")
    if expenses is None:
        expenses = get_float_fact(conn, "profile:monthly_expenses")
    return complete_derived_fields(
        StrategicPlanInput(
            goal_name=parsed.goal_name,
            monthly_income=income,
            monthly_expenses=expenses,
            target_amount=parsed.target_amount,
            current_age=current_age,
            target_age=parsed.target_age,
            months_left=parsed.months_left,
            growth_rate_annual=parsed.growth_rate_annual,
        )
    )


def parse_strategic_plan(message: str) -> StrategicPlanInput:
    text = soft_normalize(message)
    current_age = extract_current_age(text)
    target_age = extract_target_age(text)
    months_left = extract_months_left(text, current_age, target_age)
    return StrategicPlanInput(
        goal_name=extract_goal_name(text),
        monthly_income=extract_monthly_income(text),
        monthly_expenses=extract_monthly_expenses(text),
        target_amount=extract_target_amount(text),
        current_age=current_age,
        target_age=target_age,
        months_left=months_left,
        growth_rate_annual=extract_growth_rate(text),
    )


def merge_with_context(base: StrategicPlanInput | None, fresh: StrategicPlanInput) -> StrategicPlanInput:
    if base is None:
        return complete_derived_fields(fresh)

    if fresh.goal_name and base.goal_name and soft_normalize(fresh.goal_name) != soft_normalize(base.goal_name):
        base = StrategicPlanInput(
            goal_name=None,
            monthly_income=base.monthly_income,
            monthly_expenses=base.monthly_expenses,
            target_amount=None,
            current_age=base.current_age,
            target_age=None,
            months_left=None,
            growth_rate_annual=base.growth_rate_annual,
        )

    merged = StrategicPlanInput(
        goal_name=fresh.goal_name or base.goal_name,
        monthly_income=fresh.monthly_income if fresh.monthly_income is not None else base.monthly_income,
        monthly_expenses=fresh.monthly_expenses if fresh.monthly_expenses is not None else base.monthly_expenses,
        target_amount=fresh.target_amount if fresh.target_amount is not None else base.target_amount,
        current_age=fresh.current_age if fresh.current_age is not None else base.current_age,
        target_age=fresh.target_age if fresh.target_age is not None else base.target_age,
        months_left=fresh.months_left if fresh.months_left is not None else base.months_left,
        growth_rate_annual=fresh.growth_rate_annual if fresh.growth_rate_annual is not None else base.growth_rate_annual,
    )
    return complete_derived_fields(merged)


def complete_derived_fields(plan: StrategicPlanInput) -> StrategicPlanInput:
    months_left = plan.months_left
    if months_left is None and plan.current_age is not None and plan.target_age is not None and plan.target_age > plan.current_age:
        months_left = (plan.target_age - plan.current_age) * 12
    return StrategicPlanInput(
        goal_name=plan.goal_name,
        monthly_income=plan.monthly_income,
        monthly_expenses=plan.monthly_expenses,
        target_amount=plan.target_amount,
        current_age=plan.current_age,
        target_age=plan.target_age,
        months_left=months_left,
        growth_rate_annual=plan.growth_rate_annual,
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
    if parsed.target_age is not None:
        used.append(f"idade-alvo {parsed.target_age} anos")
    if parsed.months_left is not None:
        used.append(f"prazo aproximado {parsed.months_left} meses")
    if used:
        lines.append("Dados usados: " + ", ".join(used) + ".")

    if missing:
        lines.append("Conta exata ainda falta: " + ", ".join(missing) + ". Nao vou inventar esses valores.")
    if parsed.target_age is not None and parsed.current_age is None and parsed.months_left is None:
        lines.append(f"Entendi o alvo: antes dos {parsed.target_age}. Falta sua idade atual para converter isso em meses.")

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
            f"Proximo passo: mande {next_step_text(missing)}. Eu recalculo com numeros fechados.",
        ]
    )
    return " ".join(lines)


def build_actions(parsed: StrategicPlanInput, missing: list[str]) -> list[str]:
    actions = []
    if "preco alvo ou entrada desejada" in missing:
        actions.append("Informar preco alvo ou entrada desejada.")
    if "idade atual" in missing:
        actions.append("Informar idade atual.")
    if "prazo ou idade-alvo" in missing:
        actions.append("Informar prazo real ou idade-alvo.")
    if "gasto mensal medio" in missing:
        actions.append("Informar gasto mensal medio.")
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
        if parsed.target_age is not None and parsed.current_age is None:
            missing.append("idade atual")
        else:
            missing.append("prazo ou idade-alvo")
    return missing


def save_plan_context(conn: Connection, plan: StrategicPlanInput) -> None:
    payload = {
        "goal_name": plan.goal_name,
        "monthly_income": plan.monthly_income,
        "monthly_expenses": plan.monthly_expenses,
        "target_amount": plan.target_amount,
        "current_age": plan.current_age,
        "target_age": plan.target_age,
        "months_left": plan.months_left,
        "growth_rate_annual": plan.growth_rate_annual,
    }
    set_fact(conn, CONTEXT_KEY, json.dumps(payload), "json", 0.95)


def load_plan_context(conn: Connection) -> StrategicPlanInput | None:
    raw = get_fact(conn, CONTEXT_KEY)
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return complete_derived_fields(
        StrategicPlanInput(
            goal_name=payload.get("goal_name"),
            monthly_income=payload.get("monthly_income"),
            monthly_expenses=payload.get("monthly_expenses"),
            target_amount=payload.get("target_amount"),
            current_age=payload.get("current_age"),
            target_age=payload.get("target_age"),
            months_left=payload.get("months_left"),
            growth_rate_annual=payload.get("growth_rate_annual"),
        )
    )


def next_step_text(missing: list[str]) -> str:
    if not missing:
        return "qualquer mudanca de renda ou gasto"
    readable = {
        "renda mensal": "renda mensal",
        "preco alvo ou entrada desejada": "preco alvo ou entrada desejada",
        "idade atual": "idade atual",
        "prazo ou idade-alvo": "prazo real ou idade-alvo",
        "gasto mensal medio": "gasto mensal medio",
    }
    items = [readable.get(item, item) for item in missing]
    return ", ".join(items)


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


def extract_monthly_expenses(text: str) -> float | None:
    patterns = [
        rf"\b(?:gasto|gastos|despesa|despesas|custo|custos)(?:\s+(?:mensal|medio|media|fixo|fixos))*\s*(?:de|sao|e|eh)?\s*({AMOUNT_RE})(?:\s*(mil))?\s*(?:por mes|ao mes|mensal|mes)?",
        rf"\b({AMOUNT_RE})(?:\s*(mil))?\s*(?:de)?\s*(?:gasto|gastos|despesa|despesas|custo|custos)\s*(?:por mes|ao mes|mensal)?\b",
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
        rf"\b(?:meta|objetivo|preco|valor|custa|custando|entrada)\s*(?:de|por|alvo|e|eh)?\s*(?:de|por|alvo|e|eh)?\s*({AMOUNT_RE})(?:\s*(mil))?",
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
    for match in re.finditer(r"\b(?:tenho|idade atual|estou com)\s+(\d{1,2})\s*(?:anos)?\b", text):
        tail = text[match.end() : match.end() + 14].strip()
        if re.match(r"^(?:ate|pra|para)\b", tail):
            continue
        return int(match.group(1))
    return None


def extract_target_age(text: str) -> int | None:
    match = re.search(r"\b(?:antes dos|antes de|ate os|ate meus|ate completar|ate)\s+(\d{1,2})\b", text)
    return int(match.group(1)) if match else None


def extract_months_left(text: str, current_age: int | None, target_age: int | None) -> int | None:
    relative = re.search(r"\b(?:faltam|tenho|tem)\s+(\d{1,2})\s*(anos|ano|meses|mes)\s+(?:ate|pra|para)\b", text)
    if relative:
        value = int(relative.group(1))
        unit = relative.group(2)
        return value * 12 if unit.startswith("ano") else value

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
