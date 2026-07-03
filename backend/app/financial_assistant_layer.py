from __future__ import annotations

import re
import unicodedata
from datetime import date
from sqlite3 import Connection

from .analytics import money, previous_month_key, summarize
from .classifier import classify
from .normalization import parse_amount
from .repository import list_commitments


def handle_financial_assistant_layer(conn: Connection, message: str) -> dict | None:
    routed = route_intent(message)
    intent = routed["intent"]
    if intent == "avaliar_compra":
        return purchase_decision(conn, routed)
    if intent == "confirmar_parcelamento":
        return missing_data_response(
            routed,
            [
                "Confirme se isso ja saiu do caixa ou se devo salvar como compromisso futuro.",
                "Ex.: paguei a primeira parcela hoje.",
                "Ex.: salve como compromisso futuro de 10 parcelas.",
            ],
        )
    if intent == "consultar_saldo_livre":
        return balance_position_answer(conn, routed)
    if intent == "quanto_posso_gastar":
        return spending_room_answer(conn, routed)
    if intent == "gerar_relatorio_financeiro":
        return monthly_report_answer(conn, routed)
    if intent == "avaliar_saude_financeira":
        return financial_health_answer(conn, routed)
    if intent == "sugerir_cortes":
        return cut_suggestions_answer(conn, routed)
    if intent == "pedir_dados_faltantes":
        return missing_data_response(routed)
    return None


def route_intent(message: str) -> dict:
    text = soft_normalize(message)
    amount = extract_amount(message)
    installments = extract_installments(text)
    payment_mode = "parcelado" if installments and installments > 1 else "avista" if any(word in text for word in ["avista", "a vista"]) else None
    description = extract_purchase_description(text)
    entities = {
        "valor": amount,
        "descricao": description,
        "parcelas": installments,
        "forma_pagamento": payment_mode,
        "periodo": infer_month_key(text),
    }

    if asks_installment_registration(text):
        return structured_intent("confirmar_parcelamento", 0.86, entities, True, ["confirmacao_caixa_ou_compromisso"])

    if asks_purchase_decision(text):
        missing = []
        if amount is None:
            missing.append("valor_total")
        if any(word in text for word in ["parcela", "parcelado", "parcelar", "x"]) and not installments:
            missing.append("numero_parcelas")
        if missing:
            return structured_intent("pedir_dados_faltantes", 0.88, entities, False, missing)
        return structured_intent("avaliar_compra", 0.92, entities, False, [])

    if any(phrase in text for phrase in ["quanto posso gastar", "posso gastar ate", "gastar ate o fim"]):
        return structured_intent("quanto_posso_gastar", 0.9, entities, False, [])

    if any(phrase in text for phrase in ["saldo livre", "saldo real", "saldo comprometido", "saldo projetado"]):
        return structured_intent("consultar_saldo_livre", 0.93, entities, False, [])

    if any(phrase in text for phrase in ["relatorio financeiro", "resumo financeiro", "explicar meu mes", "explique meu mes"]):
        return structured_intent("gerar_relatorio_financeiro", 0.9, entities, False, [])

    if "vida financeira" in text or "saude financeira" in text or any(word in text for word in ["melhorou", "piorou"]):
        return structured_intent("avaliar_saude_financeira", 0.88, entities, False, [])

    if any(word in text for word in ["cortar", "reduzir", "economizar", "cortes"]):
        return structured_intent("sugerir_cortes", 0.86, entities, False, [])

    return structured_intent("desconhecida", 0.0, entities, False, [])


def purchase_decision(conn: Connection, routed: dict) -> dict:
    position = financial_position(conn, routed["entities"]["periodo"])
    amount = float(routed["entities"]["valor"])
    installments = routed["entities"].get("parcelas") or 1
    description = routed["entities"].get("descricao") or "Compra planejada"
    category = classify(description, -abs(amount)).category
    installment_amount = round(amount / installments, 2)
    is_installment = installments > 1

    if is_installment:
        monthly_impact = installment_amount
        cash_impact = 0.0
        projected_after = position["saldo_projetado"] - monthly_impact
        free_after = position["saldo_livre"]
    else:
        monthly_impact = 0.0
        cash_impact = amount
        projected_after = position["saldo_projetado"] - amount
        free_after = position["saldo_livre"] - amount

    ratio = (monthly_impact / position["renda_base"] * 100) if position["renda_base"] and is_installment else None
    committed_after = position["compromisso_mensal"] + monthly_impact + position["aporte_metas_mensal"]
    committed_ratio = (committed_after / position["renda_base"] * 100) if position["renda_base"] else None

    level, verdict, reasons = purchase_verdict(position, free_after, projected_after, ratio, committed_ratio, is_installment)
    calculated = {
        "amount": round(amount, 2),
        "description": description,
        "category": category,
        "installments": installments,
        "installmentAmount": installment_amount,
        "paymentMode": "parcelado" if is_installment else "avista",
        "cashImpact": round(cash_impact, 2),
        "monthlyImpact": round(monthly_impact, 2),
        "realBalance": position["saldo_real"],
        "committedBalance": position["saldo_comprometido"],
        "freeBalance": position["saldo_livre"],
        "freeBalanceAfter": round(free_after, 2),
        "projectedBalance": position["saldo_projetado"],
        "projectedBalanceAfter": round(projected_after, 2),
        "monthlyIncome": position["renda_base"],
        "monthlyCommitments": position["compromisso_mensal"],
        "goalMonthlyRequired": position["aporte_metas_mensal"],
        "installmentIncomeShare": round(ratio, 1) if ratio is not None else None,
        "committedIncomeShareAfter": round(committed_ratio, 1) if committed_ratio is not None else None,
        "level": level,
        "verdict": verdict,
        "reasons": reasons,
    }

    fact = (
        f"compra {description} de {money(amount)}"
        + (f" em {installments}x de {money(installment_amount)}" if is_installment else " a vista")
        + f". Saldo real {money(position['saldo_real'])}; saldo livre {money(position['saldo_livre'])}; saldo projetado {money(position['saldo_projetado'])}."
    )
    meaning = (
        f"Impacto mensal: {money(monthly_impact)}." if is_installment else f"Impacto imediato no caixa: {money(cash_impact)}."
    )
    risk = "; ".join(reasons) if reasons else "risco baixo com dados atuais."
    action = purchase_action(level, is_installment)
    answer = standard_answer(fact, meaning, risk, action)

    return response("purchase_decision", routed, calculated, answer, purchase_actions(level, is_installment), 0.9)


def financial_position(conn: Connection, month_key: str | None = None) -> dict:
    summary = summarize(conn, month_key)
    kpis = summary["kpis"]
    commitments = list_commitments(conn)
    expense_commitments = [item for item in commitments if item["kind"] == "expense" and item["active"]]
    income_commitments = [item for item in commitments if item["kind"] == "income" and item["active"]]
    monthly_commitments = round(sum(float(item["amount"]) for item in expense_commitments), 2)
    fixed_income = round(sum(float(item["amount"]) for item in income_commitments), 2)
    future_debt = round(
        sum(float(item["amount"]) * int(item["installments_remaining"] or 1) for item in expense_commitments),
        2,
    )
    goals = summary.get("goals", [])
    goal_monthly = round(sum(float(goal.get("monthlyRequired") or 0) for goal in goals), 2)
    income_base = float(kpis["income"] or fixed_income or 0)
    real_balance = float(kpis["balance"])
    projected = float(kpis["projectedBalance"]) + fixed_income - monthly_commitments - goal_monthly
    free_balance = real_balance - monthly_commitments
    monthly_margin = income_base - float(kpis["expenses"]) - monthly_commitments - goal_monthly
    committed_ratio = ((monthly_commitments + goal_monthly) / income_base * 100) if income_base else None
    return {
        "periodo": summary["month"],
        "saldo_real": round(real_balance, 2),
        "saldo_comprometido": monthly_commitments,
        "divida_futura_parcelas": future_debt,
        "saldo_livre": round(free_balance, 2),
        "saldo_projetado": round(projected, 2),
        "renda_base": round(income_base, 2),
        "receitas_mes": float(kpis["income"]),
        "despesas_mes": float(kpis["expenses"]),
        "compromisso_mensal": monthly_commitments,
        "receita_fixa_mensal": fixed_income,
        "aporte_metas_mensal": goal_monthly,
        "margem_mensal_estimada": round(monthly_margin, 2),
        "percentual_renda_comprometida": round(committed_ratio, 1) if committed_ratio is not None else None,
        "risco_caixa": kpis["cashRisk"],
        "score_saude": kpis["healthScore"],
        "status_saude": kpis["healthLabel"],
        "alertas": summary.get("alerts", [])[:5],
        "categorias_criticas": summary.get("categorySpend", [])[:5],
        "acoes": summary.get("actionPlan", [])[:5],
    }


def balance_position_answer(conn: Connection, routed: dict) -> dict:
    position = financial_position(conn, routed["entities"]["periodo"])
    fact = (
        f"saldo real {money(position['saldo_real'])}; saldo comprometido proximos 30 dias {money(position['saldo_comprometido'])}; "
        f"saldo livre {money(position['saldo_livre'])}; saldo projetado {money(position['saldo_projetado'])}."
    )
    meaning = "Saldo real e dinheiro hoje. Saldo livre desconta compromissos futuros proximos. Saldo projetado estima fim do mes."
    risk = "Risco maior se saldo livre ou projetado ficar negativo."
    action = "Use saldo livre para decidir compra, nao saldo real isolado."
    return response("balance_position", routed, position, standard_answer(fact, meaning, risk, action), ["Usar saldo livre para decisoes.", "Registrar compromissos futuros."], 0.92)


def spending_room_answer(conn: Connection, routed: dict) -> dict:
    position = financial_position(conn, routed["entities"]["periodo"])
    safe = max(min(position["saldo_livre"], position["saldo_projetado"], max(position["margem_mensal_estimada"], 0)), 0)
    conservative = round(safe * 0.65, 2)
    calculated = {**position, "gasto_seguro_estimado": conservative}
    fact = f"saldo livre {money(position['saldo_livre'])}; margem mensal estimada {money(position['margem_mensal_estimada'])}; limite prudente {money(conservative)}."
    meaning = "Esse valor preserva compromissos e reduz chance de fechar negativo."
    risk = "Se ainda faltam receitas ou despesas nao registradas, esse numero fica incompleto."
    action = "Gaste abaixo do limite prudente e registre qualquer parcela antes."
    return response("spending_room", routed, calculated, standard_answer(fact, meaning, risk, action), ["Registrar gastos pendentes.", "Evitar parcela nova se saldo livre baixo."], 0.88)


def financial_health_answer(conn: Connection, routed: dict) -> dict:
    summary = summarize(conn, routed["entities"]["periodo"])
    position = financial_position(conn, routed["entities"]["periodo"])
    reasons = health_reasons(summary, position)
    actions = health_actions(summary, position)
    calculated = {
        "score": summary["kpis"]["healthScore"],
        "status": summary["kpis"]["healthLabel"],
        "motivos": reasons,
        "acoes_recomendadas": actions,
        "position": position,
    }
    fact = f"score {calculated['score']}/100 ({calculated['status']}); renda {money(summary['kpis']['income'])}; despesas {money(summary['kpis']['expenses'])}; saldo livre {money(position['saldo_livre'])}."
    meaning = "Saude financeira combina renda, gasto, compromissos, saldo projetado, metas e alertas."
    risk = reasons[0] if reasons else "Sem risco forte detectado nos dados atuais."
    action = actions[0] if actions else "Manter registro diario e revisar antes de assumir parcelas."
    return response("financial_health", routed, calculated, standard_answer(fact, meaning, risk, action), actions, 0.9)


def monthly_report_answer(conn: Connection, routed: dict) -> dict:
    summary = summarize(conn, routed["entities"]["periodo"])
    position = financial_position(conn, routed["entities"]["periodo"])
    previous = previous_month_key(summary["month"])
    category = summary["categorySpend"][0] if summary["categorySpend"] else None
    calculated = {
        "periodo": summary["month"],
        "mes_anterior": previous,
        "receitas": summary["kpis"]["income"],
        "despesas": summary["kpis"]["expenses"],
        "saldo_liquido": summary["kpis"]["net"],
        "saldo_real": position["saldo_real"],
        "saldo_livre": position["saldo_livre"],
        "saldo_projetado": position["saldo_projetado"],
        "maior_categoria": category,
        "alertas": summary.get("alerts", [])[:5],
        "acoes": summary.get("actionPlan", [])[:5],
    }
    fact = f"{summary['month']}: receitas {money(summary['kpis']['income'])}, despesas {money(summary['kpis']['expenses'])}, liquido {money(summary['kpis']['net'])}."
    meaning = f"Saldo livre estimado: {money(position['saldo_livre'])}. Maior categoria: {category['category']} ({money(category['value'])})" if category else f"Saldo livre estimado: {money(position['saldo_livre'])}."
    risk = first_alert(summary) or "Sem alerta critico com dados atuais."
    action = first_action(summary) or "Continuar registrando receitas, despesas e compromissos."
    return response("monthly_report", routed, calculated, standard_answer(fact, meaning, risk, action), [action], 0.9)


def cut_suggestions_answer(conn: Connection, routed: dict) -> dict:
    summary = summarize(conn, routed["entities"]["periodo"])
    categories = summary.get("categorySpend", [])[:5]
    actions = []
    for item in categories[:3]:
        target = round(float(item["value"]) * 0.15, 2)
        actions.append(f"Reduzir {item['category']} em ate {money(target)}.")
    if summary.get("recurring"):
        rec = summary["recurring"][0]
        actions.append(f"Revisar recorrencia {rec['merchant']} ({money(rec['annualizedCost'])}/ano).")
    calculated = {"categorias": categories, "recorrencias": summary.get("recurring", [])[:5], "acoes_recomendadas": actions}
    fact = "Categorias com maior impacto: " + (", ".join(f"{item['category']} {money(item['value'])}" for item in categories[:3]) if categories else "sem dados suficientes.")
    meaning = "Corte bom mexe em categoria grande ou recorrencia, nao em microgasto isolado."
    risk = "Cortar sem ver categoria pode atacar gasto pequeno e nao mudar saldo."
    action = actions[0] if actions else "Importe mais dados ou registre despesas por alguns dias."
    return response("cut_suggestions", routed, calculated, standard_answer(fact, meaning, risk, action), actions, 0.86)


def purchase_verdict(position: dict, free_after: float, projected_after: float, ratio: float | None, committed_ratio: float | None, installment: bool) -> tuple[str, str, list[str]]:
    reasons = []
    if not position["renda_base"]:
        reasons.append("renda mensal nao cadastrada; analise incompleta")
    if free_after < 0:
        reasons.append("saldo livre ficaria negativo")
    if projected_after < 0:
        reasons.append("saldo projetado ficaria negativo")
    if ratio is not None and ratio > 30:
        reasons.append("parcela passa de 30% da renda")
    elif ratio is not None and ratio > 15:
        reasons.append("parcela pesa mais de 15% da renda")
    if committed_ratio is not None and committed_ratio > 55:
        reasons.append("compromissos ficariam acima de 55% da renda")
    elif committed_ratio is not None and committed_ratio > 40:
        reasons.append("compromissos ficariam acima de 40% da renda")

    if any("negativo" in item or "30%" in item or "55%" in item for item in reasons):
        return "danger", "Segurar compra", reasons
    if reasons or (installment and position["risco_caixa"] != "Baixo"):
        if not reasons:
            reasons.append(f"risco de caixa atual: {position['risco_caixa']}")
        return "warn", "Comprar so com ajuste", reasons
    return "ok", "Compra cabe nos dados atuais", reasons


def health_reasons(summary: dict, position: dict) -> list[str]:
    reasons = []
    ratio = position.get("percentual_renda_comprometida")
    if ratio is not None and ratio >= 40:
        reasons.append(f"Compromissos futuros representam {ratio}% da renda base.")
    if position["saldo_projetado"] < 0:
        reasons.append("Saldo projetado esta negativo.")
    if summary.get("categorySpend"):
        top = summary["categorySpend"][0]
        reasons.append(f"Maior categoria: {top['category']} com {money(top['value'])}.")
    for alert in summary.get("alerts", [])[:2]:
        reasons.append(alert["title"])
    return reasons[:5]


def health_actions(summary: dict, position: dict) -> list[str]:
    actions = [item["title"] for item in summary.get("actionPlan", [])[:3]]
    if position["saldo_livre"] < 0:
        actions.insert(0, "Nao assumir novas parcelas ate saldo livre ficar positivo.")
    if not actions:
        actions.append("Manter registros e revisar saldo livre antes de compras.")
    return actions[:5]


def structured_intent(intent: str, confidence: float, entities: dict, needs_confirmation: bool, missing_fields: list[str]) -> dict:
    return {
        "intent": intent,
        "confidence": confidence,
        "entities": entities,
        "needs_confirmation": needs_confirmation,
        "missing_fields": missing_fields,
    }


def response(intent: str, routed: dict, calculated: dict, answer: str, actions: list[str], confidence: float) -> dict:
    return {
        "answer": answer,
        "actions": actions,
        "confidence": confidence,
        "mode": "assistant_layer",
        "intent": intent,
        "data": {
            **calculated,
            "structured_intent": routed,
            "safety": {
                "raw_statement_sent_to_ai": False,
                "calculation_owner": "python",
                "requires_confirmation": routed["needs_confirmation"],
                "missing_fields": routed["missing_fields"],
            },
        },
    }


def missing_data_response(routed: dict, actions: list[str] | None = None) -> dict:
    fields = routed["missing_fields"] or ["dados objetivos"]
    answer = standard_answer(
        "faltam dados para responder com seguranca.",
        "Sem esses dados eu posso interpretar errado ou alterar saldo indevidamente.",
        "Nao vou inventar valor, parcela, prazo ou impacto no caixa.",
        "Envie: " + ", ".join(fields) + ".",
    )
    return response(
        "missing_financial_data",
        routed,
        {},
        answer,
        actions or [f"Informar {field}." for field in fields],
        routed["confidence"] or 0.82,
    )


def standard_answer(found: str, meaning: str, risk: str, action: str) -> str:
    return f"Dados: {found}\nSignificado: {meaning}\nRisco/oportunidade: {risk}\nAcao: {action}"


def purchase_action(level: str, installment: bool) -> str:
    if level == "danger":
        return "nao comprar agora; primeiro aumentar saldo livre ou renda."
    if level == "warn":
        return "comprar somente se for essencial e compensar no maior gasto variavel."
    return "se for util, comprar sem travar reserva; registrar parcela/saida depois."


def purchase_actions(level: str, installment: bool) -> list[str]:
    if level == "danger":
        return ["Adiar compra.", "Aumentar entrada ou reduzir parcelas.", "Recalcular depois de registrar renda/despesas."]
    if level == "warn":
        return ["Comprar so se for essencial.", "Cortar categoria variavel no mesmo valor.", "Evitar nova parcela este mes."]
    if installment:
        return ["Salvar compromisso futuro se comprar.", "Registrar cada parcela paga.", "Revisar saldo livre mensalmente."]
    return ["Registrar despesa se comprar.", "Manter reserva intacta.", "Revisar saldo livre depois."]


def asks_purchase_decision(text: str) -> bool:
    decision_terms = ["posso comprar", "consigo comprar", "vale comprar", "compensa comprar", "posso pagar", "consigo pagar", "assumir divida", "assumir dívida"]
    if any(term in text for term in decision_terms):
        return True
    return "comprar" in text and any(word in text for word in ["posso", "vale", "compensa", "devo", "plano"])


def asks_installment_registration(text: str) -> bool:
    has_purchase = any(word in text for word in ["comprei", "parcelei", "financiei"])
    has_installment = bool(extract_installments(text)) or any(word in text for word in ["parcelado", "parcelas"])
    has_decision = asks_purchase_decision(text)
    has_paid = any(word in text for word in ["paguei", "debito", "saiu", "lance", "lancar"])
    return has_purchase and has_installment and not has_decision and not has_paid


def extract_amount(message: str) -> float | None:
    patterns = [
        rf"r\$\s*({NUMBER_RE})",
        rf"({NUMBER_RE})\s*(?:reais|real)",
        rf"(?:de|por|valor|custa|custando)\s*(?:r\$\s*)?({NUMBER_RE})",
        r"\b(\d{3,}(?:[.,]\d{1,2})?)\b(?!\s*x)",
    ]
    for pattern in patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if not match:
            continue
        try:
            return abs(parse_amount(match.group(1)))
        except ValueError:
            continue
    return None


def extract_installments(text: str) -> int | None:
    patterns = [r"\b(?:em\s*)?(\d{1,3})\s*x\b", r"\b(\d{1,3})\s*parcelas?\b"]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            value = int(match.group(1))
            return value if value > 1 else None
    return None


def extract_purchase_description(text: str) -> str:
    match = re.search(r"\bcomprar\s+(?:um|uma|o|a)?\s*(.+?)(?=\s+(?:de|por|em\s+\d+x|r\$|qual|posso|vale|antes|ate)|$)", text)
    if match:
        description = clean_description(match.group(1))
        if description:
            return description
    match = re.search(r"\b(?:celular|carro|moto|notebook|pc|curso|viagem|byd king)\b", text)
    if match:
        return clean_description(match.group(0))
    return "Compra planejada"


def clean_description(value: str) -> str:
    clean = re.sub(r"\b(um|uma|o|a|meu|minha)\b", " ", value)
    clean = re.sub(r"\s+", " ", clean).strip(" .,;:-")
    return clean[:80] if clean else ""


def infer_month_key(text: str) -> str:
    today = date.today()
    if "mes passado" in text:
        return previous_month_key(today.strftime("%Y-%m"))
    match = re.search(r"\b(20\d{2})[-/](\d{1,2})\b", text)
    if match:
        return f"{match.group(1)}-{int(match.group(2)):02d}"
    return today.strftime("%Y-%m")


def first_alert(summary: dict) -> str | None:
    alerts = summary.get("alerts", [])
    if not alerts:
        return None
    alert = alerts[0]
    return f"{alert['title']}: {alert.get('detail') or alert.get('message') or ''}".strip()


def first_action(summary: dict) -> str | None:
    actions = summary.get("actionPlan", [])
    if not actions:
        return None
    action = actions[0]
    return f"{action['title']}: {action.get('detail', '')}".strip()


def soft_normalize(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("r $", "r$")
    text = re.sub(r"[()?!;:,]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


NUMBER_RE = r"\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:[.,]\d{1,2})?"
