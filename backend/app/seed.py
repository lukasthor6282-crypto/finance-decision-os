from __future__ import annotations

import random
from datetime import date, timedelta
from sqlite3 import Connection

from .classifier import classify
from .repository import insert_transaction


BASE_DESCRIPTIONS = [
    ("Salário ACME", 12800.0, "Renda"),
    ("Aluguel apartamento", -3150.0, "Moradia"),
    ("Condomínio", -720.0, "Moradia"),
    ("Internet fibra", -139.9, "Moradia"),
    ("Netflix", -55.9, "Assinaturas"),
    ("Spotify", -21.9, "Assinaturas"),
    ("Mercado Pão de Açúcar", -410.0, "Mercado"),
    ("Uber", -38.0, "Transporte"),
    ("iFood almoço", -64.0, "Alimentação"),
    ("Farmácia", -92.0, "Saúde"),
    ("Tesouro Direto aporte", -1200.0, "Investimentos"),
]


def has_transactions(conn: Connection) -> bool:
    row = conn.execute("SELECT COUNT(*) AS count FROM transactions").fetchone()
    return bool(row["count"])


def seed_demo(conn: Connection) -> None:
    if has_transactions(conn):
        return

    rng = random.Random(42)
    today = date.today()
    first = today.replace(day=1) - timedelta(days=150)
    rows = []

    for month_offset in range(6):
        month_start = (first + timedelta(days=32 * month_offset)).replace(day=1)
        for description, amount, category in BASE_DESCRIPTIONS:
            day = min(26, 2 + rng.randrange(0, 24))
            tx_date = month_start.replace(day=day)
            drift = 1 + rng.uniform(-0.08, 0.09)
            tx_amount = round(amount * drift, 2) if amount < 0 else amount
            rows.append((tx_date.isoformat(), description, tx_amount, category, "Principal", "seed"))

        for _ in range(rng.randrange(10, 17)):
            description = rng.choice(
                [
                    "Restaurante bairro",
                    "Mercado Extra",
                    "Uber corrida",
                    "Café trabalho",
                    "Amazon compra",
                    "Academia",
                    "Pet shop",
                ]
            )
            amount = -round(rng.uniform(18, 260), 2)
            tx_date = month_start + timedelta(days=rng.randrange(1, 27))
            category = classify(description, amount).category
            rows.append((tx_date.isoformat(), description, amount, category, "Cartão", "seed"))

    for tx_date, description, amount, category, account, source in rows:
        insert_transaction(
            conn,
            {
                "date": tx_date,
                "description": description,
                "amount": amount,
                "category": category,
                "account": account,
            },
            source=source,
        )
    conn.executemany(
        "INSERT OR IGNORE INTO budgets (category, monthly_limit) VALUES (?, ?)",
        [
            ("Mercado", 1900),
            ("Alimentação", 1200),
            ("Transporte", 850),
            ("Moradia", 4300),
            ("Assinaturas", 320),
            ("Saúde", 700),
        ],
    )
    conn.executemany(
        """
        INSERT INTO goals (name, target_amount, current_amount, due_date, priority)
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            ("Reserva de emergência", 60000, 24500, (today + timedelta(days=300)).isoformat(), "alta"),
            ("Viagem anual", 18000, 6800, (today + timedelta(days=180)).isoformat(), "média"),
        ],
    )
