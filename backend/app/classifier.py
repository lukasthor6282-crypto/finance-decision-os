from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class CategoryGuess:
    category: str
    confidence: float
    reason: str


RULES: list[tuple[str, str, float]] = [
    (r"\b(sal[aá]rio|salary|payroll|provento|pix recebido|rendimento)\b", "Renda", 0.96),
    (r"\b(mercado|supermercado|grocery|atacad|hortifruti|padaria)\b", "Mercado", 0.9),
    (r"\b(ifood|ubereats|restaurante|lanchonete|caf[eé]|bar\b|delivery)\b", "Alimentação", 0.88),
    (r"\b(uber|99|metro|ônibus|onibus|combust[ií]vel|posto|estacionamento)\b", "Transporte", 0.86),
    (r"\b(aluguel|condom[ií]nio|energia|luz|água|agua|internet|g[aá]s)\b", "Moradia", 0.92),
    (r"\b(netflix|spotify|prime|disney|hbo|assinatura|icloud|google storage)\b", "Assinaturas", 0.84),
    (r"\b(farm[aá]cia|m[eé]dico|consulta|laborat[oó]rio|sa[uú]de|dentista)\b", "Saúde", 0.88),
    (r"\b(faculdade|curso|livro|escola|educa[cç][aã]o)\b", "Educação", 0.86),
    (r"\b(viagem|hotel|airbnb|passagem|latam|gol|azul)\b", "Viagem", 0.82),
    (r"\b(cart[aã]o|loan|empr[eé]stimo|financiamento|juros)\b", "Dívidas", 0.84),
    (r"\b(tesouro|invest|corretora|xp|nubank investimento|aporte)\b", "Investimentos", 0.9),
]


def classify(description: str, amount: float) -> CategoryGuess:
    text = description.lower().strip()
    if amount > 0:
        return CategoryGuess("Renda", 0.9, "entrada positiva")

    for pattern, category, confidence in RULES:
        if re.search(pattern, text):
            return CategoryGuess(category, confidence, f"regra: {pattern}")

    return CategoryGuess("Outros", 0.42, "sem regra forte")
