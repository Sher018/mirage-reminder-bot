"""Модель расписания (из Excel)."""
from sqlalchemy import Column, Integer, String, Date, Time, DateTime
from sqlalchemy.orm import relationship

from bot.database import Base


class Schedule(Base):
    """Расписание: одна запись = один сотрудник в один день на одну смену."""

    __tablename__ = "schedules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False)
    day_of_week = Column(String(10), nullable=True)  # Пн, Вт, Ср...
    username = Column(String(100), nullable=False)  # @username
    full_name = Column(String(200), nullable=True)  # ФИО (если есть в Excel)
    shift_start = Column(Time, nullable=False)
    shift_end = Column(Time, nullable=False)
    created_at = Column(DateTime, nullable=False)

    # Связь с подтверждениями
    confirmations = relationship("Confirmation", back_populates="schedule")
