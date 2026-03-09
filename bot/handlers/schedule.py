"""Обработчик загрузки расписания."""
import logging
import re
from datetime import datetime
from contextlib import contextmanager

from telegram import Update
from telegram.ext import ContextTypes, filters
from sqlalchemy.orm import Session

from bot.config import ADMIN_IDS
from bot.utils import get_local_now
from bot.database import SessionLocal, init_db
from bot.models import Schedule
from bot.services.excel_parser import parse_schedule_excel

logger = logging.getLogger(__name__)


@contextmanager
def get_db():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def parse_week_date(text: str):
    """Парсит ДД.ММ или ДД.ММ.ГГГГ, возвращает date понедельника."""
    if not text or not isinstance(text, str):
        return None
    from datetime import timedelta
    text = text.strip()
    for fmt in ("%d.%m.%Y", "%d.%m.%y", "%d.%m"):
        try:
            d = datetime.strptime(text, fmt)
            if fmt == "%d.%m":
                d = d.replace(year=get_local_now().year)
            monday = d.date() - timedelta(days=d.weekday())
            return monday
        except ValueError:
            continue
    return None


async def schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /schedule — просит отправить Excel."""
    if not update.effective_user:
        return
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Эта команда только для администратора.")
        return
    if update.effective_chat.type != "private":
        await update.message.reply_text(
            "📋 Отправьте расписание в **личку боту** — напишите боту в личные сообщения и отправьте Excel-файл.",
            parse_mode="Markdown",
        )
        return
    context.user_data.pop("schedule_file", None)
    context.user_data.pop("awaiting_week_start", None)
    text = (
        "📋 Отправьте Excel-файл (.xlsx) с графиком на неделю.\n\n"
        "Формат: строки = сотрудники (@username), колонки = дни (пн, вт, ср...)\n"
        "Ячейка = смена вида **10:00-00:00** (начало-конец)\n\n"
        "💡 Укажите дату понедельника в первой строке (ДД.ММ.ГГГГ) или отправьте её после файла."
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def receive_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Приём Excel-файла от админа в личку."""
    if not update.message or not update.effective_user or not update.effective_chat:
        return
    if update.effective_chat.type != "private":
        return
    if not is_admin(update.effective_user.id):
        return

    doc = update.message.document
    if not doc:
        return
    if not doc.file_name or not doc.file_name.lower().endswith((".xlsx", ".xls")):
        await update.message.reply_text("❌ Нужен файл Excel (.xlsx)")
        return

    file = await context.bot.get_file(doc.file_id)
    bytes_io = await file.download_as_bytearray()
    file_bytes = bytes(bytes_io)

    try:
        records = parse_schedule_excel(file_bytes)
    except Exception as e:
        logger.exception("Excel parse error: %s", e)
        await update.message.reply_text(f"❌ Ошибка чтения файла: {e}")
        return

    if not records:
        context.user_data["schedule_file"] = file_bytes
        context.user_data["awaiting_week_start"] = True
        await update.message.reply_text(
            "📅 В файле не указана дата. Отправьте дату понедельника, например **10.03** или **10.03.2025**.",
            parse_mode="Markdown",
        )
        return

    await _save_schedule_and_reply(update, context, records)


async def receive_week_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Приём даты понедельника после загрузки файла."""
    if not update.message or not update.effective_user or not update.effective_chat:
        return
    if update.effective_chat.type != "private":
        return
    if not is_admin(update.effective_user.id):
        return
    if not context.user_data.get("awaiting_week_start") or not context.user_data.get("schedule_file"):
        return

    week_start = parse_week_date(update.message.text)
    if not week_start:
        await update.message.reply_text("❌ Неверный формат. Укажите дату, например 10.03")
        return

    file_bytes = context.user_data.pop("schedule_file")
    context.user_data.pop("awaiting_week_start", None)

    try:
        records = parse_schedule_excel(file_bytes, week_start=week_start)
    except Exception as e:
        logger.exception("Excel parse error: %s", e)
        await update.message.reply_text(f"❌ Ошибка: {e}")
        return

    if not records:
        await update.message.reply_text("❌ Не удалось извлечь данные из файла.")
        return

    await _save_schedule_and_reply(update, context, records)


async def _save_schedule_and_reply(update: Update, context, records: list) -> None:
    init_db()
    with get_db() as session:
        session.query(Schedule).delete()
        now = get_local_now()
        for r in records:
            s = Schedule(
                date=r["date"],
                day_of_week=r.get("day_of_week"),
                username=r["username"],
                full_name=r.get("full_name"),
                shift_start=r["shift_start"],
                shift_end=r["shift_end"],
                created_at=now,
            )
            session.add(s)

    dates = sorted(set(r["date"].strftime("%d.%m") for r in records))
    await update.message.reply_text(
        f"✅ Расписание загружено!\n"
        f"📅 Записей: {len(records)}\n"
        f"📆 Период: {dates[0]} — {dates[-1]}",
    )
