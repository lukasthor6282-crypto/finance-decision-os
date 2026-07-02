from __future__ import annotations

import hashlib
from datetime import datetime

from .normalization import merchant_from_description, normalize_text


def transaction_fingerprint(
    tx_date: str,
    description: str,
    amount: float,
    account: str,
    transaction_type: str = "unknown",
) -> str:
    merchant = merchant_from_description(description)
    rounded_amount = round(float(amount), 2)
    payload = "|".join(
        [
            tx_date,
            normalize_text(merchant),
            f"{rounded_amount:.2f}",
            normalize_text(account),
            normalize_text(transaction_type),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def duplicate_group_key(tx_date: str, description: str, amount: float, account: str) -> str:
    date_bucket = tx_date[:10]
    try:
        date_bucket = datetime.fromisoformat(tx_date[:10]).date().isoformat()
    except ValueError:
        pass
    merchant = merchant_from_description(description)
    payload = f"{date_bucket}|{normalize_text(merchant)}|{abs(round(float(amount), 2)):.2f}|{normalize_text(account)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
