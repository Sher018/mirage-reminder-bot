"""Обработка подтверждений (фото, геолокация)."""
import logging
from datetime import datetime, date, time, timedelta
from contextlib import contextmanager

from telegram import Update
from telegram.ext import ContextTypes, MessageHandler, filters
from sqlalchemy.orm import Session

from bot.config import ADMIN_IDS, RESTAURANT_LAT, RESTAURANT_LON, GEO_RADIUS_M, CONFIRM_WINDOW_MINUTES, TIMEZONE
from bot.utils import get_local_now, get_local_today
from zoneinfo import ZoneInfo
from bot.database import SessionLocal
from bot.models import Schedule, Confirmation
from bot.services.geo_validator import is_location_valid, get_distance_m

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


def get_active_schedules(session: Session, chat_date: date, chat_time: time) -> list[Schedule]:
    """
    Находит расписание, для которого сейчас активно окно подтверждения.
    Окно: shift_start до shift_start + CONFIRM_WINDOW_MINUTES.
    """
    from sqlalchemy import cast, Time
    # Упрощённо: ищем смены, у которых начало в пределах последних CONFIRM_WINDOW_MINUTES
    # или текущее время в окне
    all_today = session.query(Schedule).filter(Schedule.date == chat_date).all()
    result = []
    for s in all_today:
        start = s.shift_start
        end_min = start.hour * 60 + start.minute + CONFIRM_WINDOW_MINUTES
        end_h, end_m = divmod(end_min, 60)
        window_end = time(end_h, end_m)
        if start <= chat_time <= window_end:
            result.append(s)
    return result


def _username_matches(schedule_username: str, telegram_username: str) -> bool:
    """Сопоставление username: @user, user, имя — гибко."""
    s = (schedule_username or "").strip().lower().lstrip("@")
    t = (telegram_username or "").strip().lower().lstrip("@")
    if not s or not t:
        return False
    return s == t or s in t or t in s


def get_schedule_for_late(session: Session, chat_date: date, chat_time: time, username: str) -> Schedule | None:
    """Находит смену для пользователя, если он подтверждает с опозданием (после окна)."""
    all_today = session.query(Schedule).filter(Schedule.date == chat_date).all()
    for s in all_today:
        if not _username_matches(s.username, username):
            continue
        start = s.shift_start
        end_min = start.hour * 60 + start.minute + CONFIRM_WINDOW_MINUTES
        end_h, end_m = divmod(end_min, 60)
        window_end = time(end_h, end_m)
        if chat_time > window_end:
            return s
    return None


def calculate_late_minutes(shift_start: time, confirmed_at: datetime) -> int:
    """Минуты опоздания."""
    tz = ZoneInfo(TIMEZONE)
    # Оба datetime должны быть timezone-aware (иначе TypeError при вычитании)
    dt = confirmed_at if confirmed_at.tzinfo else confirmed_at.replace(tzinfo=tz)
    deadline_naive = datetime.combine(dt.date(), shift_start) + timedelta(minutes=CONFIRM_WINDOW_MINUTES)
    deadline = deadline_naive.replace(tzinfo=tz)
    delta = dt - deadline
    return max(0, int(delta.total_seconds() / 60))


def already_confirmed(session: Session, schedule_id: int) -> bool:
    return session.query(Confirmation).filter(Confirmation.schedule_id == schedule_id).first() is not None


async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка геолокации (обязательно для подтверждения)."""
    if not update.message or not update.message.location or not update.effective_user or not update.effective_chat:
        return
    if update.effective_chat.type == "private":
        return

    # Диагностика: видим ли мы геолокацию от этого пользователя
    user_id = update.effective_user.id
    uname = update.effective_user.username or update.effective_user.first_name or str(user_id)
    logger.info("Геолокация получена: user_id=%s, @%s, chat_id=%s", user_id, uname, update.effective_chat.id)

    loc = update.message.location
    user_id = update.effective_user.id
    username = update.effective_user.username or ""
    if not username:
        username = update.effective_user.first_name or str(user_id)
    if not username.startswith("@"):
        username = f"@{username}"

    now = get_local_now()
    chat_date = now.date()
    chat_time = now.time()

    dist_m = get_distance_m(loc.latitude, loc.longitude, RESTAURANT_LAT, RESTAURANT_LON)
    if dist_m > GEO_RADIUS_M:
        logger.warning("Геолокация вне радиуса: %s, расстояние %.0f м, лимит %s м", username, dist_m, GEO_RADIUS_M)
        await update.message.reply_text(
            f"❌ Геолокация не в радиусе ресторана (вы на расстоянии ~{int(dist_m)} м, нужно в пределах {GEO_RADIUS_M} м). "
            "Подойдите ближе к месту работы."
        )
        return

    with get_db() as session:
        schedules = get_active_schedules(session, chat_date, chat_time)
        if not schedules:
            schedule = get_schedule_for_late(session, chat_date, chat_time, username)
            if schedule:
                if already_confirmed(session, schedule.id):
                    await update.message.reply_text("✅ Вы уже подтвердили присутствие сегодня.")
                    return
                late_min = calculate_late_minutes(schedule.shift_start, now)
                conf = Confirmation(
                    schedule_id=schedule.id,
                    user_id=user_id,
                    username=username,
                    confirmed_at=now,
                    status="late",
                    late_minutes=late_min,
                    geo_received=True,
                    photo_received=False,
                    created_at=now,
                )
                session.add(conf)
                await update.message.reply_text(f"⚠️ Принято с опозданием на {late_min} мин.")
                return
            # Проверяем, есть ли пользователь в расписании на сегодня
            all_today = session.query(Schedule).filter(Schedule.date == chat_date).all()
            user_in_schedule = any(_username_matches(s.username, username) for s in all_today)
            if user_in_schedule:
                await update.message.reply_text(
                    "❌ Окно подтверждения для вашей смены уже закрыто. "
                    "Обратитесь к администратору для ручной отметки."
                )
            else:
                await update.message.reply_text(
                    "❌ Вы не в расписании на сегодня или ваш @username не совпадает с записью в графике."
                )
            return

        for schedule in schedules:
            if not _username_matches(schedule.username, username):
                continue
            if already_confirmed(session, schedule.id):
                await update.message.reply_text("✅ Вы уже подтвердили присутствие.")
                return
            conf = Confirmation(
                schedule_id=schedule.id,
                user_id=user_id,
                username=username,
                confirmed_at=now,
                status="on_time",
                late_minutes=0,
                geo_received=True,
                photo_received=False,
                created_at=now,
            )
            session.add(conf)
            await update.message.reply_text("✅ Принято!")
            return

        await update.message.reply_text("❌ Вы не в расписании на эту смену или уже подтвердили.")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Фото по желанию — не обязательно для подтверждения, но проверяем если есть."""
    if not update.message or not update.message.photo or not update.effective_user or not update.effective_chat:
        return
    if update.effective_chat.type == "private":
        return
    # Фото само по себе не подтверждает — нужна геолокация. Просто отвечаем.
    await update.message.reply_text(
        "📷 Фото получено. Для подтверждения присутствия отправьте **геолокацию** (обязательно).",
        parse_mode="Markdown",
    )
