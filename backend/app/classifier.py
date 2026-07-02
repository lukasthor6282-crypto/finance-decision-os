from __future__ import annotations

from dataclasses import dataclass

from .categorizer import categorize


@dataclass(frozen=True)
class CategoryGuess:
    category: str
    confidence: float
    reason: str


def classify(description: str, amount: float) -> CategoryGuess:
    result = categorize(description, amount)
    return CategoryGuess(result.category, result.confidence, result.reason)
