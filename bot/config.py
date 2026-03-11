"""Конфигурация бота из переменных окружения."""
import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [
    int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()
]
_group_id = os.getenv("GROUP_ID")
GROUP_ID = int(_group_id) if _group_id and _group_id.strip() else None
RESTAURANT_LAT = float(os.getenv("RESTAURANT_LAT", "52.2758"))
RESTAURANT_LON = float(os.getenv("RESTAURANT_LON", "104.2774"))
GEO_RADIUS_M = int(os.getenv("GEO_RADIUS_M", "500"))
CONFIRM_WINDOW_MINUTES = int(os.getenv("CONFIRM_WINDOW_MINUTES", "15"))
# Через сколько минут — повторное напоминание тем, кто не подтвердил
LATE_REMINDER_MINUTES = int(os.getenv("LATE_REMINDER_MINUTES", "7"))

# 4 напоминания в день (HH:MM)
REMINDER_1 = os.getenv("REMINDER_1", "09:00")
REMINDER_2 = os.getenv("REMINDER_2", "10:00")
REMINDER_3 = os.getenv("REMINDER_3", "12:00")
REMINDER_4 = os.getenv("REMINDER_4", "15:00")

REMINDER_TIMES = [REMINDER_1, REMINDER_2, REMINDER_3, REMINDER_4]

# Недельный отчёт админу
WEEKLY_REPORT_DAY = int(os.getenv("WEEKLY_REPORT_DAY", "0"))  # 0=Вс, 1=Пн, ..., 6=Сб
WEEKLY_REPORT_TIME = os.getenv("WEEKLY_REPORT_TIME", "00:00")

# Часовой пояс (сервер в UTC, бот для Иркутска)
# Asia/Irkutsk = UTC+8, Europe/Moscow = UTC+3
TIMEZONE = os.getenv("TIMEZONE", "Asia/Irkutsk")
