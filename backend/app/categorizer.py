from __future__ import annotations

import re
from dataclasses import dataclass

from .normalization import normalize_text


@dataclass(frozen=True)
class CategoryRule:
    category: str
    transaction_type: str
    confidence: float
    patterns: tuple[str, ...]


@dataclass(frozen=True)
class Categorization:
    category: str
    transaction_type: str
    confidence: float
    reason: str
    is_internal: bool = False


RULES: tuple[CategoryRule, ...] = (
    CategoryRule("Transferencia", "transfer", 0.98, ("transferencia propria", "entre contas", "mesmo titular", "minha conta", "conta propria")),
    CategoryRule("Cartao", "card_payment", 0.98, ("pagamento fatura", "fatura cartao", "pagamento cartao", "cartao credito", "cartao de credito")),
    CategoryRule("Estorno", "refund", 0.96, ("estorno", "reembolso", "devolucao", "chargeback")),
    CategoryRule("Receita", "income", 0.95, ("salario", "pix recebido", "recebi pix", "transferencia recebida", "rendimento", "provento", "freelance", "receita", "renda")),
    CategoryRule("Supermercado", "expense", 0.9, ("mercado", "supermercado", "atacadao", "atacado", "hortifruti", "acougue")),
    CategoryRule("Alimentacao", "expense", 0.88, ("ifood", "uber eats", "ubereats", "restaurante", "padaria", "lanchonete", "almoco", "jantar", "delivery", "bar")),
    CategoryRule("Transporte", "expense", 0.86, ("uber", "99", "onibus", "metro", "combustivel", "posto", "estacionamento", "gasolina")),
    CategoryRule("Moradia", "expense", 0.92, ("aluguel", "condominio", "energia", "luz", "agua", "internet", "gas")),
    CategoryRule("Assinaturas", "expense", 0.84, ("netflix", "spotify", "prime", "amazon prime", "disney", "hbo", "icloud", "assinatura")),
    CategoryRule("Saude", "expense", 0.88, ("farmacia", "drogaria", "medico", "consulta", "laboratorio", "exame", "dentista")),
    CategoryRule("Educacao", "expense", 0.86, ("faculdade", "curso", "livro", "escola", "educacao")),
    CategoryRule("Viagem", "expense", 0.82, ("viagem", "hotel", "airbnb", "passagem", "latam", "gol", "azul")),
    CategoryRule("Dividas", "expense", 0.84, ("emprestimo", "financiamento", "juros")),
    CategoryRule("Investimentos", "investment", 0.9, ("tesouro", "investimento", "corretora", "aporte", "cdb", "selic", "xp", "rico")),
)


INTERNAL_TYPES = {"transfer", "card_payment", "investment"}


def categorize(description: str, amount: float) -> Categorization:
    normalized = normalize_text(description)
    for rule in RULES:
        for pattern in rule.patterns:
            if phrase_match(normalized, pattern):
                tx_type = infer_signed_type(rule.transaction_type, amount)
                return Categorization(
                    category=rule.category,
                    transaction_type=tx_type,
                    confidence=rule.confidence,
                    reason=f"rule:{pattern}",
                    is_internal=tx_type in INTERNAL_TYPES,
                )

    if amount > 0:
        return Categorization("Receita", "income", 0.72, "positive_amount")
    if amount < 0:
        return Categorization("Outros", "expense", 0.42, "fallback_expense")
    return Categorization("Outros", "unknown", 0.2, "zero_amount")


def infer_signed_type(transaction_type: str, amount: float) -> str:
    if transaction_type == "refund" and amount < 0:
        return "expense"
    if transaction_type == "income" and amount < 0:
        return "expense"
    return transaction_type


def phrase_match(text: str, phrase: str) -> bool:
    phrase = normalize_text(phrase)
    if " " in phrase:
        return phrase in text
    return re.search(rf"\b{re.escape(phrase)}\b", text) is not None


def editable_rules() -> list[dict]:
    return [
        {
            "category": rule.category,
            "transactionType": rule.transaction_type,
            "confidence": rule.confidence,
            "patterns": list(rule.patterns),
        }
        for rule in RULES
    ]
