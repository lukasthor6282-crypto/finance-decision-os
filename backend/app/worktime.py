from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .normalization import parse_amount


WEEKDAYS = {
    "segunda": 0,
    "segunda feira": 0,
    "terca": 1,
    "terca feira": 1,
    "quarta": 2,
    "quarta feira": 2,
    "quinta": 3,
    "quinta feira": 3,
    "sexta": 4,
    "sexta feira": 4,
    "sabado": 5,
    "domingo": 6,
}


@dataclass(frozen=True)
class ParsedWorkSession:
    date: str
    start_time: str | None
    end_time: str | None
    break_minutes: int
    hourly_rate: float
    hours: float
    gross_amount: float
    description: str
    notes: str


def parse_hourly_rate(message: str) -> float | None:
    text = normalize_work_text(message)
    patterns = [
        r"(?:ganho|recebo|cobro)\s*(?:r\$\s*)?(\d+(?:[.,]\d{1,2})?)\s*(?:r\$|reais|real)?\s*(?:por hora|/h|hora)\b",
        r"(?:minha hora(?:\s+e)?|valor da hora(?:\s+e)?|hora(?:\s+e)?)\s*(?:r\$\s*)?(\d+(?:[.,]\d{1,2})?)\s*(?:r\$|reais|real)?",
        r"(?:r\$\s*)?(\d+(?:[.,]\d{1,2})?)\s*(?:r\$|reais|real)?\s*(?:por hora|/h)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue
        try:
            return parse_amount(match.group(1))
        except ValueError:
            continue
    return None


def parse_work_session_message(message: str, known_hourly_rate: float | None = None) -> ParsedWorkSession | None:
    original = " ".join(message.strip().split())
    text = normalize_work_text(original)
    if not any(word in text for word in ["trabalhei", "trabalho", "jornada", "turno", "hora trabalhada", "horas trabalhadas"]):
        return None

    hourly_rate = parse_hourly_rate(original) or known_hourly_rate
    if hourly_rate is None:
        return None

    tx_date = infer_work_date(text)
    break_minutes = infer_break_minutes(text)
    interval = extract_time_interval(text)
    if interval:
        start_time, end_time = interval
        minutes = minutes_between(start_time, end_time) - break_minutes
        if minutes <= 0:
            return None
        hours = round(minutes / 60, 4)
        description = f"Horas trabalhadas {start_time}-{end_time}"
    else:
        duration = extract_duration_hours(text)
        if duration is None:
            return None
        start_time = None
        end_time = None
        hours = max(round(duration - (break_minutes / 60), 4), 0)
        if hours <= 0:
            return None
        description = "Horas trabalhadas"

    gross_amount = round(hours * hourly_rate, 2)
    return ParsedWorkSession(
        date=tx_date,
        start_time=start_time,
        end_time=end_time,
        break_minutes=break_minutes,
        hourly_rate=round(hourly_rate, 2),
        hours=hours,
        gross_amount=gross_amount,
        description=description,
        notes=f"registrado pelo chat: {original}",
    )


def infer_work_date(text: str) -> str:
    clean = normalize_work_text(text)
    today = date.today()
    if "hoje" in clean:
        return today.isoformat()
    if "ontem" in clean:
        return (today - timedelta(days=1)).isoformat()
    if "anteontem" in clean:
        return (today - timedelta(days=2)).isoformat()

    match = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b", clean)
    if match:
        day = int(match.group(1))
        month = int(match.group(2))
        year = int(match.group(3) or today.year)
        if year < 100:
            year += 2000
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            return today.isoformat()

    for label, weekday in WEEKDAYS.items():
        if re.search(rf"\b{re.escape(label)}\b", clean):
            delta = (today.weekday() - weekday) % 7
            return (today - timedelta(days=delta)).isoformat()

    return today.isoformat()


def infer_break_minutes(text: str) -> int:
    clean = normalize_work_text(text)
    match = re.search(r"(?:intervalo|pausa|almoco)\D{0,12}(\d{1,3})\s*(?:min|minutos)", clean)
    if match:
        return int(match.group(1))
    match = re.search(r"(\d{1,3})\s*(?:min|minutos)\D{0,12}(?:intervalo|pausa|almoco)", clean)
    if match:
        return int(match.group(1))
    return 0


def extract_time_interval(text: str) -> tuple[str, str] | None:
    clean = normalize_work_text(text)
    patterns = [
        r"(?:das|de)\s*(\d{1,2}(?::\d{2}|h\d{0,2})?)\s*(?:ate|as|a)\s*(?:as)?\s*(\d{1,2}(?::\d{2}|h\d{0,2})?)",
        r"(\d{1,2}(?::\d{2}|h\d{0,2})?)\s*(?:ate|as|a)\s*(\d{1,2}(?::\d{2}|h\d{0,2})?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, clean, re.IGNORECASE)
        if not match:
            continue
        start = normalize_time(match.group(1))
        end = normalize_time(match.group(2))
        if start and end:
            return start, end
    return None


def extract_duration_hours(text: str) -> float | None:
    clean = normalize_work_text(text)
    match = re.search(r"(\d+(?:[.,]\d{1,2})?)\s*(?:horas|hora)\b", clean)
    if match:
        return parse_amount(match.group(1))
    match = re.search(r"\b(\d{1,2})h(?:(\d{1,2}))?\b", clean)
    if match:
        hours = int(match.group(1))
        minutes = int(match.group(2) or 0)
        return hours + minutes / 60
    return None


def normalize_time(value: str) -> str | None:
    clean = value.strip().lower().replace(" ", "")
    match = re.fullmatch(r"(\d{1,2})(?::|h)?(\d{0,2})", clean)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    if hour > 23 or minute > 59:
        return None
    return f"{hour:02d}:{minute:02d}"


def minutes_between(start_time: str, end_time: str) -> int:
    start = datetime.strptime(start_time, "%H:%M")
    end = datetime.strptime(end_time, "%H:%M")
    if end <= start:
        end += timedelta(days=1)
    return int((end - start).total_seconds() // 60)


def normalize_work_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = normalized.lower()
    normalized = normalized.replace("às", "as").replace("à", "a")
    normalized = normalized.replace("at?", "ate").replace("?s", "as")
    normalized = re.sub(r"\b(\d{1,2})\s*(?:a;|a:|;|,|\.)\s*(\d{2})\b", r"\1:\2", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def is_work_correction_message(message: str) -> bool:
    text = normalize_work_text(message)
    return any(
        marker in text
        for marker in [
            "falei errado",
            "mandei errado",
            "errei",
            "errado de novo",
            "errado denovo",
            "errado denov",
            "denovo",
            "denov",
            "de novo",
            "corrigir",
            "corrige",
            "correcao",
            "na verdade",
            "era ate",
            "foi ate",
            "trabalhei ate",
        ]
    )
