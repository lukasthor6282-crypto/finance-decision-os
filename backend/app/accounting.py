from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

from .classifier import classify
from .normalization import normalize_text, parse_amount


INCOME_WORDS = {
    "ganhei",
    "recebi",
    "entrou",
    "caiu",
    "faturei",
    "vendi",
    "salario",
    "renda",
    "pix recebido",
    "me pagaram",
}
EXPENSE_WORDS = {
    "gastei",
    "paguei",
    "comprei",
    "saiu",
    "despesa",
    "custo",
    "debito",
    "pix enviado",
}
FUTURE_WORDS = {"vou", "pretendo", "quero", "posso", "devo", "vale"}

CATEGORY_HINTS = [
    ("Mercado", {"mercado", "supermercado", "atacadao", "padaria", "hortifruti"}),
    ("Alimentacao", {"ifood", "restaurante", "almoco", "jantar", "lanche", "cafe", "delivery"}),
    ("Transporte", {"uber", "99", "onibus", "metro", "gasolina", "posto", "combustivel"}),
    ("Moradia", {"aluguel", "condominio", "luz", "energia", "agua", "internet", "gas"}),
    ("Assinaturas", {"netflix", "spotify", "prime", "disney", "hbo", "assinatura"}),
    ("Saude", {"farmacia", "medico", "consulta", "exame", "dentista"}),
    ("Educacao", {"curso", "faculdade", "escola", "livro"}),
    ("Investimentos", {"aporte", "tesouro", "investimento", "corretora"}),
]


@dataclass(frozen=True)
class ParsedTransaction:
    date: str
    description: str
    amount: float
    category: str
    account: str
    notes: str
    pattern: str


def parse_transaction_message(message: str) -> ParsedTransaction | None:
    clean = " ".join(message.strip().split())
    normalized = normalize_text(clean)
    if not normalized:
        return None

    amount = extract_amount(clean)
    if amount is None:
        return None

    if any(word in normalized.split() for word in FUTURE_WORDS):
        if not has_bookkeeping_verb(normalized):
            return None

    direction = detect_direction(normalized)
    if not direction:
        return None

    signed_amount = abs(amount) if direction == "income" else -abs(amount)
    description = extract_description(clean, normalized, direction)
    category = infer_category(description, normalized, signed_amount)
    account = infer_account(normalized)
    tx_date = infer_date(normalized)
    pattern = normalize_text(description)

    return ParsedTransaction(
        date=tx_date,
        description=description,
        amount=signed_amount,
        category=category,
        account=account,
        notes=f"registrado pelo chat: {clean}",
        pattern=pattern,
    )


def has_bookkeeping_verb(normalized: str) -> bool:
    return any(word in normalized for word in INCOME_WORDS | EXPENSE_WORDS)


def detect_direction(normalized: str) -> str | None:
    if any(word in normalized for word in INCOME_WORDS):
        return "income"
    if any(word in normalized for word in EXPENSE_WORDS):
        return "expense"
    return None


def extract_amount(message: str) -> float | None:
    patterns = [
        r"r\$\s*([+-]?\d+(?:[.,]\d{1,2})?)",
        r"([+-]?\d+(?:[.,]\d{1,2})?)\s*(?:r\$|reais|real)",
        r"\b([+-]?\d{2,}(?:[.,]\d{1,2})?)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if not match:
            continue
        try:
            return parse_amount(match.group(1))
        except ValueError:
            continue
    return None


def infer_date(normalized: str) -> str:
    today = date.today()
    if "ontem" in normalized:
        return (today - timedelta(days=1)).isoformat()
    if "anteontem" in normalized:
        return (today - timedelta(days=2)).isoformat()
    match = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b", normalized)
    if match:
        day = int(match.group(1))
        month = int(match.group(2))
        year = int(match.group(3) or today.year)
        if year < 100:
            year += 2000
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            return today.isoformat()
    return today.isoformat()


def infer_account(normalized: str) -> str:
    if "cartao" in normalized or "credito" in normalized:
        return "Cartao"
    if "pix" in normalized:
        return "Pix"
    if "dinheiro" in normalized:
        return "Dinheiro"
    if "conta corrente" in normalized or "banco" in normalized:
        return "Conta Corrente"
    return "Principal"


def infer_category(description: str, normalized: str, amount: float) -> str:
    if amount > 0:
        return "Renda"
    tokens = set(normalized.split())
    for category, hints in CATEGORY_HINTS:
        if tokens & hints:
            return category
    return classify(description, amount).category


def extract_description(message: str, normalized: str, direction: str) -> str:
    without_amount = re.sub(r"r\$\s*\d+(?:[.,]\d{1,2})?", " ", message, flags=re.IGNORECASE)
    without_amount = re.sub(r"\d+(?:[.,]\d{1,2})?\s*(?:r\$|reais|real)", " ", without_amount, flags=re.IGNORECASE)
    without_amount = re.sub(r"\b\d{2,}(?:[.,]\d{1,2})?\b", " ", without_amount)
    lowered = normalize_text(without_amount)
    words_to_drop = INCOME_WORDS | EXPENSE_WORDS | {"hoje", "ontem", "anteontem", "eu", "de", "do", "da", "no", "na", "em", "com", "para", "por", "r"}
    tokens = [token for token in lowered.split() if token not in words_to_drop]
    text = " ".join(tokens).strip()

    if text:
        return text[:120]
    if direction == "income":
        return "Receita informada"
    return "Despesa informada"
