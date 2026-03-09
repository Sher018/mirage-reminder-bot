"""Точка входа — запуск бота."""
import re
import sys
import logging

# Сразу выводим в консоль (без буфера)
def _log(s: str) -> None:
    print(s, flush=True)

_log("Загрузка модулей...")

from telegram import Update, BotCommand
from telegram.error import BadRequest
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

from bot.config import BOT_TOKEN, ADMIN_IDS
from bot.database import init_db
from bot.handlers.schedule import schedule_command, receive_document, receive_week_date
from bot.handlers.confirmations import handle_location, handle_photo
from bot.handlers.today_status import cmd_today, cmd_status, cmd_next_days, callback_button, get_reply_keyboard, BUTTON_TO_CMD, BUTTON_TEXTS
from bot.handlers.setgroup import setgroup_command
from bot.handlers.group_utils import groupid_command, test_command, check_command, remind_command, remind_tomorrow_command
from bot.services.scheduler import setup_scheduler

_log("Модули загружены.")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def start(update: Update, context) -> None:
    """Обработчик команды /start."""
    from telegram import ReplyKeyboardRemove
    from bot.handlers.today_status import get_reply_keyboard
    text = (
        "👋 Привет! Я бот-напоминалка для Ресторанного комплекса Мираж.\n\n"
        "📋 Админ: /schedule → Excel (строки=сотрудники, колонки=дни, ячейка=10:00-00:00)\n\n"
        "⏰ Напоминания в группу. 15 мин на подтверждение. Геолокация — обязательно.\n\n"
        "📊 Воскресенье 00:00 — отчёт админу.\n\n"
        "📌 В группе: /setgroup — сохранить группу"
    )
    user_id = update.effective_user.id if update.effective_user else 0
    reply_markup = get_reply_keyboard() if user_id in ADMIN_IDS else ReplyKeyboardRemove()
    await update.message.reply_text(text, reply_markup=reply_markup)


def main() -> None:
    """Запуск бота."""
    _log("Инициализация БД...")
    init_db()

    if not BOT_TOKEN:
        print("❌ Ошибка: BOT_TOKEN не задан в .env")
        return

    async def post_init(app: Application) -> None:
        """Меню команд при нажатии / в чате."""
        await app.bot.set_my_commands([
            BotCommand("start", "Начать"),
            BotCommand("schedule", "Загрузить расписание"),
            BotCommand("today", "Кто сегодня работает"),
            BotCommand("next", "График на следующие дни"),
            BotCommand("status", "Статус подтверждений"),
            BotCommand("remind", "Отправить напоминание в группу"),
            BotCommand("remind_tomorrow", "Напоминание на завтра в группу"),
            BotCommand("setgroup", "Сохранить группу (в группе)"),
            BotCommand("test", "Тест отправки в группу"),
            BotCommand("check", "Проверка настроек"),
        ])

    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработка ошибок: 'Message to be replied not found' — не падать."""
        err = context.error
        if isinstance(err, BadRequest) and "message to be replied not found" in str(err).lower():
            logger.warning("Сообщение для ответа удалено или недоступно: %s", err)
            return
        logger.exception("Ошибка в обработчике: %s", err)

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_error_handler(error_handler)

    # Команды
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("schedule", schedule_command))
    app.add_handler(CommandHandler("raspisanie", schedule_command))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("setgroup", setgroup_command))
    app.add_handler(CommandHandler("groupid", groupid_command))
    app.add_handler(CommandHandler("test", test_command))
    app.add_handler(CommandHandler("next", cmd_next_days))
    app.add_handler(CommandHandler("check", check_command))
    app.add_handler(CommandHandler("remind", remind_command))
    app.add_handler(CommandHandler("remind_tomorrow", remind_tomorrow_command))

    # Документы (Excel) — только в личку
    app.add_handler(MessageHandler(
        filters.Document.ALL & filters.ChatType.PRIVATE,
        receive_document,
    ))
    # Закреплённые кнопки (текст → команда)
    async def handle_button(update: Update, context) -> None:
        if not update.message or not update.message.text:
            return
        key = update.message.text.strip().lower()
        cmd = BUTTON_TO_CMD.get(key)
        if not cmd:
            return
        if cmd == "schedule":
            from bot.handlers.schedule import schedule_command
            await schedule_command(update, context)
        elif cmd == "today":
            await cmd_today(update, context)
        elif cmd == "status":
            await cmd_status(update, context)
        elif cmd == "remind":
            await remind_command(update, context)
        elif cmd == "remind_tomorrow":
            await remind_tomorrow_command(update, context)
        elif cmd == "check":
            await check_command(update, context)
        elif cmd == "next_days":
            await cmd_next_days(update, context)

    # Кнопка «Напоминание» — отдельный обработчик (regex: с эмодзи или без)
    remind_pattern = re.compile(r"^(⏰\s*)?[Нн]апоминание\s*$", re.IGNORECASE)
    app.add_handler(MessageHandler(
        filters.Regex(remind_pattern),
        remind_command,
    ))
    # Остальные кнопки
    other_buttons = [t for t in BUTTON_TEXTS if "напоминание" not in t.lower()]
    app.add_handler(MessageHandler(
        filters.Text(other_buttons),
        handle_button,
    ))
    # Дата понедельника после загрузки файла
    app.add_handler(MessageHandler(
        filters.TEXT & filters.ChatType.PRIVATE,
        receive_week_date,
    ))

    # Геолокация и фото — только в группах (group и supergroup)
    group_filter = filters.ChatType.GROUP | filters.ChatType.SUPERGROUP
    app.add_handler(MessageHandler(filters.LOCATION & group_filter, handle_location))
    app.add_handler(MessageHandler(filters.PHOTO & group_filter, handle_photo))

    # Inline-кнопки (только в личке админа)
    app.add_handler(CallbackQueryHandler(callback_button))

    # Планировщик
    setup_scheduler(app)

    _log("Бот запущен. Остановка: Ctrl+C")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        _log("\nБот остановлен (Ctrl+C).")
    except Exception:
        print("\n" + "=" * 50, flush=True)
        print("ОШИБКА при запуске бота:", flush=True)
        print("=" * 50, flush=True)
        import traceback
        traceback.print_exc()
        print("=" * 50, flush=True)
    try:
        input("\nНажмите Enter, чтобы закрыть окно...")
    except (EOFError, KeyboardInterrupt):
        pass
