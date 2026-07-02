from __future__ import annotations

import importlib

from fastapi.testclient import TestClient


def make_client(tmp_path, monkeypatch):
    db_path = tmp_path / "finance-test.db"
    monkeypatch.setenv("FINANCE_DB_PATH", str(db_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("APP_PASSWORD", raising=False)

    import app.db as db

    importlib.reload(db)
    import app.main as main

    importlib.reload(main)
    main.startup()
    client = TestClient(main.app)
    client.post("/api/seed")
    return client


def make_empty_client(tmp_path, monkeypatch):
    db_path = tmp_path / "finance-empty-test.db"
    monkeypatch.setenv("FINANCE_DB_PATH", str(db_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("APP_PASSWORD", raising=False)

    import app.db as db

    importlib.reload(db)
    import app.main as main

    importlib.reload(main)
    main.startup()
    return TestClient(main.app)


def test_dashboard_starts_empty_without_demo_seed(tmp_path, monkeypatch):
    client = make_empty_client(tmp_path, monkeypatch)

    response = client.get("/api/dashboard")

    assert response.status_code == 200
    body = response.json()
    assert body["kpis"]["balance"] == 0
    assert body["recentTransactions"] == []
    assert body["actionPlan"] == []


def test_dashboard_has_decision_data(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)

    response = client.get("/api/dashboard")

    assert response.status_code == 200
    body = response.json()
    assert body["kpis"]["balance"] != 0
    assert body["actionPlan"]
    assert "insights" in body
    assert "recurring" in body


def test_import_deduplicates_csv(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    csv_body = "date,description,amount,account\n2026-07-01,Uber corrida,-42.90,Cartao\n2026-07-01,Uber corrida,-42.90,Cartao\n"

    response = client.post(
        "/api/import",
        files={"file": ("transactions.csv", csv_body.encode("utf-8"), "text/csv")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["imported"] == 1
    assert body["duplicated"] == 1


def test_agent_purchase_decision(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)

    response = client.post("/api/agent/chat", json={"message": "posso comprar algo de R$ 900 hoje?"})

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "purchase_decision"
    assert body["actions"]
    assert body["data"]["amount"] == 900


def test_agent_records_income_and_sums_repeated_entries(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    start_balance = client.get("/api/dashboard").json()["kpis"]["balance"]

    first = client.post("/api/agent/chat", json={"message": "hoje eu ganhei 250R$"})
    second = client.post("/api/agent/chat", json={"message": "hoje eu ganhei 250R$"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["intent"] == "record_transaction"
    assert second.json()["intent"] == "record_transaction"
    assert second.json()["data"]["duplicated"] is False

    end_balance = client.get("/api/dashboard").json()["kpis"]["balance"]
    assert round(end_balance - start_balance, 2) == 500


def test_agent_records_expense_and_learns_pattern(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)

    response = client.post("/api/agent/chat", json={"message": "gastei R$ 80 no mercado hoje"})

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "record_transaction"
    assert body["data"]["amount"] == -80
    assert body["data"]["category"] == "Mercado"

    transactions = client.get("/api/transactions", params={"search": "mercado", "limit": 10}).json()
    assert any(tx["amount"] == -80 and tx["source"] == "agent" for tx in transactions)

    patterns = client.get("/api/patterns").json()
    assert any(pattern["pattern"] == "mercado" and pattern["category"] == "Mercado" for pattern in patterns)


def test_goals_crud(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)

    created = client.post(
        "/api/goals",
        json={"name": "Notebook", "target_amount": 12000, "current_amount": 1000, "priority": "alta"},
    )
    assert created.status_code == 200
    goal_id = created.json()["id"]

    updated = client.patch(f"/api/goals/{goal_id}", json={"current_amount": 2500})
    assert updated.status_code == 200

    goals = client.get("/api/goals").json()
    assert any(goal["id"] == goal_id and goal["current_amount"] == 2500 for goal in goals)
