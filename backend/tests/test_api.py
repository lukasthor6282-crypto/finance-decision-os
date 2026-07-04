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


def test_import_preview_and_manual_mapping_for_custom_statement(tmp_path, monkeypatch):
    client = make_empty_client(tmp_path, monkeypatch)
    csv_body = "Dia;Historico;Quantia;Banco;Natureza;Forma\n01/07/2026;Padaria bairro;18,50;Nubank;Despesa;Debito\n02/07/2026;Pix recebido cliente;250,00;Nubank;Receita;Pix\n"

    preview = client.post(
        "/api/import/preview",
        files={"file": ("extrato.csv", csv_body.encode("utf-8"), "text/csv")},
    )

    assert preview.status_code == 200
    assert "Dia" in preview.json()["columns"]

    response = client.post(
        "/api/import",
        data={
            "date_column": "Dia",
            "description_column": "Historico",
            "amount_column": "Quantia",
            "account_column": "Banco",
            "transaction_type_column": "Natureza",
            "payment_method_column": "Forma",
        },
        files={"file": ("extrato.csv", csv_body.encode("utf-8"), "text/csv")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["imported"] == 2
    assert body["skipped"] == 0

    summary = client.get("/api/dashboard", params={"month": "2026-07"}).json()
    transactions = client.get("/api/transactions").json()

    assert summary["kpis"]["income"] == 250
    assert summary["kpis"]["expenses"] == 18.5
    assert any(tx["description"] == "Padaria bairro" and tx["amount"] == -18.5 for tx in transactions)
    assert any("forma_pagamento: Debito" in (tx.get("notes") or "") for tx in transactions)


def test_agent_purchase_decision(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)

    response = client.post("/api/agent/chat", json={"message": "posso comprar algo de R$ 900 hoje?"})

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "purchase_decision"
    assert body["actions"]
    assert body["data"]["amount"] == 900


def test_simple_finance_records_invoice_and_partial_payment(tmp_path, monkeypatch):
    client = make_empty_client(tmp_path, monkeypatch)

    invoice = client.post(
        "/api/simple/chat",
        json={"message": "Tenho R$ 1.081,38 de fatura, R$ 481 é da parcela do meu celular, o resto são compras avulsas."},
    )
    payment = client.post("/api/simple/chat", json={"message": "Paguei R$ 300 da fatura."})

    assert invoice.status_code == 200
    assert invoice.json()["intent"] == "registrar_fatura"
    assert payment.status_code == 200
    assert payment.json()["intent"] == "pagar_fatura_parcial"

    summary = client.get("/api/simple/summary").json()
    assert summary["totals"]["openInvoices"] == 781.38
    assert summary["totals"]["paidExpenses"] == 300
    assert summary["totals"]["balanceAfterPending"] == -1081.38
    items = summary["openInvoices"][0]["items"]
    assert items[0]["description"] == "parcela do celular"
    assert items[0]["amount"] == 481
    assert items[1]["description"] == "compras avulsas"
    assert items[1]["amount"] == 600.38


def test_simple_finance_daily_income_expense_and_pending_payment(tmp_path, monkeypatch):
    client = make_empty_client(tmp_path, monkeypatch)

    income = client.post("/api/simple/chat", json={"message": "Hoje ganhei R$ 250"})
    expense = client.post("/api/simple/chat", json={"message": "Gastei R$ 40 no mercado"})
    pending = client.post("/api/simple/chat", json={"message": "Tenho R$ 120 de internet para pagar"})
    paid = client.post("/api/simple/chat", json={"message": "Paguei a internet"})

    assert income.json()["intent"] == "registrar_receita"
    assert expense.json()["intent"] == "registrar_despesa_paga"
    assert pending.json()["intent"] == "registrar_despesa_pendente"
    assert paid.json()["intent"] == "pagar_despesa"

    summary = client.get("/api/simple/summary").json()
    assert summary["totals"]["income"] == 250
    assert summary["totals"]["paidExpenses"] == 160
    assert summary["totals"]["pendingExpenses"] == 0
    assert summary["totals"]["netBalance"] == 90
    assert summary["totals"]["balanceAfterPending"] == 90


def test_simple_finance_records_weekly_work_hours(tmp_path, monkeypatch):
    client = make_empty_client(tmp_path, monkeypatch)

    response = client.post(
        "/api/simple/chat",
        json={"message": "segunda eu trabalhei das 11:00 às 19:30 ganhando 12 por hora"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "registrar_jornada_trabalho"
    assert body["data"]["hours"] == 8.5
    assert body["data"]["gross"] == 102
    assert body["data"]["workWeek"]["hours"] == 8.5
    assert body["data"]["workWeek"]["gross"] == 102
    assert "Total da semana" in body["answer"]

    summary = client.get("/api/simple/summary").json()
    assert summary["workWeek"]["hours"] == 8.5
    assert summary["workWeek"]["gross"] == 102


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
    assert body["data"]["category"] == "Supermercado"

    transactions = client.get("/api/transactions", params={"search": "mercado", "limit": 10}).json()
    assert any(tx["amount"] == -80 and tx["source"] == "agent" for tx in transactions)

    patterns = client.get("/api/patterns").json()
    assert any(pattern["pattern"] == "mercado" and pattern["category"] == "Supermercado" for pattern in patterns)


def test_agent_saves_fixed_installment_expense_without_changing_balance(tmp_path, monkeypatch):
    client = make_empty_client(tmp_path, monkeypatch)

    response = client.post(
        "/api/agent/chat",
        json={"message": "guarde essa informacao, de gasto fixo eu tenho 481,60 da parcela do meu celular, tenho mais 11 parcelas a pagar"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "remember_commitment"
    assert body["data"]["kind"] == "expense"
    assert body["data"]["amount"] == 481.6
    assert body["data"]["installments_remaining"] == 11
    assert body["data"]["futureTotal"] == 5297.6

    commitments = client.get("/api/commitments").json()
    dashboard = client.get("/api/dashboard").json()
    assert len(commitments) == 1
    assert commitments[0]["amount"] == 481.6
    assert commitments[0]["installments_remaining"] == 11
    assert dashboard["kpis"]["balance"] == 0


def test_summary_excludes_transfers_card_payments_and_offsets_refunds(tmp_path, monkeypatch):
    client = make_empty_client(tmp_path, monkeypatch)
    rows = [
        {"date": "2026-07-01", "description": "salario recebido", "amount": 1000},
        {"date": "2026-07-02", "description": "ifood jantar", "amount": -100},
        {"date": "2026-07-03", "description": "mercado bairro", "amount": -80},
        {"date": "2026-07-04", "description": "estorno ifood", "amount": 20},
        {"date": "2026-07-05", "description": "transferencia propria", "amount": -500},
        {"date": "2026-07-06", "description": "pagamento fatura cartao", "amount": -300},
    ]
    for row in rows:
        response = client.post("/api/transactions", json=row)
        assert response.status_code == 200

    summary = client.get("/api/dashboard", params={"month": "2026-07"}).json()
    transactions = client.get("/api/transactions").json()

    assert summary["kpis"]["income"] == 1000
    assert summary["kpis"]["grossExpenses"] == 180
    assert summary["kpis"]["refunds"] == 20
    assert summary["kpis"]["expenses"] == 160
    assert summary["kpis"]["net"] == 840
    assert summary["kpis"]["balance"] == 840
    assert any(tx["transaction_type"] == "card_payment" and tx["is_internal"] for tx in transactions)
    assert any(tx["transaction_type"] == "transfer" and tx["is_internal"] for tx in transactions)


def test_agent_answers_category_spend_with_deterministic_router(tmp_path, monkeypatch):
    client = make_empty_client(tmp_path, monkeypatch)
    client.post("/api/transactions", json={"date": "2026-07-01", "description": "ifood jantar", "amount": -100})
    client.post("/api/transactions", json={"date": "2026-07-02", "description": "restaurante bairro", "amount": -50})

    response = client.post("/api/agent/chat", json={"message": "quanto gastei com alimentacao em 2026-07?"})

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "category_spend"
    assert body["mode"] == "deterministic"
    assert body["data"]["value"] == 150


def test_agent_answers_largest_expense_without_internal_payments(tmp_path, monkeypatch):
    client = make_empty_client(tmp_path, monkeypatch)
    client.post("/api/transactions", json={"date": "2026-07-01", "description": "pagamento fatura cartao", "amount": -900})
    client.post("/api/transactions", json={"date": "2026-07-02", "description": "uber corrida", "amount": -45})
    client.post("/api/transactions", json={"date": "2026-07-03", "description": "mercado bairro", "amount": -120})

    response = client.post("/api/agent/chat", json={"message": "qual foi meu maior gasto em 2026-07?"})

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "largest_expense"
    assert "mercado" in body["data"]["transaction"]["description"]


def test_agent_answers_income_balance_and_transaction_list(tmp_path, monkeypatch):
    client = make_empty_client(tmp_path, monkeypatch)
    rows = [
        {"date": "2026-07-01", "description": "salario recebido", "amount": 1200},
        {"date": "2026-07-02", "description": "ifood jantar", "amount": -100},
        {"date": "2026-07-03", "description": "mercado bairro", "amount": -80},
    ]
    for row in rows:
        assert client.post("/api/transactions", json=row).status_code == 200

    income = client.post("/api/agent/chat", json={"message": "quanto ganhei em 2026-07?"}).json()
    balance = client.post("/api/agent/chat", json={"message": "qual meu saldo atual?"}).json()
    listing = client.post("/api/agent/chat", json={"message": "liste meus lancamentos em 2026-07"}).json()

    assert income["intent"] == "total_income"
    assert income["data"]["income"] == 1200
    assert balance["intent"] == "balance"
    assert balance["data"]["kpis"]["balance"] == 1020
    assert listing["intent"] == "transaction_list"
    assert listing["data"]["count"] == 3


def test_agent_answers_work_totals_and_hourly_rate(tmp_path, monkeypatch):
    client = make_empty_client(tmp_path, monkeypatch)

    client.post("/api/agent/chat", json={"message": "minha hora e 30 reais"})
    client.post("/api/agent/chat", json={"message": "02/07/2026 trabalhei das 10:00 ate 12:00"})
    client.post("/api/agent/chat", json={"message": "03/07/2026 trabalhei 3 horas"})

    rate = client.post("/api/agent/chat", json={"message": "qual meu valor hora?"}).json()
    work = client.post("/api/agent/chat", json={"message": "quanto trabalhei em 2026-07?"}).json()

    assert rate["intent"] == "hourly_rate"
    assert rate["data"]["hourlyRate"] == 30
    assert work["intent"] == "work_total"
    assert work["data"]["hours"] == 5
    assert work["data"]["gross"] == 150


def test_agent_blocks_ambiguous_financial_question_without_llm_guess(tmp_path, monkeypatch):
    client = make_empty_client(tmp_path, monkeypatch)
    client.post("/api/transactions", json={"date": "2026-07-01", "description": "salario recebido", "amount": 1200})

    response = client.post("/api/agent/chat", json={"message": "qual foi aquela coisa do pix?"})

    assert response.status_code == 200
    assert response.json()["intent"] == "unsupported_financial_question"


def test_category_rules_reprocess_and_manual_lock(tmp_path, monkeypatch):
    client = make_empty_client(tmp_path, monkeypatch)
    created_tx = client.post(
        "/api/transactions",
        json={"date": "2026-07-01", "description": "academia mensal", "amount": -90},
    ).json()

    rule = client.post(
        "/api/category-rules",
        json={"pattern": "academia", "category": "Saude", "transaction_type": "expense", "is_internal": False},
    )
    assert rule.status_code == 200
    assert rule.json()["source"] == "custom"

    reprocessed = client.post("/api/transactions/reprocess")
    assert reprocessed.status_code == 200
    assert reprocessed.json()["updated"] == 1
    tx = client.get("/api/transactions", params={"search": "academia"}).json()[0]
    assert tx["category"] == "Saude"

    patched = client.patch(f"/api/transactions/{created_tx['id']}", json={"category": "Outros"})
    assert patched.status_code == 200
    assert patched.json()["category"] == "Outros"

    client.post("/api/transactions/reprocess")
    tx = client.get("/api/transactions", params={"search": "academia"}).json()[0]
    assert tx["category"] == "Outros"
    assert tx["category_locked"] == 1


def test_agent_calculates_hourly_work_session_from_message(tmp_path, monkeypatch):
    client = make_empty_client(tmp_path, monkeypatch)

    response = client.post(
        "/api/agent/chat",
        json={"message": "eu ganho 12 reais por hora, terça feira eu trabalhei das 14:00 ate as 18:40"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "record_work_session"
    assert body["data"]["hours"] == 4.6667
    assert body["data"]["gross_amount"] == 56
    assert body["data"]["hourly_rate"] == 12

    dashboard = client.get("/api/dashboard").json()
    assert dashboard["kpis"]["balance"] == 56
    assert dashboard["recentTransactions"][0]["source"] == "work_session"

    facts = client.get("/api/facts").json()
    assert any(fact["key"] == "hourly_rate" and fact["value"] == "12.00" for fact in facts)


def test_agent_reuses_saved_hourly_rate_for_next_work_session(tmp_path, monkeypatch):
    client = make_empty_client(tmp_path, monkeypatch)

    saved = client.post("/api/agent/chat", json={"message": "minha hora é 20 reais"})
    worked = client.post("/api/agent/chat", json={"message": "hoje trabalhei das 10:00 ate as 12:30"})

    assert saved.status_code == 200
    assert saved.json()["intent"] == "remember_hourly_rate"
    assert worked.status_code == 200
    body = worked.json()
    assert body["intent"] == "record_work_session"
    assert body["data"]["hours"] == 2.5
    assert body["data"]["gross_amount"] == 50

    duplicate = client.post("/api/agent/chat", json={"message": "hoje trabalhei das 10:00 ate as 12:30"})
    assert duplicate.json()["data"]["duplicated"] is True
    assert client.get("/api/dashboard").json()["kpis"]["balance"] == 50


def test_agent_records_work_session_with_iso_date_from_form(tmp_path, monkeypatch):
    client = make_empty_client(tmp_path, monkeypatch)

    response = client.post(
        "/api/agent/chat",
        json={"message": "2026-07-02 trabalhei das 10:00 ate 12:30 ganhando R$ 20 por hora"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "record_work_session"
    assert body["data"]["date"] == "2026-07-02"
    assert body["data"]["hours"] == 2.5
    assert body["data"]["gross_amount"] == 50

    sessions = client.get("/api/work-sessions").json()
    assert sessions[0]["date"] == "2026-07-02"


def test_agent_corrects_previous_work_session_without_duplicate(tmp_path, monkeypatch):
    client = make_empty_client(tmp_path, monkeypatch)

    first = client.post(
        "/api/agent/chat",
        json={"message": "02/07/2026 trabalhei das 13:30 até as 15:30 ganhando 12 por hora"},
    )
    correction = client.post(
        "/api/agent/chat",
        json={"message": "falei errado, 02/07/2026 trabalhei das 13:30 às 17:30"},
    )

    assert first.status_code == 200
    assert first.json()["intent"] == "record_work_session"
    assert correction.status_code == 200
    body = correction.json()
    assert body["intent"] == "correct_work_session"
    assert body["data"]["corrected"] is True
    assert body["data"]["hours"] == 4
    assert body["data"]["gross_amount"] == 48
    assert body["data"]["delta"] == 24

    sessions = client.get("/api/work-sessions").json()
    transactions = client.get("/api/transactions").json()
    dashboard = client.get("/api/dashboard", params={"month": "2026-07"}).json()

    assert len(sessions) == 1
    assert sessions[0]["end_time"] == "17:30"
    assert len(transactions) == 1
    assert transactions[0]["amount"] == 48
    assert dashboard["kpis"]["income"] == 48
    assert dashboard["kpis"]["balance"] == 48


def test_agent_correction_merges_existing_duplicate_work_sessions(tmp_path, monkeypatch):
    client = make_empty_client(tmp_path, monkeypatch)

    client.post(
        "/api/agent/chat",
        json={"message": "02/07/2026 trabalhei das 13:30 ate as 15:30 ganhando 12 por hora"},
    )
    client.post(
        "/api/agent/chat",
        json={"message": "02/07/2026 trabalhei das 13:30 ate as 17:00 ganhando 12 por hora"},
    )

    before = client.get("/api/dashboard", params={"month": "2026-07"}).json()
    assert before["kpis"]["income"] == 66

    correction = client.post(
        "/api/agent/chat",
        json={"message": "mandei errado denov, 02/07/2026 trabalhei das 13:30 as 17a;30"},
    )

    assert correction.status_code == 200
    body = correction.json()
    assert body["intent"] == "correct_work_session"
    assert body["data"]["hours"] == 4
    assert body["data"]["gross_amount"] == 48
    assert body["data"]["duplicatesMerged"] == 1
    assert body["data"]["delta"] == -18

    sessions = client.get("/api/work-sessions").json()
    transactions = client.get("/api/transactions").json()
    dashboard = client.get("/api/dashboard", params={"month": "2026-07"}).json()

    assert len(sessions) == 1
    assert sessions[0]["end_time"] == "17:30"
    assert len(transactions) == 1
    assert transactions[0]["amount"] == 48
    assert dashboard["kpis"]["income"] == 48
    assert dashboard["kpis"]["balance"] == 48


def test_agent_builds_strategic_plan_without_inventing_target_price(tmp_path, monkeypatch):
    client = make_empty_client(tmp_path, monkeypatch)

    response = client.post(
        "/api/agent/chat",
        json={
            "message": "ganho em media 1200 por mes, antes dos 22 eu quero comprar um byd king, qual o melhor plano para mim?"
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "strategic_plan"
    assert body["data"]["goalName"] == "BYD King"
    assert body["data"]["monthlyIncome"] == 1200
    assert body["data"]["targetAge"] == 22
    assert body["data"]["targetAmount"] is None
    assert "preco alvo ou entrada desejada" in body["data"]["missing"]
    assert "idade atual" in body["data"]["missing"]
    assert "prazo ou idade-alvo" not in body["data"]["missing"]
    assert "idade-alvo 22 anos" in body["answer"]
    assert "Falta sua idade atual" in body["answer"]
    assert "Nao vou inventar" in body["answer"]


def test_agent_continues_strategic_plan_conversation(tmp_path, monkeypatch):
    client = make_empty_client(tmp_path, monkeypatch)

    first = client.post(
        "/api/agent/chat",
        json={
            "message": "ganho em media 1200 por mes, antes dos 22 eu quero comprar um byd king, qual o melhor plano para mim?"
        },
    )
    second = client.post(
        "/api/agent/chat",
        json={"message": "tenho 17 anos, tenho 5 anos ate la"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    body = second.json()
    assert body["intent"] == "strategic_plan"
    assert body["data"]["goalName"] == "BYD King"
    assert body["data"]["monthlyIncome"] == 1200
    assert body["data"]["currentAge"] == 17
    assert body["data"]["targetAge"] == 22
    assert body["data"]["monthsLeft"] == 60
    assert body["intent"] != "overview"


def test_agent_continues_strategic_plan_with_price_and_expenses(tmp_path, monkeypatch):
    client = make_empty_client(tmp_path, monkeypatch)

    client.post(
        "/api/agent/chat",
        json={"message": "ganho 1200 por mes e quero comprar um byd king antes dos 22"},
    )
    client.post("/api/agent/chat", json={"message": "tenho 17 anos"})
    response = client.post(
        "/api/agent/chat",
        json={"message": "o preco alvo e R$ 180.000 e meu gasto mensal medio e R$ 700"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "strategic_plan"
    assert body["data"]["targetAmount"] == 180000
    assert body["data"]["monthlyExpenses"] == 700
    assert body["data"]["monthlyRequired"] == 3000
    assert body["data"]["monthlyGap"] == 2500


def test_agent_builds_strategic_plan_with_required_monthly_amount(tmp_path, monkeypatch):
    client = make_empty_client(tmp_path, monkeypatch)

    response = client.post(
        "/api/agent/chat",
        json={"message": "tenho 20 anos, ganho 1200 por mes e quero comprar uma moto por R$ 12000 antes dos 22"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "strategic_plan"
    assert body["data"]["goalName"] == "Moto"
    assert body["data"]["monthsLeft"] == 24
    assert body["data"]["targetAmount"] == 12000
    assert body["data"]["monthlyRequired"] == 500


def test_assistant_layer_evaluates_installment_purchase_with_free_balance(tmp_path, monkeypatch):
    client = make_empty_client(tmp_path, monkeypatch)
    client.post("/api/transactions", json={"date": "2026-07-01", "description": "salario recebido", "amount": 1200})
    client.post("/api/transactions", json={"date": "2026-07-02", "description": "mercado bairro", "amount": -500})
    client.post(
        "/api/agent/chat",
        json={"message": "guarde gasto fixo de R$ 300 da parcela do notebook, tenho mais 4 parcelas a pagar"},
    )

    response = client.post(
        "/api/agent/chat",
        json={"message": "em 2026-07 posso comprar um celular de R$ 2400 em 10x?"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "purchase_decision"
    assert body["mode"] == "assistant_layer"
    assert body["data"]["amount"] == 2400
    assert body["data"]["installments"] == 10
    assert body["data"]["installmentAmount"] == 240
    assert body["data"]["freeBalance"] == 400
    assert body["data"]["monthlyCommitments"] == 300
    assert body["data"]["structured_intent"]["intent"] == "avaliar_compra"
    assert body["data"]["safety"]["calculation_owner"] == "python"


def test_assistant_layer_asks_missing_purchase_data_without_guessing(tmp_path, monkeypatch):
    client = make_empty_client(tmp_path, monkeypatch)

    response = client.post("/api/agent/chat", json={"message": "posso comprar isso?"})

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "missing_financial_data"
    assert "valor_total" in body["data"]["safety"]["missing_fields"]
    assert body["data"]["safety"]["raw_statement_sent_to_ai"] is False


def test_assistant_layer_does_not_record_ambiguous_installment_purchase(tmp_path, monkeypatch):
    client = make_empty_client(tmp_path, monkeypatch)

    response = client.post("/api/agent/chat", json={"message": "comprei um celular de R$ 2400 em 10x"})

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "missing_financial_data"
    assert body["data"]["structured_intent"]["intent"] == "confirmar_parcelamento"
    assert body["data"]["structured_intent"]["needs_confirmation"] is True
    assert client.get("/api/transactions").json() == []


def test_assistant_layer_reports_real_free_and_projected_balance(tmp_path, monkeypatch):
    client = make_empty_client(tmp_path, monkeypatch)
    client.post("/api/transactions", json={"date": "2026-07-01", "description": "salario recebido", "amount": 1200})
    client.post(
        "/api/agent/chat",
        json={"message": "guarde gasto fixo de R$ 200 da parcela do celular, tenho mais 3 parcelas a pagar"},
    )

    response = client.post("/api/agent/chat", json={"message": "qual meu saldo livre e saldo projetado em 2026-07?"})

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "balance_position"
    assert body["data"]["saldo_real"] == 1200
    assert body["data"]["saldo_comprometido"] == 200
    assert body["data"]["saldo_livre"] == 1000


def test_agent_learns_profile_facts_and_uses_them_in_goal_plan(tmp_path, monkeypatch):
    client = make_empty_client(tmp_path, monkeypatch)

    learned = client.post(
        "/api/agent/chat",
        json={"message": "lembre que minha renda media e R$ 1200 por mes e tenho 17 anos"},
    )
    plan = client.post(
        "/api/agent/chat",
        json={"message": "quero comprar uma moto por R$ 12000 antes dos 22, qual plano?"},
    )

    assert learned.status_code == 200
    assert learned.json()["intent"] == "train_assistant"
    facts = client.get("/api/facts").json()
    assert any(item["key"] == "profile:monthly_income" and item["value"] == "1200.00" for item in facts)
    assert any(item["key"] == "profile:current_age" and item["value"] == "17" for item in facts)

    body = plan.json()
    assert body["intent"] == "strategic_plan"
    assert body["data"]["monthlyIncome"] == 1200
    assert body["data"]["currentAge"] == 17
    assert body["data"]["monthsLeft"] == 60
    assert body["data"]["monthlyRequired"] == 200


def test_agent_learns_category_rule_from_chat(tmp_path, monkeypatch):
    client = make_empty_client(tmp_path, monkeypatch)

    learned = client.post(
        "/api/agent/chat",
        json={"message": "aprenda quando aparecer academia premium categoria Saude"},
    )
    tx = client.post(
        "/api/transactions",
        json={"date": "2026-07-01", "description": "academia premium mensal", "amount": -99},
    )

    assert learned.status_code == 200
    assert learned.json()["intent"] == "train_assistant"
    assert learned.json()["data"]["trainingType"] == "category_rule"
    assert tx.json()["category"] == "Saude"


def test_agent_answers_what_it_knows_about_user(tmp_path, monkeypatch):
    client = make_empty_client(tmp_path, monkeypatch)
    client.post("/api/agent/chat", json={"message": "lembre que minha renda media e R$ 1200 por mes"})

    response = client.post("/api/agent/chat", json={"message": "o que voce sabe sobre mim?"})

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "memory_profile"
    assert any(item["key"] == "profile:monthly_income" for item in body["data"]["facts"])


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
