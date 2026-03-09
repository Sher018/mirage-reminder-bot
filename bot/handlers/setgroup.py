"""Команда /setgroup — сохранить группу для напоминаний."""
import logging
from contextlib import contextmanager

from telegram import Update
from telegram.ext import ContextTypes, CommandHandler

from bot.config import ADMIN_IDS
from bot.utils import get_local_now
from bot.database import SessionLocal, init_db
from bot.models import WorkGroup

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


async def setgroup_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Сохраняет ID группы для напоминаний. Вызывать в группе."""
    if not update.effective_user or not update.effective_chat:
        return
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Только для администратора.")
        return
    if update.effective_chat.type not in ("group", "supergroup"):
        await update.message.reply_text("❌ Эта команда только в группе.")
        return

    chat_id = update.effective_chat.id
    init_db()
    with get_db() as session:
        wg = session.query(WorkGroup).first()
        now = get_local_now()
        if wg:
            wg.chat_id = chat_id
            wg.updated_at = now
        else:
            session.add(WorkGroup(chat_id=chat_id, created_at=now, updated_at=now))

    await update.message.reply_text(
        f"✅ Группа сохранена (ID: {chat_id}). Напоминания будут приходить сюда.",
    )
