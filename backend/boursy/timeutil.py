from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo


def utcnow() -> datetime:
    """Naive UTC timestamp (SQLite stores datetimes without a timezone)."""
    return datetime.now(UTC).replace(tzinfo=None)


def to_iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC).isoformat()


def market_today(tz: str) -> date:
    return datetime.now(ZoneInfo(tz)).date()
