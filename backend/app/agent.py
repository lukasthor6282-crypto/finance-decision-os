from __future__ import annotations

import os
import re
from sqlite3 import Connection

from .accounting import ParsedTransaction, parse_transaction_message
from .analytics import money, scenario, summarize
from .repository import insert_transaction


SYSTEM_PROMPT = """
Voce e um agente financeiro privado. Responda em portugues, com base apenas nos dados do usuario.
Nao invente saldo, renda, objetivo ou transacao. De raciocinio curto, numeros e proximos passos.
Nao ofereca recomendacao financeira profissional; entregue analise educacional e operacional.
"""


def answer(conn: Connection, message: str) -> dict:
    parsed = parse_transaction_message(message)
    if parsed:
        return record_transaction_from_chat(conn, parsed)

    summary = summarize(conn)
    if os.getenv("OPENAI_API_KEY"):
        try:
            return openai_answer(summary, message)
        except Exception as exc:
            local = local_answer(conn, summary, message)
            local["answer"] += f"\n\nModo local ativado: provedor IA falhou ({type(exc).__name__})."
            return local
    return local_answer(conn, summary, message)


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
            summary["actionPlan"][0]["title"],
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


def openai_answer(summary: dict, message: str) -> dict:
    from openai import OpenAI

    client = OpenAI()
    response = client.responses.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        input=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Dados financeiros JSON:\n{summary}\n\nPergunta:\n{message}"},
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
    return response(
        intent="overview",
        answer=(
            f"Mes {summary['month']}: renda {money(kpis['income'])}, gastos {money(kpis['expenses'])}, "
            f"liquido {money(kpis['net'])}, poupanca {kpis['savingsRate']}%. "
            f"Saude financeira {kpis['healthScore']}/100. Proxima decisao: {summary['actionPlan'][0]['title']}."
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
