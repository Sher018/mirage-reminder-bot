"""Утилиты: дата и время в часовом поясе ресторана."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

from bot.config import TIMEZONE

_tz = ZoneInfo(TIMEZONE)


def get_local_today() -> date:
    """Сегодняшняя дата в часовом поясе ресторана (Иркутск)."""
    return datetime.now(_tz).date()


def get_local_now() -> datetime:
    """Текущее время в часовом поясе ресторана."""
    return datetime.now(_tz)
