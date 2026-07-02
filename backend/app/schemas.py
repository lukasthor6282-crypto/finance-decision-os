from __future__ import annotations

from pydantic import BaseModel, Field


class TransactionIn(BaseModel):
    date: str
    description: str
    amount: float
    category: str | None = None
    account: str = "Principal"
    notes: str | None = None


class TransactionOut(TransactionIn):
    id: int
    category: str
    source: str


class BudgetIn(BaseModel):
    category: str
    monthly_limit: float = Field(gt=0)


class GoalIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    target_amount: float = Field(gt=0)
    current_amount: float = Field(default=0, ge=0)
    due_date: str | None = None
    priority: str = "media"


class GoalPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    target_amount: float | None = Field(default=None, gt=0)
    current_amount: float | None = Field(default=None, ge=0)
    due_date: str | None = None
    priority: str | None = None


class AgentRequest(BaseModel):
    message: str = Field(min_length=2, max_length=1200)


class AgentResponse(BaseModel):
    answer: str
    actions: list[str]
    confidence: float
    mode: str
    intent: str | None = None
    data: dict | list | None = None


class ScenarioRequest(BaseModel):
    description: str = "Compra planejada"
    amount: float = Field(gt=0)
    category: str | None = None
