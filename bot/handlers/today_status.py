"""Команды /today, /status, /next_days и кнопки."""
import logging
from datetime import date, datetime, timedelta
from contextlib import contextmanager

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import ContextTypes, CallbackQueryHandler

from bot.config import ADMIN_IDS, CONFIRM_WINDOW_MINUTES
from bot.database import SessionLocal
from bot.models import Schedule, Confirmation
from bot.utils import get_local_today, get_local_now

logger = logging.getLogger(__name__)


def _get_status_icon(schedule: Schedule, confirmed_ids: set, now: datetime) -> str:
    """✅ подтвердил | ⏳ ожидает (смена не началась) | ❌ не подтвердил."""
    if schedule.id in confirmed_ids:
        return "✅"
    shift_start = schedule.shift_start
    now_min = now.hour * 60 + now.minute
    start_min = shift_start.hour * 60 + shift_start.minute
    end_min = start_min + CONFIRM_WINDOW_MINUTES
    if now_min < start_min:
        return "⏳"  # Смена ещё не началась
    if now_min <= end_min:
        return "⏳"  # Окно подтверждения активно
    return "❌"  # Окно закрыто, не подтвердил


def get_menu_keyboard():
    """Inline-кнопки под сообщениями."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Расписание", callback_data="cmd_schedule")],
        [InlineKeyboardButton("📅 Сегодня", callback_data="today")],
        [InlineKeyboardButton("📊 Статус", callback_data="status")],
    ])


# Тексты кнопок (для фильтра и маппинга)
BUTTON_TEXTS = [
    "📋 Расписание", "📅 Сегодня", "📊 Статус",
    "⏰ Напоминание", "🌅 На завтра", "🔧 Проверка", "📆 Следующие дни",
]
BUTTON_TO_CMD = {t.lower(): c for t, c in [
    ("📋 Расписание", "schedule"), ("📅 Сегодня", "today"), ("📊 Статус", "status"),
    ("⏰ Напоминание", "remind"), ("🌅 На завтра", "remind_tomorrow"), ("🔧 Проверка", "check"), ("📆 Следующие дни", "next_days"),
]}


def get_reply_keyboard():
    """Закреплённые кнопки на русском (ReplyKeyboard) — только для админов."""
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("📋 Расписание"), KeyboardButton("📅 Сегодня"), KeyboardButton("📊 Статус")],
            [KeyboardButton("⏰ Напоминание"), KeyboardButton("🌅 На завтра")],
            [KeyboardButton("🔧 Проверка"), KeyboardButton("📆 Следующие дни")],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


@contextmanager
def get_db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Кто сегодня работает (по сменам)."""
    today = get_local_today()
    with get_db() as session:
        schedules = session.query(Schedule).filter(Schedule.date == today).order_by(Schedule.shift_start).all()

    if not schedules:
        await update.message.reply_text("📅 Сегодня никого нет в расписании.")
        return

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

    await update.message.reply_text("\n".join(lines))


async def cmd_next_days(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """График на следующие дни (до 7 дней вперёд). Только для админа."""
    if not update.effective_user or not update.message:
        return
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Только для администратора.")
        return

    today = get_local_today()
    with get_db() as session:
        schedules = session.query(Schedule).filter(
            Schedule.date > today,
            Schedule.date <= today + timedelta(days=7),
        ).order_by(Schedule.date, Schedule.shift_start).all()

    if not schedules:
        await update.message.reply_text("📆 На следующие 7 дней нет записей в расписании.")
        return

    by_date = {}
    for s in schedules:
        d = s.date
        if d not in by_date:
            by_date[d] = {}
        key = s.shift_start.strftime("%H:%M")
        if key not in by_date[d]:
            by_date[d][key] = []
        by_date[d][key].append(s)

    day_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    lines = ["📆 Следующие дни:\n"]
    for d in sorted(by_date.keys()):
        day_name = day_names[d.weekday()]
        lines.append(f"📅 {d.strftime('%d.%m')} ({day_name}):")
        for t in sorted(by_date[d].keys()):
            users = [x.username for x in by_date[d][t]]
            lines.append(f"  • {t}: {', '.join(users)}")
        lines.append("")

    await update.message.reply_text("\n".join(lines).strip())


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Кто подтвердил, кто нет (для текущей смены/дня)."""
    today = get_local_today()
    now = get_local_now()
    with get_db() as session:
        schedules = session.query(Schedule).filter(Schedule.date == today).order_by(Schedule.shift_start).all()
        confirmations = session.query(Confirmation).filter(
            Confirmation.schedule_id.in_([s.id for s in schedules])
        ).all()
        confirmed_ids = {c.schedule_id for c in confirmations}
        late_minutes_by_schedule = {
            c.schedule_id: c.late_minutes for c in confirmations
            if c.status == "late" and c.late_minutes
        }

    if not schedules:
        await update.message.reply_text("📊 Сегодня нет смен в расписании.")
        return

    by_time = {}
    for s in schedules:
        key = s.shift_start.strftime("%H:%M")
        if key not in by_time:
            by_time[key] = []
        by_time[key].append(s)

    lines = ["📊 Статус подтверждений:\n"]
    lines.append("✅ подтвердил | ⏳ ожидает | ❌ не подтвердил\n")
    for t in sorted(by_time.keys()):
        lines.append(f"Смена {t}:")
        for s in by_time[t]:
            icon = _get_status_icon(s, confirmed_ids, now)
            line = f"  {icon} {s.username}"
            if s.id in late_minutes_by_schedule:
                line += f" (опоздание {late_minutes_by_schedule[s.id]} мин)"
            lines.append(line)

    await update.message.reply_text("\n".join(lines))


async def callback_today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Кнопка «Сегодня»."""
    query = update.callback_query
    if not query:
        return
    await query.answer()

    today = get_local_today()
    with get_db() as session:
        schedules = session.query(Schedule).filter(Schedule.date == today).order_by(Schedule.shift_start).all()

    if not schedules:
        try:
            await query.edit_message_text("📅 Сегодня никого нет в расписании.")
        except BadRequest as e:
            if "not modified" not in str(e).lower():
                raise
        return

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

    try:
        await query.edit_message_text("\n".join(lines))
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            raise


async def callback_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Кнопка «Статус»."""
    query = update.callback_query
    if not query:
        return
    await query.answer()

    today = get_local_today()
    now = get_local_now()
    with get_db() as session:
        schedules = session.query(Schedule).filter(Schedule.date == today).order_by(Schedule.shift_start).all()
        confirmations = session.query(Confirmation).filter(
            Confirmation.schedule_id.in_([s.id for s in schedules])
        ).all()
        confirmed_ids = {c.schedule_id for c in confirmations}
        late_minutes_by_schedule = {
            c.schedule_id: c.late_minutes for c in confirmations
            if c.status == "late" and c.late_minutes
        }

    if not schedules:
        try:
            await query.edit_message_text("📊 Сегодня нет смен в расписании.")
        except BadRequest as e:
            if "not modified" not in str(e).lower():
                raise
        return

    by_time = {}
    for s in schedules:
        key = s.shift_start.strftime("%H:%M")
        if key not in by_time:
            by_time[key] = []
        by_time[key].append(s)

    lines = ["📊 Статус подтверждений:\n"]
    lines.append("✅ подтвердил | ⏳ ожидает | ❌ не подтвердил\n")
    for t in sorted(by_time.keys()):
        lines.append(f"Смена {t}:")
        for s in by_time[t]:
            icon = _get_status_icon(s, confirmed_ids, now)
            line = f"  {icon} {s.username}"
            if s.id in late_minutes_by_schedule:
                line += f" (опоздание {late_minutes_by_schedule[s.id]} мин)"
            lines.append(line)

    try:
        await query.edit_message_text("\n".join(lines))
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            raise


async def callback_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик inline-кнопок."""
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()
    if query.data == "today":
        await callback_today(update, context)
    elif query.data == "status":
        await callback_status(update, context)
    elif query.data == "cmd_schedule":
        text = (
            "📋 Отправьте Excel-файл (.xlsx) с графиком на неделю.\n\n"
            "Формат: строки = сотрудники (@username), колонки = дни (пн, вт, ср...)\n"
            "Ячейка = смена вида **10:00-00:00** (начало-конец)\n\n"
            "💡 Укажите дату понедельника в первой строке или отправьте её после файла."
        )
        try:
            await query.edit_message_text(text, parse_mode="Markdown")
        except BadRequest as e:
            if "not modified" not in str(e).lower():
                raise
