"""Инициализация БД и сессий."""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

Base = declarative_base()

# Путь к SQLite: на Amvera — /data/bot.db (постоянное хранилище), локально — bot.db
DB_PATH = os.getenv("DATABASE_PATH") or os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "bot.db"
)
# Создать родительскую папку (на Amvera /data может не существовать при первом запуске)
db_dir = os.path.dirname(DB_PATH)
if db_dir:
    os.makedirs(db_dir, exist_ok=True)
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    """Создаёт все таблицы в БД."""
    from bot.models import Schedule, Confirmation, WorkGroup  # noqa: F401

    Base.metadata.create_all(bind=engine)


def get_session():
    """Контекстный менеджер для сессии."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
