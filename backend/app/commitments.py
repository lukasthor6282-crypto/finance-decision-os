from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .categorizer import categorize
from .normalization import normalize_text, parse_amount


@dataclass(frozen=True)
class ParsedCommitment:
    kind: str
    description: str
    amount: float
    category: str
    frequency: str
    installments_remaining: int | None
    installments_total: int | None
    due_day: int | None
    notes: str


def parse_commitment_message(message: str) -> ParsedCommitment | None:
    original = " ".join(message.strip().split())
    text = normalize_commitment_text(original)
    if not text:
        return None

    commitment_terms = [
        "gasto fixo",
        "despesa fixa",
        "custo fixo",
        "conta fixa",
        "parcela",
        "parcelas",
        "mensalidade",
        "assinatura",
        "receita fixa",
        "renda fixa",
        "salario fixo",
    ]
    save_terms = ["guarde", "salve", "guardar", "salvar", "tenho", "vou pagar", "a pagar"]
    if not any(term in text for term in commitment_terms):
        return None
    if not any(term in text for term in save_terms):
        return None

    amount = extract_commitment_amount(original)
    if amount is None or amount <= 0:
        return None

    kind = "income" if any(term in text for term in ["receita fixa", "renda fixa", "salario fixo"]) else "expense"
    description = extract_commitment_description(original, amount)
    signed_amount = amount if kind == "income" else -amount
    category = "Receita" if kind == "income" else categorize(description, signed_amount).category
    installments_remaining = extract_remaining_installments(text)
    installments_total = extract_total_installments(text, installments_remaining)
    due_day = extract_due_day(text)

    return ParsedCommitment(
        kind=kind,
        description=description,
        amount=round(amount, 2),
        category=category,
        frequency="monthly",
        installments_remaining=installments_remaining,
        installments_total=installments_total,
        due_day=due_day,
        notes=f"registrado pelo chat: {original}",
    )


def extract_commitment_amount(message: str) -> float | None:
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


def extract_remaining_installments(text: str) -> int | None:
    patterns = [
        r"(?:mais|faltam|restam|tenho mais)\s*(\d{1,3})\s*parcelas?",
        r"(\d{1,3})\s*parcelas?\s*(?:a pagar|restantes|faltando)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return int(match.group(1))
    return None


def normalize_commitment_text(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-zA-Z0-9\s,.-]", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def extract_total_installments(text: str, remaining: int | None) -> int | None:
    match = re.search(r"\b(?:em|de)\s*(\d{1,3})x\b", text)
    if match:
        return int(match.group(1))
    match = re.search(r"\b(\d{1,3})\s*parcelas?\s*(?:totais|no total)\b", text)
    if match:
        return int(match.group(1))
    return remaining


def extract_due_day(text: str) -> int | None:
    match = re.search(r"(?:dia|vence dia|vencimento dia)\s*(\d{1,2})\b", text)
    if not match:
        return None
    day = int(match.group(1))
    return day if 1 <= day <= 31 else None


def extract_commitment_description(message: str, amount: float) -> str:
    text = normalize_commitment_text(message)
    installment = re.search(r"\bparcela\s+(?:do|da|de)?\s*(?:meu|minha)?\s*([a-z0-9 ]+?)(?:,| tenho| faltam| restam|$)", text)
    if installment:
        subject = clean_commitment_tokens(installment.group(1))
        if subject:
            return f"parcela {subject}"[:120]

    amount_text = str(amount).replace(".", r"[,.]")
    text = re.sub(rf"\br?\$?\s*{amount_text}0?\b", " ", text)
    text = re.sub(r"\b\d+(?:[.,]\d{1,2})?\s*(?:r\$|reais|real)\b", " ", text)
    text = re.sub(r"\b(?:mais|faltam|restam|tenho mais)?\s*\d{1,3}\s*parcelas?.*", " ", text)
    description = clean_commitment_tokens(text)
    if description:
        return description[:120]
    return "Compromisso fixo"


def clean_commitment_tokens(text: str) -> str:
    drop = {
        "eu",
        "guarde",
        "guardar",
        "salve",
        "salvar",
        "essa",
        "informacao",
        "de",
        "do",
        "da",
        "meu",
        "minha",
        "tenho",
        "gasto",
        "fixo",
        "despesa",
        "custo",
        "conta",
        "parcela",
        "parcelas",
        "e",
        "mais",
        "a",
        "pagar",
    }
    tokens = [token for token in re.split(r"\W+", text) if token and token not in drop and not token.isdigit()]
    return " ".join(tokens).strip()
