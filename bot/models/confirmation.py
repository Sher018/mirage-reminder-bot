"""Модель подтверждения присутствия."""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship

from bot.database import Base


class Confirmation(Base):
    """Подтверждение присутствия: геолокация (обязательно) + фото (по желанию)."""

    __tablename__ = "confirmations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    schedule_id = Column(Integer, ForeignKey("schedules.id"), nullable=False)
    user_id = Column(Integer, nullable=False)  # Telegram user_id
    username = Column(String(100), nullable=False)
    confirmed_at = Column(DateTime, nullable=False)
    status = Column(String(20), nullable=False)  # 'on_time' | 'late'
    late_minutes = Column(Integer, default=0)  # Минуты опоздания (0 если вовремя)
    geo_received = Column(Boolean, default=True)
    photo_received = Column(Boolean, default=False)
    created_at = Column(DateTime, nullable=False)

    schedule = relationship("Schedule", back_populates="confirmations")
