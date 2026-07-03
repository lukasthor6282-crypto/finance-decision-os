from __future__ import annotations

import os
import re
from sqlite3 import Connection

from .accounting import ParsedTransaction, parse_transaction_message
from .analytics import money, scenario, summarize
from .commitments import ParsedCommitment, parse_commitment_message
from .financial_assistant_layer import handle_financial_assistant_layer
from .question_router import answer_question
from .repository import (
    existing_work_session,
    find_work_session_for_correction,
    get_float_fact,
    insert_commitment,
    insert_transaction,
    insert_work_session,
    set_fact,
    update_work_session,
)
from .strategic_planner import answer_strategic_plan, asks_strategic_plan, continues_strategic_plan
from .worktime import ParsedWorkSession, is_work_correction_message, parse_hourly_rate, parse_work_session_message


SYSTEM_PROMPT = """
Voce e um agente financeiro privado. Responda em portugues, com base apenas nos dados do usuario.
Nao invente saldo, renda, objetivo ou transacao. De raciocinio curto, numeros e proximos passos.
Nao faca calculos financeiros por conta propria. Se a pergunta exigir valor especifico e o Python nao entregou esse valor, diga que nao ha dados suficientes.
Use somente o resumo JSON fornecido. Nunca presuma extrato completo quando o dado nao estiver no JSON.
Nao ofereca recomendacao financeira profissional; entregue analise educacional e operacional.
"""


def answer(conn: Connection, message: str) -> dict:
    hourly_rate = parse_hourly_rate(message)
    known_hourly_rate = hourly_rate or get_float_fact(conn, "hourly_rate")
    work_session = parse_work_session_message(message, known_hourly_rate)
    if work_session:
        if is_work_correction_message(message):
            return correct_work_session_from_chat(conn, work_session)
        return record_work_session_from_chat(conn, work_session)

    if hourly_rate is not None and any(word in message.lower() for word in ["hora", "/h", "por hora"]):
        set_fact(conn, "hourly_rate", f"{hourly_rate:.2f}", "money_per_hour", 0.95)
        return response(
            intent="remember_hourly_rate",
            answer=f"Valor/hora salvo: {money(hourly_rate)}. Quando voce disser uma jornada, eu calculo horas, valor bruto e lanço como receita.",
            actions=[
                "Exemplo: hoje trabalhei das 14:00 ate 18:40.",
                "Exemplo: ontem trabalhei 5 horas.",
            ],
            confidence=0.94,
            data={"hourlyRate": hourly_rate},
        )

    commitment = parse_commitment_message(message)
    if commitment:
        return record_commitment_from_chat(conn, commitment)

    if asks_strategic_plan(message) or continues_strategic_plan(conn, message):
        return answer_strategic_plan(conn, message)

    layered = handle_financial_assistant_layer(conn, message)
    if layered:
        return layered

    parsed = parse_transaction_message(message)
    if parsed:
        return record_transaction_from_chat(conn, parsed)

    routed = answer_question(conn, message)
    if routed:
        return routed

    summary = summarize(conn)
    guarded = guarded_unknown_question(message)
    if guarded:
        return guarded

    if os.getenv("OPENAI_API_KEY"):
        try:
            return openai_answer(summary, message)
        except Exception as exc:
            local = local_answer(conn, summary, message)
            local["answer"] += f"\n\nModo local ativado: provedor IA falhou ({type(exc).__name__})."
            return local
    return local_answer(conn, summary, message)


def guarded_unknown_question(message: str) -> dict | None:
    lower = message.lower()
    has_question_shape = "?" in lower or any(word in lower for word in ["quanto", "qual", "quais", "onde", "quando", "listar", "mostre"])
    finance_terms = [
        "gastei",
        "ganhei",
        "recebi",
        "saldo",
        "despesa",
        "receita",
        "categoria",
        "cartao",
        "fatura",
        "pix",
        "trabalhei",
        "horas",
        "extrato",
    ]
    purchase_terms = ["comprar", "posso", "vale", "pagar", "assinar"]
    if has_question_shape and any(term in lower for term in finance_terms) and not any(term in lower for term in purchase_terms):
        return response(
            intent="unsupported_financial_question",
            answer="Nao consegui interpretar essa pergunta com seguranca. Posso responder melhor se voce citar periodo, categoria ou tipo de dado.",
            actions=[
                "Ex.: quanto gastei com alimentacao em julho?",
                "Ex.: quanto ganhei esta semana?",
                "Ex.: quanto trabalhei este mes?",
            ],
            confidence=0.62,
            data={},
        )
    return None


def record_transaction_from_chat(conn: Connection, tx: ParsedTransaction) -> dict:
    result = insert_transaction(
        conn,
        {
            "date": tx.date,
            "description": tx.description,
            "amount": tx.amount,
            "category": tx.category,
            "account": tx.account,
            "notes": tx.notes,
        },
        source="agent",
    )
    summary = summarize(conn)
    kpis = summary["kpis"]
    direction = "receita" if tx.amount > 0 else "despesa"
    duplicate_line = " Ja existia lancamento igual; nao dupliquei." if result.duplicated else ""
    next_action = summary["actionPlan"][0]["title"] if summary["actionPlan"] else "Continue registrando entradas e saidas."

    return response(
        intent="record_transaction",
        answer=(
            f"Lancamento salvo: {direction} de {money(abs(tx.amount))} em {tx.category}. "
            f"Saldo agora: {money(kpis['balance'])}. "
            f"No mes: renda {money(kpis['income'])}, gastos {money(kpis['expenses'])}, liquido {money(kpis['net'])}."
            f"{duplicate_line}"
        ),
        actions=[
            "Revise categoria se necessario.",
            "Continue registrando entradas e saidas pelo chat.",
            next_action,
        ],
        confidence=0.9,
        data={
            "id": result.id,
            "duplicated": result.duplicated,
            "date": tx.date,
            "description": tx.description,
            "amount": tx.amount,
            "category": tx.category,
            "account": tx.account,
            "balance": kpis["balance"],
            "pattern": tx.pattern,
        },
    )


def record_commitment_from_chat(conn: Connection, commitment: ParsedCommitment) -> dict:
    result = insert_commitment(conn, commitment)
    label = "receita fixa" if commitment.kind == "income" else "despesa fixa"
    remaining = ""
    total_future = None
    if commitment.installments_remaining:
        total_future = round(commitment.amount * commitment.installments_remaining, 2)
        remaining = f" {commitment.installments_remaining} parcelas restantes, total futuro {money(total_future)}."
    duplicate_line = " Atualizei compromisso existente." if result.duplicated else ""

    return response(
        intent="remember_commitment",
        answer=(
            f"{label.capitalize()} salva: {commitment.description} de {money(commitment.amount)}/mes."
            f"{remaining}{duplicate_line} Nao alterei saldo; saldo muda quando voce registrar pagamento ou receita real."
        ),
        actions=[
            "Veja em Receitas/Despesas.",
            "Quando pagar a parcela, diga: paguei R$ 481,60 parcela celular.",
            "Se quitar ou mudar valor, me informe pelo chat.",
        ],
        confidence=0.93,
        data={
            **commitment.__dict__,
            "id": result.id,
            "duplicated": result.duplicated,
            "futureTotal": total_future,
        },
    )


def record_work_session_from_chat(conn: Connection, session: ParsedWorkSession) -> dict:
    set_fact(conn, "hourly_rate", f"{session.hourly_rate:.2f}", "money_per_hour", 0.98)
    existing = existing_work_session(conn, session)
    if existing:
        summary = summarize(conn)
        return response(
            intent="record_work_session",
            answer=(
                f"Jornada ja registrada: {session.hours:.2f}h a {money(session.hourly_rate)}/h. "
                f"Nao dupliquei. Saldo atual: {money(summary['kpis']['balance'])}."
            ),
            actions=["Se foi outro turno, informe horario diferente.", "Se teve intervalo, diga quantos minutos."],
            confidence=0.88,
            data={**session.__dict__, "duplicated": True, "transactionId": existing["transaction_id"]},
        )

    tx_result = insert_transaction(
        conn,
        {
            "date": session.date,
            "description": session.description,
            "amount": session.gross_amount,
            "category": "Receita",
            "transaction_type": "income",
            "account": "Principal",
            "notes": session.notes,
        },
        source="work_session",
    )
    work_result = insert_work_session(conn, session, tx_result.id)
    summary = summarize(conn)
    kpis = summary["kpis"]
    time_line = ""
    if session.start_time and session.end_time:
        time_line = f" ({session.start_time}-{session.end_time})"

    return response(
        intent="record_work_session",
        answer=(
            f"Jornada salva{time_line}: {session.hours:.2f}h x {money(session.hourly_rate)}/h = {money(session.gross_amount)}. "
            f"Lancei como receita. Saldo agora: {money(kpis['balance'])}. "
            f"No mes: renda {money(kpis['income'])}, gastos {money(kpis['expenses'])}, liquido {money(kpis['net'])}."
        ),
        actions=[
            "Valor/hora memorizado para proximas jornadas.",
            "Informe pausas como: com 30 minutos de intervalo.",
            "Continue registrando receitas e despesas pelo chat.",
        ],
        confidence=0.95,
        data={
            **session.__dict__,
            "id": work_result.id,
            "transactionId": tx_result.id,
            "duplicated": False,
            "balance": kpis["balance"],
        },
    )


def correct_work_session_from_chat(conn: Connection, session: ParsedWorkSession) -> dict:
    previous = find_work_session_for_correction(conn, session)
    if not previous:
        return response(
            intent="correct_work_session",
            answer="Nao encontrei uma jornada anterior desse dia para corrigir. Registre como nova jornada ou informe data e horario inicial.",
            actions=[
                "Ex.: falei errado, na quarta trabalhei das 13:30 as 17:30.",
                "Ex.: corrigir 02/07/2026 das 13:30 as 17:30.",
            ],
            confidence=0.72,
            data={**session.__dict__, "corrected": False},
        )

    old_hours = float(previous.get("total_hours", previous["hours"]))
    old_amount = float(previous.get("total_gross_amount", previous["gross_amount"]))
    result = update_work_session(conn, previous["id"], session)
    summary = summarize(conn)
    kpis = summary["kpis"]
    time_line = f" ({session.start_time}-{session.end_time})" if session.start_time and session.end_time else ""
    delta = session.gross_amount - old_amount

    return response(
        intent="correct_work_session",
        answer=(
            f"Jornada corrigida{time_line}: antes {old_hours:.2f}h/{money(old_amount)}, "
            f"agora {session.hours:.2f}h x {money(session.hourly_rate)}/h = {money(session.gross_amount)}. "
            f"Ajuste no saldo: {money(delta)}. Saldo agora: {money(kpis['balance'])}."
        ),
        actions=[
            "Corrigi a jornada e a receita ligada a ela.",
            "Nao criei lancamento duplicado.",
            "Revise no livro caixa se o horario ficou correto.",
        ],
        confidence=0.95,
        data={
            **session.__dict__,
            "id": result.id,
            "transactionId": result.transaction_id,
            "corrected": True,
            "previousHours": old_hours,
            "previousAmount": old_amount,
            "duplicatesMerged": previous.get("duplicate_count", 0),
            "delta": round(delta, 2),
            "balance": kpis["balance"],
        },
    )


def openai_answer(summary: dict, message: str) -> dict:
    from openai import OpenAI

    context = structured_llm_context(summary)
    client = OpenAI()
    response = client.responses.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        input=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Dados financeiros estruturados JSON:\n{context}\n\nPergunta:\n{message}"},
        ],
    )
    text = getattr(response, "output_text", "").strip() or "Nao consegui gerar resposta com o provedor IA."
    return {
        "answer": text,
        "actions": [item["title"] for item in summary["actionPlan"]],
        "confidence": 0.82,
        "mode": "openai",
        "intent": "llm",
        "data": {"summaryMonth": summary["month"], "healthScore": summary["kpis"]["healthScore"]},
    }


def structured_llm_context(summary: dict) -> dict:
    kpis = summary["kpis"]
    return {
        "periodo": summary["month"],
        "kpis": {
            "saldo_real": kpis["balance"],
            "receitas": kpis["income"],
            "despesas": kpis["expenses"],
            "liquido": kpis["net"],
            "poupanca_percentual": kpis["savingsRate"],
            "saldo_projetado": kpis["projectedBalance"],
            "risco_caixa": kpis["cashRisk"],
            "score_saude": kpis["healthScore"],
            "status_saude": kpis["healthLabel"],
        },
        "categorias_criticas": summary.get("categorySpend", [])[:5],
        "orcamentos": summary.get("budgetStatus", [])[:5],
        "recorrencias": summary.get("recurring", [])[:5],
        "metas": summary.get("goals", [])[:5],
        "alertas": summary.get("alerts", [])[:5],
        "acoes": summary.get("actionPlan", [])[:5],
        "regras": {
            "calculos_feitos_por": "python",
            "extrato_bruto_enviado": False,
            "nao_inventar_valores": True,
        },
    }


def local_answer(conn: Connection, summary: dict, message: str) -> dict:
    lower = message.lower()
    amount = extract_amount(lower)

    if amount and any(word in lower for word in ["comprar", "posso", "vale", "gastar", "pagar", "assinar"]):
        result = scenario(conn, "Cenario pedido ao agente", amount)
        budget_line = ""
        if result.get("budgetAfter"):
            budget = result["budgetAfter"]
            budget_line = f" Categoria {budget['category']} iria para {budget['ratioAfter']}% do limite."
        return response(
            intent="purchase_decision",
            answer=(
                f"{result['verdict']}. {result['message']}{budget_line} "
                "Regra: poupanca >=20% e orcamento abaixo de 85% = folga; abaixo disso pede ajuste."
            ),
            actions=[
                "Compare com orcamento da categoria antes de pagar.",
                "Se nao for essencial, espere 72h.",
                "Compense no maior gasto variavel do mes.",
            ],
            confidence=0.8,
            data=result,
        )

    if any(word in lower for word in ["risco", "seguro", "caixa", "reserva", "saude", "saúde"]):
        kpis = summary["kpis"]
        return response(
            intent="cash_risk",
            answer=(
                f"Risco de caixa: {kpis['cashRisk']}. "
                f"Saldo: {money(kpis['balance'])}. "
                f"Queima diaria: {money(kpis['dailyBurn'])}. "
                f"Saldo projetado: {money(kpis['projectedBalance'])}. "
                f"Score financeiro: {kpis['healthScore']}/100 ({kpis['healthLabel']})."
            ),
            actions=[item["title"] for item in summary["actionPlan"]],
            confidence=0.82,
            data=summary["kpis"],
        )

    if any(word in lower for word in ["orcamento", "orçamento", "limite", "estourar", "categoria"]):
        budgets = summary["budgetStatus"]
        if not budgets:
            return response(
                intent="budget",
                answer="Nenhum orcamento cadastrado ainda. Cadastre limites por categoria para eu projetar estouro.",
                actions=["Criar orcamento por categoria", "Importar mais transacoes"],
                confidence=0.7,
                data=[],
            )
        top = budgets[0]
        return response(
            intent="budget",
            answer=(
                f"Categoria mais sensivel: {top['category']}. "
                f"Gasto atual {money(top['spent'])}, limite {money(top['limit'])}, "
                f"projecao {money(top['projected'])} ({top['projectedRatio']}%)."
            ),
            actions=[item["title"] for item in summary["actionPlan"]],
            confidence=0.78,
            data=budgets,
        )

    if any(word in lower for word in ["recorrente", "recorrencia", "recorrência", "assinatura", "fixo"]):
        recurring = summary["recurring"]
        if not recurring:
            return response(
                intent="recurring",
                answer="Nao detectei recorrencias fortes ainda. Preciso de pelo menos 3 meses parecidos por comerciante.",
                actions=["Importar extratos antigos", "Revisar assinaturas manualmente"],
                confidence=0.68,
                data=[],
            )
        top = recurring[0]
        return response(
            intent="recurring",
            answer=(
                f"Maior recorrencia: {top['merchant']} em {top['category']}. "
                f"Media {money(top['averageAmount'])}/mes, custo anual {money(top['annualizedCost'])}."
            ),
            actions=[f"Revisar {top['merchant']}", "Cancelar o que nao usar", "Renegociar planos anuais"],
            confidence=0.77,
            data=recurring,
        )

    if any(word in lower for word in ["meta", "objetivo", "sonho", "reserva"]):
        goals = summary["goals"]
        if not goals:
            return response(
                intent="goals",
                answer="Nenhuma meta cadastrada. Crie uma meta com valor alvo e prazo para eu calcular aporte mensal.",
                actions=["Criar meta de reserva", "Definir prazo", "Associar aporte mensal"],
                confidence=0.7,
                data=[],
            )
        goal = sorted(goals, key=lambda item: item["progress"])[0]
        monthly = f" Precisa de {money(goal['monthlyRequired'])}/mes." if goal.get("monthlyRequired") else ""
        return response(
            intent="goals",
            answer=f"Meta em foco: {goal['name']}. Falta {money(goal['remaining'])}. Progresso {goal['progress']}%.{monthly}",
            actions=[item["title"] for item in summary["actionPlan"]],
            confidence=0.78,
            data=goals,
        )

    if any(word in lower for word in ["economizar", "cortar", "reduzir", "sobrou", "poupar"]):
        category = summary["categorySpend"][0] if summary["categorySpend"] else None
        base = "Sem categoria dominante ainda."
        if category:
            base = f"Maior alavanca: {category['category']} com {money(category['value'])} ({category['share']}% dos gastos)."
        return response(
            intent="savings",
            answer=f"{base} Foque em 1 corte grande, nao 10 microcortes. Meta operacional: poupanca 20%+.",
            actions=[item["detail"] for item in summary["actionPlan"]],
            confidence=0.78,
            data={"categorySpend": summary["categorySpend"], "actionPlan": summary["actionPlan"]},
        )

    kpis = summary["kpis"]
    next_action = summary["actionPlan"][0]["title"] if summary["actionPlan"] else "Registre receita, despesa ou horas trabalhadas."
    return response(
        intent="overview",
        answer=(
            f"Mes {summary['month']}: renda {money(kpis['income'])}, gastos {money(kpis['expenses'])}, "
            f"liquido {money(kpis['net'])}, poupanca {kpis['savingsRate']}%. "
            f"Saude financeira {kpis['healthScore']}/100. Proxima decisao: {next_action}."
        ),
        actions=[item["title"] for item in summary["actionPlan"]],
        confidence=0.74,
        data={"kpis": kpis, "insights": summary["insights"]},
    )


def response(intent: str, answer: str, actions: list[str], confidence: float, data: dict | list | None = None) -> dict:
    return {
        "answer": answer,
        "actions": actions,
        "confidence": confidence,
        "mode": "local",
        "intent": intent,
        "data": data,
    }


def extract_amount(text: str) -> float | None:
    match = re.search(r"(?:r\$\s*)?(\d{2,}(?:[.,]\d{1,2})?)", text)
    if not match:
        return None
    value = match.group(1).replace(".", "").replace(",", ".")
    try:
        return float(value)
    except ValueError:
        return None
