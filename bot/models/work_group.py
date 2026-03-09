"""Модель рабочей группы (куда отправлять напоминания)."""
from sqlalchemy import Column, Integer, BigInteger, DateTime

from bot.database import Base


class WorkGroup(Base):
    """ID группы в Telegram для отправки напоминаний."""

    __tablename__ = "work_groups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(BigInteger, nullable=False, unique=True)  # Telegram group id (отрицательный)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)
