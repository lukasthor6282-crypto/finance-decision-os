from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime


def normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-zA-Z0-9\s]", " ", text.lower())
    text = re.sub(r"\b\d{2,}\b", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def merchant_from_description(description: str) -> str:
    clean = normalize_text(description)
    if not clean:
        return "desconhecido"
    tokens = [token for token in clean.split() if token not in {"pix", "debito", "credito", "compra", "pagamento"}]
    return " ".join(tokens[:4]) or clean


def parse_date(value: str) -> str:
    clean = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(clean, fmt).date().isoformat()
        except ValueError:
            pass
    raise ValueError("invalid date")


def parse_amount(value: str | float | int) -> float:
    if isinstance(value, (float, int)):
        return float(value)

    clean = str(value).strip().replace("R$", "").replace(" ", "")
    negative = clean.startswith("-") or (clean.startswith("(") and clean.endswith(")"))
    clean = clean.strip("()").lstrip("+").lstrip("-")

    if "," in clean and "." in clean:
        clean = clean.replace(".", "").replace(",", ".")
    elif "," in clean:
        clean = clean.replace(",", ".")
    elif "." in clean:
        parts = clean.split(".")
        if len(parts) > 1 and len(parts[-1]) == 3 and all(part.isdigit() for part in parts):
            clean = "".join(parts)

    amount = float(clean)
    return -amount if negative else amount


def transaction_fingerprint(date: str, description: str, amount: float, account: str) -> str:
    merchant = merchant_from_description(description)
    payload = f"{date}|{merchant}|{round(float(amount), 2):.2f}|{normalize_text(account)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
