from __future__ import annotations

import hashlib
import re
import unicodedata
from sqlite3 import Connection

from .normalization import normalize_text, parse_amount
from .repository import create_category_rule, list_facts, set_fact


TRAINING_TERMS = ("lembre", "guarde", "salve", "aprenda", "considere", "a partir de agora")


def handle_training_message(conn: Connection, message: str) -> dict | None:
    text = soft_normalize(message)
    if asks_memory(text):
        return memory_answer(conn)
    if not any(term in text for term in TRAINING_TERMS):
        return None

    category_rule = parse_category_training(text)
    if category_rule:
        rule = create_category_rule(conn, category_rule)
        return response(
            "train_assistant",
            f"Aprendi regra: quando aparecer '{rule['pattern']}', categoria {rule['category']}. Nao alterei saldo.",
            ["Use Reprocessar se quiser aplicar em lancamentos antigos.", "Voce pode apagar regra na aba Regras."],
            0.94,
            {"trainingType": "category_rule", "rule": rule},
        )

    facts = parse_profile_facts(message, text)
    if not facts:
        facts = [generic_memory(message)]

    for fact in facts:
        set_fact(conn, fact["key"], fact["value"], fact["type"], fact["confidence"])

    readable = "; ".join(fact["label"] for fact in facts)
    return response(
        "train_assistant",
        f"Memoria salva: {readable}. Nao alterei saldo nem criei lancamento.",
        ["Vou usar isso em planos, decisoes de compra e respostas futuras.", "Para ver memoria, pergunte: o que voce sabe sobre mim?"],
        0.92,
        {"trainingType": "profile_facts", "facts": facts},
    )


def parse_profile_facts(original: str, text: str) -> list[dict]:
    facts = []
    income = extract_value_near(text, ["renda", "ganho", "recebo", "salario", "faturamento"])
    if income and income >= 50:
        facts.append(fact("profile:monthly_income", f"{income:.2f}", "money_per_month", f"renda media mensal {money_br(income)}", 0.92))

    expenses = extract_value_near(text, ["gasto mensal", "gastos mensais", "despesa mensal", "despesas mensais", "custo mensal"])
    if expenses and expenses >= 0:
        facts.append(fact("profile:monthly_expenses", f"{expenses:.2f}", "money_per_month", f"gasto mensal medio {money_br(expenses)}", 0.9))

    age = extract_age(text)
    if age:
        facts.append(fact("profile:current_age", str(age), "integer", f"idade atual {age} anos", 0.92))

    payday = extract_payday(text)
    if payday:
        facts.append(fact("profile:payday", str(payday), "day_of_month", f"dia de recebimento {payday}", 0.86))

    risk = extract_risk_profile(text)
    if risk:
        facts.append(fact("profile:risk_profile", risk, "preference", f"perfil {risk}", 0.86))

    priority = extract_priority(original, text)
    if priority:
        facts.append(fact("profile:priority", priority, "preference", f"prioridade: {priority}", 0.86))

    return dedupe_facts(facts)


def parse_category_training(text: str) -> dict | None:
    category_match = re.search(r"(?:categoria|categorize|classifique|conta como)\s+([a-z0-9 ]{3,40})", text)
    if not category_match:
        category_match = re.search(r"(?:como|em)\s+(alimentacao|supermercado|transporte|moradia|assinaturas|saude|educacao|receita|transferencia|cartao|investimentos|outros)\b", text)
    pattern_match = re.search(r"(?:quando aparecer|quando eu falar|se aparecer|padrao|termo)\s+['\"]?([a-z0-9 ]{2,60})['\"]?", text)
    if not pattern_match:
        pattern_match = re.search(r"aprenda\s+['\"]?([a-z0-9 ]{2,60})['\"]?\s+(?:como|em|categoria)", text)
    if not category_match or not pattern_match:
        return None

    category = normalize_category(category_match.group(1))
    pattern = cleanup_pattern(pattern_match.group(1))
    if len(pattern) < 2 or len(category) < 2:
        return None
    tx_type = "income" if category == "Receita" else "transfer" if category == "Transferencia" else "card_payment" if category == "Cartao" else "investment" if category == "Investimentos" else "expense"
    return {"pattern": pattern, "category": category, "transaction_type": tx_type, "is_internal": tx_type in {"transfer", "card_payment", "investment"}, "priority": 150}


def memory_answer(conn: Connection) -> dict:
    facts = list_facts(conn)
    profile = [item for item in facts if item["key"].startswith("profile:")][:12]
    generic = [item for item in facts if item["key"].startswith("memory:")][:5]
    if not profile and not generic:
        return response(
            "memory_profile",
            "Ainda nao tenho memorias pessoais salvas. Voce pode dizer: lembre que minha renda media e R$ 1200.",
            ["Ensinar renda media.", "Ensinar idade.", "Ensinar prioridade/meta."],
            0.9,
            {"facts": []},
        )
    lines = [format_fact(item) for item in profile + generic]
    return response(
        "memory_profile",
        "Memorias salvas: " + "; ".join(lines) + ".",
        ["Uso isso em planos e decisoes.", "Dados financeiros reais continuam vindo do banco."],
        0.92,
        {"facts": profile + generic},
    )


def asks_memory(text: str) -> bool:
    return any(phrase in text for phrase in ["o que voce sabe sobre mim", "quais memorias", "minha memoria", "o que aprendeu sobre mim"])


def extract_value_near(text: str, terms: list[str]) -> float | None:
    for term in terms:
        match = re.search(rf"{re.escape(term)}(?:\s+(?:media|medio|mensal|por mes|ao mes|e|eh|de|é))*\s*(?:r\$\s*)?({NUMBER_RE})(?:\s*(mil))?", text)
        if match:
            amount = parse_training_amount(match.group(1), match.group(2))
            if amount is not None:
                return amount
    return None


def parse_training_amount(value: str, suffix: str | None = None) -> float | None:
    try:
        amount = abs(parse_amount(value))
    except ValueError:
        return None
    if suffix == "mil":
        amount *= 1000
    return amount


def extract_age(text: str) -> int | None:
    match = re.search(r"\b(?:tenho|idade atual|estou com)\s+(\d{1,2})\s*(?:anos)?\b", text)
    if not match:
        return None
    age = int(match.group(1))
    return age if 10 <= age <= 99 else None


def extract_payday(text: str) -> int | None:
    match = re.search(r"\b(?:recebo|salario cai|pagamento cai|dia de pagamento)\s+(?:todo dia|dia)?\s*(\d{1,2})\b", text)
    if not match:
        return None
    day = int(match.group(1))
    return day if 1 <= day <= 31 else None


def extract_risk_profile(text: str) -> str | None:
    if any(word in text for word in ["conservador", "cauteloso", "nao gosto de risco", "sem risco"]):
        return "conservador"
    if any(word in text for word in ["agressivo", "aceito risco", "arriscado"]):
        return "agressivo"
    if "moderado" in text:
        return "moderado"
    return None


def extract_priority(original: str, text: str) -> str | None:
    match = re.search(r"\b(?:minha prioridade|meu foco|objetivo principal|meta principal)\s+(?:e|eh|é|será|sera)?\s*(.+)$", soft_normalize_keep(original))
    if not match:
        return None
    priority = re.sub(r"\b(lembre|guarde|salve|aprenda|considere|que)\b", " ", match.group(1), flags=re.IGNORECASE)
    priority = re.sub(r"\s+", " ", priority).strip(" .,;:-")
    return priority[:140] if priority else None


def generic_memory(message: str) -> dict:
    cleaned = re.sub(r"\b(lembre|guarde|salve|aprenda|considere|que|essa informacao|esta informacao)\b", " ", message, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,;:-")
    key = "memory:" + hashlib.sha1(normalize_text(cleaned).encode("utf-8")).hexdigest()[:12]
    return fact(key, cleaned[:240] or message[:240], "text", cleaned[:120] or "memoria pessoal", 0.72)


def fact(key: str, value: str, value_type: str, label: str, confidence: float) -> dict:
    return {"key": key, "value": value, "type": value_type, "label": label, "confidence": confidence}


def dedupe_facts(facts: list[dict]) -> list[dict]:
    seen = set()
    result = []
    for item in facts:
        if item["key"] in seen:
            continue
        seen.add(item["key"])
        result.append(item)
    return result


def format_fact(item: dict) -> str:
    key = item["key"].replace("profile:", "")
    return f"{key}={item['value']}"


def normalize_category(value: str) -> str:
    mapping = {
        "alimentacao": "Alimentacao",
        "supermercado": "Supermercado",
        "transporte": "Transporte",
        "moradia": "Moradia",
        "assinaturas": "Assinaturas",
        "saude": "Saude",
        "educacao": "Educacao",
        "receita": "Receita",
        "transferencia": "Transferencia",
        "cartao": "Cartao",
        "investimentos": "Investimentos",
        "outros": "Outros",
    }
    normalized = normalize_text(value)
    return mapping.get(normalized, value.strip().title())


def cleanup_pattern(value: str) -> str:
    clean = re.sub(r"\b(como|em|categoria|classifique|conta)\b.*$", " ", value)
    return normalize_text(clean).strip()


def soft_normalize(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("r $", "r$")
    text = re.sub(r"[()?!;:,]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def soft_normalize_keep(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text).strip()


def money_br(value: float) -> str:
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def response(intent: str, answer: str, actions: list[str], confidence: float, data: dict | list | None = None) -> dict:
    return {
        "answer": answer,
        "actions": actions,
        "confidence": confidence,
        "mode": "training",
        "intent": intent,
        "data": data,
    }


NUMBER_RE = r"\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:[.,]\d{1,2})?"
