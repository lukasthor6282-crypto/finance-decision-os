from __future__ import annotations

import csv
import io
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .normalization import parse_amount, parse_date


CANONICAL_FIELDS = {
    "date": "data",
    "description": "descricao",
    "amount": "valor",
    "account": "banco/conta",
    "transaction_type": "tipo",
    "payment_method": "forma_pagamento",
    "category": "categoria",
    "notes": "observacao",
}

ALIASES = {
    "date": ("data", "date", "dt", "posted_at", "posted date", "data lancamento", "data transacao", "lancamento"),
    "description": ("descricao", "descrição", "description", "historico", "histórico", "memo", "name", "merchant", "detalhes"),
    "amount": ("valor", "amount", "value", "total", "montante", "valor r$", "valor brl"),
    "account": ("banco", "bank", "conta", "account", "instituicao", "instituição"),
    "transaction_type": ("tipo", "type", "tipo transacao", "tipo da transacao", "natureza", "debito credito"),
    "payment_method": ("forma pagamento", "forma de pagamento", "pagamento", "metodo pagamento", "cartao", "payment method"),
    "category": ("categoria", "category"),
    "notes": ("observacao", "observação", "notes", "nota", "comentario"),
}

REQUIRED_FIELDS = ("date", "description", "amount")


@dataclass(frozen=True)
class ImportPreview:
    columns: list[str]
    detected_mapping: dict[str, str | None]
    sample_rows: list[dict[str, str]]


@dataclass(frozen=True)
class ParsedImport:
    transactions: list[dict]
    columns: list[str]
    mapping: dict[str, str | None]
    errors: list[str]


class ImportValidationError(ValueError):
    def __init__(self, message: str, columns: list[str] | None = None, mapping: dict[str, str | None] | None = None) -> None:
        super().__init__(message)
        self.columns = columns or []
        self.mapping = mapping or {}


def preview_statement_file(filename: str, content: bytes, limit: int = 5) -> ImportPreview:
    rows = read_table(filename, content)
    columns = list(rows[0].keys()) if rows else []
    mapping = detect_mapping(columns, {})
    return ImportPreview(columns=columns, detected_mapping=mapping, sample_rows=rows[:limit])


def parse_statement_file(filename: str, content: bytes, manual_mapping: dict[str, str | None] | None = None) -> ParsedImport:
    rows = read_table(filename, content)
    columns = list(rows[0].keys()) if rows else []
    mapping = detect_mapping(columns, manual_mapping or {})
    missing = [field for field in REQUIRED_FIELDS if not mapping.get(field)]
    if missing:
        labels = ", ".join(CANONICAL_FIELDS[field] for field in missing)
        raise ImportValidationError(
            f"Mapeie as colunas obrigatorias: {labels}.",
            columns=columns,
            mapping=mapping,
        )

    transactions: list[dict] = []
    errors: list[str] = []
    for index, row in enumerate(rows, start=2):
        try:
            transactions.append(normalize_import_row(row, mapping))
        except ValueError as exc:
            errors.append(f"Linha {index}: {exc}")

    return ParsedImport(transactions=transactions, columns=columns, mapping=mapping, errors=errors)


def read_table(filename: str, content: bytes) -> list[dict[str, str]]:
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else "csv"
    if suffix in {"xlsx", "xls"}:
        return read_excel(content, suffix)
    if suffix == "csv":
        return read_csv(content)
    raise ImportValidationError("Formato nao suportado. Use CSV, XLS ou XLSX.")


def read_csv(content: bytes) -> list[dict[str, str]]:
    try:
        import pandas as pd

        frame = pd.read_csv(io.BytesIO(content), sep=None, engine="python", dtype=str, keep_default_na=False).fillna("")
        return frame_to_rows(frame)
    except ImportError:
        pass
    except Exception:
        pass

    text = decode_text(content)
    sample = text[:2048]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error as exc:
        raise ImportValidationError("Nao consegui identificar o separador do CSV. Use virgula, ponto e virgula, tab ou barra vertical.") from exc
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        raise ImportValidationError("CSV vazio ou sem cabecalho.")
    return [{key.strip(): clean_cell(value) for key, value in row.items() if key} for row in reader]


def read_excel(content: bytes, suffix: str) -> list[dict[str, str]]:
    try:
        import pandas as pd
    except ImportError as exc:
        raise ImportValidationError("Para importar Excel, instale pandas e openpyxl.") from exc

    engine = "openpyxl" if suffix == "xlsx" else None
    try:
        frame = pd.read_excel(io.BytesIO(content), dtype=str, keep_default_na=False, engine=engine).fillna("")
    except ImportError as exc:
        raise ImportValidationError("Para importar Excel, instale openpyxl para XLSX ou xlrd para XLS.") from exc
    return frame_to_rows(frame)


def frame_to_rows(frame: Any) -> list[dict[str, str]]:
    if frame.empty:
        raise ImportValidationError("Arquivo vazio.")
    frame.columns = [str(column).strip() for column in frame.columns]
    return [
        {str(key).strip(): clean_cell(value) for key, value in row.items()}
        for row in frame.to_dict(orient="records")
    ]


def detect_mapping(columns: list[str], manual_mapping: dict[str, str | None]) -> dict[str, str | None]:
    normalized_columns = {normalize_key(column): column for column in columns}
    mapping: dict[str, str | None] = {}
    for field in CANONICAL_FIELDS:
        manual_column = manual_mapping.get(field)
        if manual_column:
            resolved = resolve_column(columns, manual_column)
            if not resolved:
                raise ImportValidationError(f"Coluna mapeada nao encontrada: {manual_column}", columns=columns)
            mapping[field] = resolved
            continue

        mapping[field] = None
        for alias in ALIASES[field]:
            resolved = normalized_columns.get(normalize_key(alias))
            if resolved:
                mapping[field] = resolved
                break
    return mapping


def resolve_column(columns: list[str], value: str) -> str | None:
    if value in columns:
        return value
    normalized = normalize_key(value)
    for column in columns:
        if normalize_key(column) == normalized:
            return column
    return None


def normalize_import_row(row: dict[str, str], mapping: dict[str, str | None]) -> dict:
    date_value = value_for(row, mapping, "date")
    description = value_for(row, mapping, "description").strip()
    amount_value = value_for(row, mapping, "amount")
    if not description:
        raise ValueError("descricao vazia")

    amount = parse_amount(amount_value)
    transaction_type = normalize_transaction_type(value_for(row, mapping, "transaction_type", required=False))
    if transaction_type == "income":
        amount = abs(amount)
    elif transaction_type in {"expense", "card_payment", "investment"}:
        amount = -abs(amount)
    elif transaction_type == "refund":
        amount = abs(amount)

    account = value_for(row, mapping, "account", required=False) or "Principal"
    category = value_for(row, mapping, "category", required=False) or None
    payment = value_for(row, mapping, "payment_method", required=False)
    notes = value_for(row, mapping, "notes", required=False)
    note_parts = []
    if payment:
        note_parts.append(f"forma_pagamento: {payment}")
    if notes:
        note_parts.append(notes)

    return {
        "date": parse_import_date(date_value),
        "description": description,
        "amount": amount,
        "category": category,
        "account": account.strip() or "Principal",
        "notes": "; ".join(note_parts) or None,
        "transaction_type": transaction_type,
    }


def value_for(row: dict[str, str], mapping: dict[str, str | None], field: str, required: bool = True) -> str:
    column = mapping.get(field)
    if not column:
        if required:
            raise ValueError(f"coluna {CANONICAL_FIELDS[field]} nao mapeada")
        return ""
    value = clean_cell(row.get(column, ""))
    if required and value == "":
        raise ValueError(f"{CANONICAL_FIELDS[field]} vazio")
    return value


def parse_import_date(value: str) -> str:
    try:
        return parse_date(value)
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        pass
    try:
        import pandas as pd

        parsed = pd.to_datetime(value, dayfirst=True, errors="raise")
        return parsed.date().isoformat()
    except Exception as exc:
        raise ValueError("data invalida") from exc


def normalize_transaction_type(value: str) -> str | None:
    text = normalize_key(value)
    if not text:
        return None
    if any(word in text for word in ["receita", "entrada", "credito", "credit", "income", "pix recebido", "salario"]):
        return "income"
    if any(word in text for word in ["estorno", "refund", "reembolso"]):
        return "refund"
    if any(word in text for word in ["fatura", "cartao", "card payment"]):
        return "card_payment"
    if any(word in text for word in ["transferencia", "transfer", "ted", "doc"]):
        return "transfer"
    if any(word in text for word in ["investimento", "aplicacao", "resgate", "investment"]):
        return "investment"
    if any(word in text for word in ["despesa", "saida", "debito", "debit", "expense", "compra"]):
        return "expense"
    return None


def decode_text(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def clean_cell(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "nat", "none"}:
        return ""
    return text


def normalize_key(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-zA-Z0-9]+", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()
