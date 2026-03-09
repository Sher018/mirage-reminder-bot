"""Планировщик напоминаний и недельного отчёта."""
import logging
from datetime import datetime, date, time, timedelta
from contextlib import contextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session

from bot.config import (
    BOT_TOKEN, ADMIN_IDS, GROUP_ID, WEEKLY_REPORT_DAY, WEEKLY_REPORT_TIME,
    CONFIRM_WINDOW_MINUTES, LATE_REMINDER_MINUTES,
)
from bot.database import SessionLocal, init_db
from bot.models import Schedule, Confirmation, WorkGroup
from bot.utils import get_local_today, get_local_now

logger = logging.getLogger(__name__)

# Глобальные ссылки для доступа из main
application = None
scheduler = None


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


def get_group_chat_id() -> int | None:
    """ID группы для отправки напоминаний."""
    if GROUP_ID:
        return GROUP_ID
    session = SessionLocal()
    try:
        wg = session.query(WorkGroup).first()
        return wg.chat_id if wg else None
    finally:
        session.close()


async def send_reminders_for_time(shift_start: time, app=None) -> None:
    """Отправляет напоминание для смен с началом в shift_start. app — для вызова из хендлера."""
    app = app or application
    if not app or not BOT_TOKEN:
        return

    chat_id = get_group_chat_id()
    if not chat_id:
        logger.warning("Группа не сохранена. Выполните /setgroup в группе или добавьте GROUP_ID в .env")
        return

    init_db()
    today = get_local_today()
    with get_db() as session:
        schedules = session.query(Schedule).filter(
            Schedule.date == today,
            Schedule.shift_start == shift_start,
        ).all()

    if not schedules:
        return

    usernames = [s.username for s in schedules]
    end_min = shift_start.hour * 60 + shift_start.minute + CONFIRM_WINDOW_MINUTES
    end_h, end_m = divmod(end_min, 60)
    deadline = f"{end_h:02d}:{end_m:02d}"

    # Формат: график смены + просьба отметиться
    text = (
        f"📅 Смена {shift_start.hour:02d}:{shift_start.minute:02d}\n"
        f"• {shift_start.hour:02d}:{shift_start.minute:02d}: {', '.join(usernames)}\n\n"
        f"Подтвердите присутствие:\n"
        f"• Геолокация — обязательно\n"
        f"• Фото — по желанию\n\n"
        f"⏰ До {deadline}"
    )

    try:
        await app.bot.send_message(chat_id=chat_id, text=text)
        logger.info("Напоминание отправлено в группу %s: смена %s", chat_id, shift_start)
    except Exception as e:
        logger.exception("Ошибка отправки в группу %s: %s. Проверьте: бот в группе? GROUP_ID верный?", chat_id, e)




async def send_late_reminder(shift_start: time) -> None:
    """Повторное напоминание тем, кто ещё не подтвердил (через 7 мин после начала смены)."""
    app = application
    if not app or not BOT_TOKEN:
        return

    chat_id = get_group_chat_id()
    if not chat_id:
        return

    init_db()
    today = get_local_today()
    with get_db() as session:
        schedules = session.query(Schedule).filter(
            Schedule.date == today,
            Schedule.shift_start == shift_start,
        ).all()
        confirmed_ids = {c.schedule_id for c in session.query(Confirmation).filter(
            Confirmation.schedule_id.in_([s.id for s in schedules])
        ).all()}

    not_confirmed = [s for s in schedules if s.id not in confirmed_ids]
    if not not_confirmed:
        return

    usernames = [s.username for s in not_confirmed]
    end_min = shift_start.hour * 60 + shift_start.minute + CONFIRM_WINDOW_MINUTES
    end_h, end_m = divmod(end_min, 60)
    deadline = f"{end_h:02d}:{end_m:02d}"

    text = (
        f"📅 Смена {shift_start.hour:02d}:{shift_start.minute:02d}\n"
        f"• {shift_start.hour:02d}:{shift_start.minute:02d}: {', '.join(usernames)}\n\n"
        f"Подтвердите присутствие (геолокация обязательна). До {deadline}!"
    )

    try:
        await app.bot.send_message(chat_id=chat_id, text=text)
        logger.info("Повторное напоминание в группу %s: смена %s, не подтвердили: %s", chat_id, shift_start, usernames)
    except Exception as e:
        logger.exception("Ошибка отправки повторного напоминания: %s", e)


async def job_reminders() -> None:
    """Проверяет расписание и отправляет напоминания: в начале смены и через 7 мин тем, кто не подтвердил."""
    now = get_local_now()
    current_min = now.hour * 60 + now.minute

    init_db()
    today = get_local_today()
    with get_db() as session:
        times = session.query(Schedule.shift_start).filter(
            Schedule.date == today,
        ).distinct().all()

    for (t,) in times:
        start_min = t.hour * 60 + t.minute
        # В начале смены — первое напоминание
        if current_min == start_min:
            await send_reminders_for_time(t)
            break
        # Через 7 мин — повторное напоминание тем, кто не подтвердил
        if current_min == start_min + LATE_REMINDER_MINUTES:
            await send_late_reminder(t)
            break


async def job_weekly_report() -> None:
    """Недельный отчёт админу."""
    app = application
    if not app or not BOT_TOKEN:
        return

    now = get_local_now()
    end_date = now.date()
    start_date = end_date - timedelta(days=6)

    init_db()
    with get_db() as session:
        schedules = session.query(Schedule).filter(
            Schedule.date >= start_date,
            Schedule.date <= end_date,
        ).all()

        confirmations = session.query(Confirmation).join(Schedule).filter(
            Schedule.date >= start_date,
            Schedule.date <= end_date,
        ).all()

    late_list = []
    no_confirm_list = []
    confirmed_ids = {c.schedule_id for c in confirmations}
    schedule_by_id = {s.id: s for s in schedules}

    for c in confirmations:
        if c.status == "late":
            s = schedule_by_id.get(c.schedule_id)
            if s:
                late_list.append((s, c))

    for s in schedules:
        if s.id not in confirmed_ids:
            no_confirm_list.append(s)

    lines = [f"📊 Отчёт за неделю {start_date.strftime('%d.%m')} — {end_date.strftime('%d.%m')}\n"]

    if late_list:
        lines.append("⚠️ ОПОЗДАНИЯ:")
        for s, c in late_list:
            name = s.full_name or s.username
            lines.append(f"• {name} — {s.date.strftime('%d.%m')}, смена {s.shift_start.hour:02d}:{s.shift_start.minute:02d}: опоздание {c.late_minutes} мин")

    if no_confirm_list:
        lines.append("\n❌ НЕ ПОДТВЕРДИЛИ:")
        for s in no_confirm_list:
            name = s.full_name or s.username
            lines.append(f"• {name} — {s.date.strftime('%d.%m')}, смена {s.shift_start.hour:02d}:{s.shift_start.minute:02d}")

    if not late_list and not no_confirm_list:
        lines.append("✅ Все подтвердили вовремя!")

    text = "\n".join(lines)

    for admin_id in ADMIN_IDS:
        try:
            await app.bot.send_message(chat_id=admin_id, text=text)
        except Exception as e:
            logger.exception("Failed to send report to admin %s: %s", admin_id, e)


def setup_scheduler(app) -> AsyncIOScheduler:
    """Настраивает планировщик."""
    global application, scheduler
    application = app
    scheduler = AsyncIOScheduler()

    # Каждую минуту проверяем, нужно ли отправить напоминание
    scheduler.add_job(job_reminders, CronTrigger(minute="*"), id="reminders")

    # Недельный отчёт: воскресенье 00:00
    day = WEEKLY_REPORT_DAY  # 0 = воскресенье
    hour, minute = map(int, WEEKLY_REPORT_TIME.split(":"))
    scheduler.add_job(
        job_weekly_report,
        CronTrigger(day_of_week=day, hour=hour, minute=minute),
        id="weekly_report",
    )

    scheduler.start()
    logger.info("Scheduler started")
    return scheduler
