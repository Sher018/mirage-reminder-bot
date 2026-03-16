"""Утилиты для работы с группой: /groupid, /test, /remind."""
import logging
from datetime import timedelta, time as time_type

from telegram import Update
from telegram.ext import ContextTypes, CommandHandler

from bot.config import ADMIN_IDS, CONFIRM_WINDOW_MINUTES
from bot.database import SessionLocal, init_db
from bot.models import Schedule, Confirmation
from bot.services.scheduler import get_group_chat_id
from bot.utils import get_local_today

logger = logging.getLogger(__name__)


def _format_schedule_with_request(schedules: list) -> str:
    """Формирует сообщение: график работы + просьба отметиться (как кнопка «Напоминание»)."""
    by_time = {}
    for s in schedules:
        key = s.shift_start.strftime("%H:%M")
        if key not in by_time:
            by_time[key] = []
        by_time[key].append(s)

    lines = ["📅 Сегодня работают:\n"]
    for t in sorted(by_time.keys()):
        users = [x.username for x in by_time[t]]
        lines.append(f"• {t}: {', '.join(users)}")

    lines.append("")
    lines.append("Подтвердите присутствие:")
    lines.append("• Геолокация — обязательно (ответьте на это сообщение)")
    lines.append("• Фото — по желанию")
    lines.append(f"⏰ У вас {CONFIRM_WINDOW_MINUTES} мин с начала смены, чтобы отметиться.")
    return "\n".join(lines)


def get_today_reminder_text() -> str | None:
    """Текст напоминания на сегодня (как кнопка «Напоминание»). None если смен нет."""
    today = get_local_today()
    session = SessionLocal()
    try:
        schedules = session.query(Schedule).filter(Schedule.date == today).order_by(Schedule.shift_start).all()
        if not schedules:
            return None
        return _format_schedule_with_request(schedules)
    finally:
        session.close()


def get_today_reminder_text_for_shift(reminder_for_shift_start: time_type) -> str | None:
    """
    Текст напоминания на сегодня перед сменой reminder_for_shift_start.
    В прошедших сменах (shift_start < reminder_for_shift_start) показываются только
    работники, которые ещё не отметились; в текущей и будущих — все.
    """
    today = get_local_today()
    session = SessionLocal()
    try:
        schedules = session.query(Schedule).filter(Schedule.date == today).order_by(Schedule.shift_start).all()
        if not schedules:
            return None
        schedule_ids = [s.id for s in schedules]
        confirmations = session.query(Confirmation).filter(Confirmation.schedule_id.in_(schedule_ids)).all()
        confirmed_ids = {c.schedule_id for c in confirmations}

        # По каждой смене (времени) — список имён: все или только не отметившиеся
        by_time: dict[str, list[str]] = {}
        for s in schedules:
            key = s.shift_start.strftime("%H:%M")
            if key not in by_time:
                by_time[key] = []
            is_past_shift = s.shift_start < reminder_for_shift_start
            if is_past_shift and s.id in confirmed_ids:
                continue  # прошедшая смена, уже отметился — не показываем
            by_time[key].append(s.username)

        lines = ["📅 Сегодня работают:\n"]
        for t in sorted(by_time.keys()):
            users = by_time[t]
            lines.append(f"• {t}: {', '.join(users) if users else '— все отметились'}")

        lines.append("")
        lines.append("Подтвердите присутствие:")
        lines.append("• Геолокация — обязательно (ответьте на это сообщение)")
        lines.append("• Фото — по желанию")
        lines.append(f"⏰ У вас {CONFIRM_WINDOW_MINUTES} мин с начала смены, чтобы отметиться.")
        return "\n".join(lines)
    finally:
        session.close()


def _format_tomorrow_reminder(schedules: list) -> str:
    """Формирует напоминание на завтра с воодушевляющим текстом."""
    by_time = {}
    for s in schedules:
        key = s.shift_start.strftime("%H:%M")
        if key not in by_time:
            by_time[key] = []
        by_time[key].append(s)

    lines = ["🌅 ЗАВТРА РАБОТАЮТ:\n"]
    for t in sorted(by_time.keys()):
        users = [x.username for x in by_time[t]]
        lines.append(f"• {t}: {', '.join(users)}")

    lines.append("")
    lines.append("⏰ Приходите вовремя — пунктуальность показывает уважение к команде и гостям!")
    lines.append("💪 Успешный день начинается с правильного старта. Будьте на месте в начале смены!")
    return "\n".join(lines)


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


async def groupid_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показывает ID группы. Вызывать в группе."""
    if not update.effective_user or not update.effective_chat:
        return
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Только для администратора.")
        return
    if update.effective_chat.type not in ("group", "supergroup"):
        await update.message.reply_text("❌ Эта команда только в группе.")
        return

    chat_id = update.effective_chat.id
    saved_id = get_group_chat_id()
    text = (
        f"🆔 ID этой группы: `{chat_id}`\n\n"
        f"Добавьте в .env:\n`GROUP_ID={chat_id}`\n\n"
        f"Или выполните /setgroup — бот сохранит группу автоматически.\n\n"
        f"Сохранено в боте: {'✅ Да' if saved_id == chat_id else '❌ Нет (выполните /setgroup)'}"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправляет тестовое напоминание в группу."""
    if not update.effective_user or not update.effective_chat:
        return
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Только для администратора.")
        return

    chat_id = get_group_chat_id()
    if not chat_id:
        await update.message.reply_text(
            "❌ Группа не сохранена.\n\n"
            "1. Добавьте бота в группу\n"
            "2. В группе выполните /setgroup\n"
            "Или добавьте GROUP_ID в .env (узнать: /groupid в группе)"
        )
        return

    try:
        init_db()
        today = get_local_today()
        session = SessionLocal()
        schedules = session.query(Schedule).filter(Schedule.date == today).limit(3).all()
        session.close()

        if schedules:
            usernames = [s.username for s in schedules[:3]]
            text = f"🧪 Тест. Сегодня работают: {', '.join(usernames)}\n\nПодтвердите геолокацией!"
        else:
            text = "🧪 Тестовое сообщение. Группа настроена, напоминания будут приходить сюда."

        await context.bot.send_message(chat_id=chat_id, text=text)
        if update.effective_chat.id == chat_id:
            await update.message.reply_text("✅ Тест отправлен в эту группу.")
        else:
            await update.message.reply_text(f"✅ Тест отправлен в группу (ID: {chat_id}).")
    except Exception as e:
        err_msg = str(e)
        logger.exception("Test send error: %s", e)
        hint = ""
        if "chat not found" in err_msg.lower() or "not found" in err_msg.lower():
            hint = "\n\n💡 Бот удалён из группы или GROUP_ID неверный. Добавьте бота в группу и выполните /setgroup."
        elif "forbidden" in err_msg.lower() or "blocked" in err_msg.lower():
            hint = "\n\n💡 Бот заблокирован или не имеет прав. Добавьте бота в группу как администратора."
        await update.message.reply_text(f"❌ Ошибка: {e}{hint}")


def _parse_shift_time(arg: str) -> time_type | None:
    """Парсит время из строки вида 09:00, 12:00, 15:00."""
    try:
        parts = arg.strip().split(":")
        if len(parts) != 2:
            return None
        h, m = int(parts[0]), int(parts[1])
        if 0 <= h <= 23 and 0 <= m <= 59:
            return time_type(h, m)
    except (ValueError, IndexError):
        pass
    return None


async def test_reminder_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Тест: отправляет в группу то же напоминание, что бот шлёт за 5 мин до смены.
    Без аргументов — как перед первой сменой (все в списке).
    С временем — как перед этой сменой: /test_reminder 12:00 (в 9:00 будут только не отметившиеся).
    """
    if not update.effective_user or not update.message:
        return
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Только для администратора.")
        return

    chat_id = get_group_chat_id()
    if not chat_id:
        await update.message.reply_text("❌ Группа не сохранена. Выполните /setgroup в группе.")
        return

    init_db()
    today = get_local_today()
    session = SessionLocal()

    shift_start: time_type | None = None
    if context.args and len(context.args) >= 1:
        shift_start = _parse_shift_time(context.args[0])
        if shift_start is None:
            await update.message.reply_text(
                "❌ Укажите время смены, например: /test_reminder 12:00"
            )
            session.close()
            return

    if shift_start is None:
        first = (
            session.query(Schedule.shift_start)
            .filter(Schedule.date == today)
            .order_by(Schedule.shift_start)
            .limit(1)
            .first()
        )
        if not first:
            session.close()
            await update.message.reply_text(
                "📋 Сегодня нет смен в расписании. Загрузите расписание через /schedule, затем снова /test_reminder."
            )
            return
        shift_start = first[0]
    session.close()

    text = get_today_reminder_text_for_shift(shift_start)
    if not text:
        await update.message.reply_text("📋 Нет расписания на сегодня. Загрузите через /schedule.")
        return

    try:
        await context.application.bot.send_message(chat_id=chat_id, text=text)
        await update.message.reply_text(
            f"✅ Тестовое напоминание отправлено в группу (как за 5 мин до смены {shift_start.hour:02d}:{shift_start.minute:02d})."
        )
    except Exception as e:
        logger.exception("Ошибка тестового напоминания: %s", e)
        await update.message.reply_text(f"❌ Ошибка: {e}")


async def remind_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправляет в группу график работы + просьбу отметиться. Работает в любое время."""
    if not update.effective_user or not update.message:
        return
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Только для администратора.")
        return

    chat_id = get_group_chat_id()
    if not chat_id:
        await update.message.reply_text("❌ Группа не сохранена. Выполните /setgroup в группе.")
        return

    init_db()
    today = get_local_today()
    session = SessionLocal()
    schedules = session.query(Schedule).filter(Schedule.date == today).order_by(Schedule.shift_start).all()
    session.close()

    if not schedules:
        await update.message.reply_text("📋 Сегодня нет смен в расписании.")
        return

    text = _format_schedule_with_request(schedules)
    try:
        await context.bot.send_message(chat_id=chat_id, text=text)
        await update.message.reply_text("✅ Напоминание отправлено в группу.")
    except Exception as e:
        logger.exception("Ошибка отправки напоминания: %s", e)
        await update.message.reply_text(f"❌ Ошибка: {e}")


async def remind_tomorrow_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправляет в группу напоминание на завтра: кто работает + воодушевляющий текст."""
    if not update.effective_user or not update.message:
        return
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Только для администратора.")
        return

    chat_id = get_group_chat_id()
    if not chat_id:
        await update.message.reply_text("❌ Группа не сохранена. Выполните /setgroup в группе.")
        return

    tomorrow = get_local_today() + timedelta(days=1)
    init_db()
    session = SessionLocal()
    schedules = session.query(Schedule).filter(Schedule.date == tomorrow).order_by(Schedule.shift_start).all()
    session.close()

    if not schedules:
        await update.message.reply_text("📋 На завтра нет смен в расписании.")
        return

    text = _format_tomorrow_reminder(schedules)
    try:
        await context.bot.send_message(chat_id=chat_id, text=text)
        await update.message.reply_text("✅ Напоминание на завтра отправлено в группу.")
    except Exception as e:
        logger.exception("Ошибка отправки напоминания на завтра: %s", e)
        await update.message.reply_text(f"❌ Ошибка: {e}")


async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Проверка настроек: группа, Privacy Mode."""
    if not update.effective_user:
        return
    if not is_admin(update.effective_user.id):
        return

    chat_id = get_group_chat_id()
    text = (
        "📋 Проверка настроек:\n\n"
        f"Группа: {'✅ ' + str(chat_id) if chat_id else '❌ Не задана'}\n\n"
    )
    if not chat_id:
        text += "Выполните /setgroup в группе или добавьте GROUP_ID в .env\n\n"

    text += (
        "⚠️ **Group Privacy** (в @BotFather):\n"
        "Должен быть **выключен** (Turn off).\n"
        "Иначе бот не получит геолокацию от работников.\n\n"
        "🧪 **Тест связи:** пусть работник напишет в группе «тест» или «проверка» — бот ответит.\n\n"
        "🧪 **Тест напоминания:** /test_reminder — отправит в группу то же сообщение, что за 5 мин до смены.\n\n"
        "💡 Пусть работники **отвечают на сообщение бота** геолокацией.\n\n"
        "/test — тест отправки в группу."
    )
    await update.message.reply_text(text, parse_mode="Markdown")
