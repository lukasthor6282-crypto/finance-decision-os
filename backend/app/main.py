from __future__ import annotations

import base64
import csv
import io
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from .agent import answer
from .analytics import get_transactions, scenario, summarize
from .db import connect, init_db, is_postgres
from .normalization import parse_amount, parse_date
from .repository import (
    create_category_rule,
    delete_category_rule,
    insert_transaction,
    list_budgets,
    list_category_rules,
    list_facts,
    list_goals,
    list_learned_patterns,
    list_work_sessions,
    reprocess_transactions,
    update_transaction_category,
)
from .schemas import AgentRequest, AgentResponse, BudgetIn, CategoryRuleIn, GoalIn, GoalPatch, ScenarioRequest, TransactionIn, TransactionPatch
from .seed import seed_demo


def startup() -> None:
    init_db()
    if os.getenv("SEED_DEMO", "").lower() == "true":
        with connect() as conn:
            seed_demo(conn)


@asynccontextmanager
async def lifespan(app: FastAPI):
    startup()
    yield


DEFAULT_ALLOWED_ORIGINS = ",".join(
    [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://finance-decision-os.pages.dev",
    ]
)
allowed_origins = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", DEFAULT_ALLOWED_ORIGINS).split(",")
    if origin.strip()
]

app = FastAPI(title="Finance Decision OS", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=r"https://([a-z0-9-]+\.)?finance-decision-os\.pages\.dev",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def optional_basic_auth(request: Request, call_next):
    password = os.getenv("APP_PASSWORD")
    if not password or request.url.path == "/api/health":
        return await call_next(request)

    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() == "basic" and token:
        try:
            decoded = base64.b64decode(token).decode("utf-8")
            username, _, received_password = decoded.partition(":")
        except Exception:
            username, received_password = "", ""
        expected_user = os.getenv("APP_USER", "lukas")
        if secrets.compare_digest(username, expected_user) and secrets.compare_digest(received_password, password):
            return await call_next(request)

    return Response(
        "autenticacao necessaria",
        status_code=401,
        headers={"WWW-Authenticate": 'Basic realm="Finance Decision OS"'},
    )


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/summary")
def api_summary(month: str | None = None) -> dict:
    with connect() as conn:
        return summarize(conn, month=month)


@app.get("/api/dashboard")
def api_dashboard(month: str | None = None) -> dict:
    with connect() as conn:
        return summarize(conn, month=month)


@app.get("/api/insights")
def api_insights(month: str | None = None) -> list[dict]:
    with connect() as conn:
        return summarize(conn, month=month)["insights"]


@app.get("/api/recommendations")
def api_recommendations(month: str | None = None) -> list[dict]:
    with connect() as conn:
        return summarize(conn, month=month)["actionPlan"]


@app.get("/api/transactions")
def api_transactions(
    limit: int = Query(100, ge=1, le=2000),
    start: str | None = None,
    end: str | None = None,
    category: str | None = None,
    account: str | None = None,
    search: str | None = None,
) -> list[dict]:
    with connect() as conn:
        return get_transactions(conn, limit, start, end, category, account, search)


@app.post("/api/transactions")
def api_create_transaction(payload: TransactionIn) -> dict:
    with connect() as conn:
        result = insert_transaction(
            conn,
            {
                "date": parse_date(payload.date),
                "description": payload.description.strip(),
                "amount": payload.amount,
                "category": payload.category,
                "account": payload.account,
                "notes": payload.notes,
                "transaction_type": payload.transaction_type,
                "is_internal": payload.is_internal,
            },
            source="manual",
        )
        return {"id": result.id, "category": result.category, "duplicated": result.duplicated}


@app.delete("/api/transactions/{transaction_id}")
def api_delete_transaction(transaction_id: int) -> dict:
    with connect() as conn:
        cursor = conn.execute("DELETE FROM transactions WHERE id = ?", (transaction_id,))
        if cursor.rowcount == 0:
            raise HTTPException(404, "transacao nao encontrada")
        return {"ok": True}


@app.patch("/api/transactions/{transaction_id}")
def api_update_transaction(transaction_id: int, payload: TransactionPatch) -> dict:
    with connect() as conn:
        result = update_transaction_category(
            conn,
            transaction_id,
            payload.category,
            payload.transaction_type,
            payload.is_internal,
        )
        if not result:
            raise HTTPException(404, "transacao nao encontrada")
        return result


@app.post("/api/transactions/reprocess")
def api_reprocess_transactions(include_locked: bool = False) -> dict:
    with connect() as conn:
        return reprocess_transactions(conn, include_locked)


@app.get("/api/budgets")
def api_budgets() -> list[dict]:
    with connect() as conn:
        return list_budgets(conn)


@app.post("/api/budgets")
def api_budget(payload: BudgetIn) -> dict:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO budgets (category, monthly_limit)
            VALUES (?, ?)
            ON CONFLICT(category) DO UPDATE SET monthly_limit = excluded.monthly_limit
            """,
            (payload.category, payload.monthly_limit),
        )
        return {"ok": True}


@app.get("/api/goals")
def api_goals() -> list[dict]:
    with connect() as conn:
        return list_goals(conn)


@app.post("/api/goals")
def api_create_goal(payload: GoalIn) -> dict:
    with connect() as conn:
        returning = " RETURNING id" if is_postgres(conn) else ""
        cursor = conn.execute(
            f"""
            INSERT INTO goals (name, target_amount, current_amount, due_date, priority)
            VALUES (?, ?, ?, ?, ?)
            {returning}
            """,
            (payload.name, payload.target_amount, payload.current_amount, payload.due_date, payload.priority),
        )
        goal_id = cursor.fetchone()["id"] if is_postgres(conn) else cursor.lastrowid
        return {"id": goal_id, "ok": True}


@app.patch("/api/goals/{goal_id}")
def api_update_goal(goal_id: int, payload: GoalPatch) -> dict:
    data = payload.model_dump(exclude_unset=True)
    if not data:
        return {"ok": True}
    allowed = {"name", "target_amount", "current_amount", "due_date", "priority"}
    updates = [key for key in data if key in allowed]
    sql = ", ".join(f"{key} = ?" for key in updates)
    values = [data[key] for key in updates] + [goal_id]
    with connect() as conn:
        cursor = conn.execute(f"UPDATE goals SET {sql} WHERE id = ?", values)
        if cursor.rowcount == 0:
            raise HTTPException(404, "meta nao encontrada")
        return {"ok": True}


@app.delete("/api/goals/{goal_id}")
def api_delete_goal(goal_id: int) -> dict:
    with connect() as conn:
        cursor = conn.execute("DELETE FROM goals WHERE id = ?", (goal_id,))
        if cursor.rowcount == 0:
            raise HTTPException(404, "meta nao encontrada")
        return {"ok": True}


@app.get("/api/categories")
def api_categories() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT category, COUNT(*) AS transactions, SUM(CASE WHEN amount < 0 THEN ABS(amount) ELSE 0 END) AS spend
            FROM transactions
            WHERE transaction_type NOT IN ('transfer', 'card_payment', 'investment')
              AND amount < 0
            GROUP BY category
            ORDER BY spend DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]


@app.get("/api/category-rules")
def api_category_rules() -> list[dict]:
    with connect() as conn:
        return list_category_rules(conn)


@app.post("/api/category-rules")
def api_create_category_rule(payload: CategoryRuleIn) -> dict:
    with connect() as conn:
        try:
            return create_category_rule(conn, payload.model_dump())
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc


@app.delete("/api/category-rules/{rule_id}")
def api_delete_category_rule(rule_id: int) -> dict:
    with connect() as conn:
        if not delete_category_rule(conn, rule_id):
            raise HTTPException(404, "regra nao encontrada")
        return {"ok": True}


@app.get("/api/patterns")
def api_patterns() -> list[dict]:
    with connect() as conn:
        return list_learned_patterns(conn)


@app.get("/api/facts")
def api_facts() -> list[dict]:
    with connect() as conn:
        return list_facts(conn)


@app.get("/api/work-sessions")
def api_work_sessions(limit: int = Query(100, ge=1, le=500)) -> list[dict]:
    with connect() as conn:
        return list_work_sessions(conn, limit)


@app.post("/api/import")
async def api_import(file: UploadFile = File(...)) -> dict:
    content = await file.read()
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(400, "CSV vazio ou sem cabeçalho")

    imported = 0
    duplicated = 0
    skipped = 0
    with connect() as conn:
        for row in reader:
            try:
                tx = normalize_row(row)
            except ValueError:
                skipped += 1
                continue
            result = insert_transaction(conn, tx, source="csv")
            if result.duplicated:
                duplicated += 1
            else:
                imported += 1
    return {"imported": imported, "duplicated": duplicated, "skipped": skipped}


@app.post("/api/agent/chat", response_model=AgentResponse)
def api_agent(payload: AgentRequest) -> dict:
    with connect() as conn:
        conn.execute("INSERT INTO chat_messages (role, content) VALUES ('user', ?)", (payload.message,))
        result = answer(conn, payload.message)
        conn.execute("INSERT INTO chat_messages (role, content) VALUES ('assistant', ?)", (result["answer"],))
        return result


@app.post("/api/scenario")
def api_scenario(payload: ScenarioRequest) -> dict:
    with connect() as conn:
        return scenario(conn, payload.description, payload.amount, payload.category)


@app.post("/api/seed")
def api_seed() -> dict:
    with connect() as conn:
        seed_demo(conn)
    return {"ok": True}


@app.delete("/api/admin/demo-data")
def api_delete_demo_data() -> dict:
    with connect() as conn:
        deleted = {}
        for table in ("transactions", "budgets", "goals", "chat_messages", "learned_patterns", "user_facts", "work_sessions"):
            cursor = conn.execute(f"DELETE FROM {table}")
            deleted[table] = cursor.rowcount
        return {"ok": True, "deleted": deleted}


def normalize_row(row: dict) -> dict:
    lowered = {key.strip().lower(): value for key, value in row.items() if key}
    date_value = pick(lowered, ["date", "data", "posted_at", "posted date", "dt"])
    description = pick(lowered, ["description", "descrição", "descricao", "memo", "name", "merchant", "histórico", "historico"])
    amount_value = pick(lowered, ["amount", "valor", "value", "total"])
    category = pick(lowered, ["category", "categoria"], required=False)
    account = pick(lowered, ["account", "conta", "bank"], required=False) or "Principal"
    return {
        "date": parse_date(date_value),
        "description": description.strip(),
        "amount": parse_amount(amount_value),
        "category": category.strip() if category else None,
        "account": account.strip() or "Principal",
    }


def pick(row: dict, keys: list[str], required: bool = True) -> str:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    if required:
        raise ValueError(f"missing {keys[0]}")
    return ""


def mount_static_app() -> None:
    static_dir = Path(os.getenv("STATIC_DIR", Path(__file__).resolve().parent / "static"))
    index_file = static_dir / "index.html"
    assets_dir = static_dir / "assets"
    if not index_file.exists():
        return
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/")
    def app_index() -> FileResponse:
        return FileResponse(index_file)

    @app.get("/{full_path:path}")
    def app_fallback(full_path: str) -> FileResponse:
        if full_path.startswith("api/"):
            raise HTTPException(404, "rota nao encontrada")
        return FileResponse(index_file)


mount_static_app()
