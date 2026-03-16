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
        usernames = [s.username for s in schedules]

    if not schedules:
        return
    end_min = shift_start.hour * 60 + shift_start.minute + CONFIRM_WINDOW_MINUTES
    end_h, end_m = divmod(end_min, 60)
    deadline = f"{end_h:02d}:{end_m:02d}"

    # Напоминание за 5 мин до смены: список работников + просьба отметиться
    text = (
        f"⏰ Через {REMINDER_BEFORE_MINUTES} мин начинается смена {shift_start.hour:02d}:{shift_start.minute:02d}\n\n"
        f"📅 На смене:\n"
        f"• {shift_start.hour:02d}:{shift_start.minute:02d}: {', '.join(usernames)}\n\n"
        f"Подтвердите присутствие (геолокация обязательна, можно ответить на это сообщение):\n"
        f"• Отметиться можно до {deadline} ({CONFIRM_WINDOW_MINUTES} мин с начала смены).\n"
        f"• Фото — по желанию."
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
        schedule_ids = [s.id for s in schedules]
        confirmed_ids = {c.schedule_id for c in session.query(Confirmation).filter(
            Confirmation.schedule_id.in_(schedule_ids),
        ).all()}
        usernames = [s.username for s in schedules if s.id not in confirmed_ids]

    if not usernames:
        return
    end_min = shift_start.hour * 60 + shift_start.minute + CONFIRM_WINDOW_MINUTES
    end_h, end_m = divmod(end_min, 60)
    deadline = f"{end_h:02d}:{end_m:02d}"

    text = (
        f"📅 Смена {shift_start.hour:02d}:{shift_start.minute:02d}\n"
        f"• {shift_start.hour:02d}:{shift_start.minute:02d}: {', '.join(usernames)}\n\n"
        f"Подтвердите присутствие (ответьте на это сообщение геолокацией). "
        f"У вас {CONFIRM_WINDOW_MINUTES} мин с начала смены — до {deadline}!"
    )

    try:
        await app.bot.send_message(chat_id=chat_id, text=text)
        logger.info("Повторное напоминание в группу %s: смена %s, не подтвердили: %s", chat_id, shift_start, usernames)
    except Exception as e:
        logger.exception("Ошибка отправки повторного напоминания: %s", e)


# Кэш отправленных напоминаний за текущий день, чтобы не дублировать при расширенном окне
_sent_first_reminder: set[tuple[date, time]] = set()


def _clear_sent_cache_if_new_day(today: date) -> None:
    """Очищает кэш при смене дня."""
    global _sent_first_reminder
    if not _sent_first_reminder:
        return
    # Если в кэше есть даты не сегодня — очищаем
    if any(d != today for d, _ in _sent_first_reminder):
        _sent_first_reminder = set()


# За сколько минут до начала смены отправить напоминание
REMINDER_BEFORE_MINUTES = 5


async def job_reminders() -> None:
    """Отправляет напоминания: за 5 мин до смены и через 7 мин после начала — тем, кто не подтвердил."""
    now = get_local_now()
    today = get_local_today()
    current_min = now.hour * 60 + now.minute

    init_db()
    with get_db() as session:
        times = session.query(Schedule.shift_start).filter(
            Schedule.date == today,
        ).distinct().all()

    _clear_sent_cache_if_new_day(today)
    times_list = [t for (t,) in times]

    if not times_list:
        logger.info(
            "job_reminders: нет смен на %s (локальное время %s). Загрузите расписание на эту дату через /schedule.",
            today,
            now.strftime("%H:%M"),
        )
        return

    chat_id = get_group_chat_id()
    if not chat_id:
        logger.warning(
            "job_reminders: группа не задана. Смены на %s в %s — напоминания не отправляются. /setgroup или GROUP_ID в .env",
            today,
            [t.strftime("%H:%M") for t in times_list],
        )
        return

    # Диагностика: когда ждать напоминания (раз в 10 мин чтобы не засорять лог)
    if now.minute % 10 == 0:
        reminder_minutes = [start_min - REMINDER_BEFORE_MINUTES for start_min in (tt.hour * 60 + tt.minute for tt in times_list)]
        logger.info(
            "job_reminders: локальное время %s (минута дня=%s). Напоминания за 5 мин до смены в минуты: %s. Смены: %s",
            now.strftime("%H:%M"),
            current_min,
            reminder_minutes,
            [t.strftime("%H:%M") for t in times_list],
        )

    for t in times_list:
        start_min = t.hour * 60 + t.minute
        # За REMINDER_BEFORE_MINUTES мин до начала смены — напоминание со списком и просьбой отметиться
        reminder_at_min = start_min - REMINDER_BEFORE_MINUTES
        if reminder_at_min >= 0 and current_min == reminder_at_min:
            if (today, t) not in _sent_first_reminder:
                logger.info("Отправка напоминания за 5 мин до смены %s", t.strftime("%H:%M"))
                await send_reminders_for_time(t)
                _sent_first_reminder.add((today, t))
            break
        # Через 7 мин после начала — повторное напоминание тем, кто не подтвердил
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
