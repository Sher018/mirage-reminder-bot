"""Парсинг Excel-файла с расписанием."""
from datetime import date, time, datetime, timedelta

def _local_year():
    from bot.utils import get_local_now
    return get_local_now().year
from io import BytesIO
import re
from typing import Optional

import openpyxl


def parse_time(value) -> Optional[time]:
    """Преобразует значение в time."""
    if value is None:
        return None
    if isinstance(value, time):
        return value
    if isinstance(value, datetime):
        return value.time()
    if isinstance(value, (int, float)):
        if value < 1:
            hours = int(value * 24)
            minutes = int((value * 24 % 1) * 60)
            return time(hours, minutes)
        return None
    if isinstance(value, str):
        for fmt in ("%H:%M", "%H.%M", "%H,%M"):
            try:
                return datetime.strptime(value.strip(), fmt).time()
            except ValueError:
                continue
        parts = value.replace(".", ":").replace(",", ":").split(":")
        if len(parts) >= 2:
            try:
                return time(int(parts[0]), int(parts[1]))
            except (ValueError, IndexError):
                pass
    return None


def parse_shift_cell(value) -> Optional[tuple[time, time]]:
    """
    Парсит ячейку смены вида "10:00-00:00" или "09:00-22:00".
    Возвращает (shift_start, shift_end) или None.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s or s.upper() in ("ВЫХОДНОЙ", "ВЫХ", "В", "-", "—"):
        return None
    # Формат HH:MM-HH:MM или HH.MM-HH.MM
    m = re.match(r"(\d{1,2})[.:](\d{2})\s*[-–—]\s*(\d{1,2})[.:](\d{2})", s.replace(" ", ""))
    if m:
        try:
            start = time(int(m.group(1)), int(m.group(2)))
            end = time(int(m.group(3)), int(m.group(4)))
            return (start, end)
        except (ValueError, IndexError):
            pass
    return None


def parse_date(value) -> Optional[date]:
    """Преобразует значение в date."""
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, (int, float)):
        try:
            return datetime.fromordinal(datetime(1900, 1, 1).toordinal() + int(value) - 2).date()
        except (ValueError, OverflowError):
            return None
    if isinstance(value, str):
        for fmt in ("%d.%m.%Y", "%d.%m.%y", "%Y-%m-%d", "%d/%m/%Y"):
            try:
                return datetime.strptime(value.strip(), fmt).date()
            except ValueError:
                continue
    return None


def normalize_username(val: str) -> str:
    """Добавляет @ если нет."""
    s = str(val).strip()
    if s and not s.startswith("@"):
        return f"@{s}"
    return s


# Дни недели: пн=0, вт=1, ..., вс=6
DAY_NAMES = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


def find_day_columns(rows: list) -> dict[int, int]:
    """
    Находит индексы колонок для каждого дня (пн, вт, ...).
    Возвращает {0: col_idx, 1: col_idx, ...} где 0=пн, 6=вс.
    """
    result = {}
    for row in rows[:3]:  # Смотрим первые 3 строки
        for i, cell in enumerate(row):
            if cell is None:
                continue
            val = str(cell).strip().lower()
            for day_idx, day_name in enumerate(DAY_NAMES):
                if val == day_name or val == day_name + ".":
                    result[day_idx] = i
    return result


def find_employee_column(rows: list) -> Optional[int]:
    """Колонка с сотрудниками (@username или имя). Ищем колонку с @ в данных."""
    for col in range(10):
        for row in rows[2:12]:  # Данные начинаются с 3-й строки
            if col >= len(row):
                continue
            cell = row[col]
            if cell and str(cell).strip().startswith("@"):
                return col
    return 1  # По умолчанию вторая колонка (после №)


def find_week_start(rows: list) -> Optional[date]:
    """Ищет дату начала недели в первых строках или в тексте 'Неделя 10.03-16.03'."""
    for row in rows[:3]:
        for cell in row[:8]:
            if cell is None:
                continue
            s = str(cell).strip()
            d = parse_date(cell)
            if d:
                monday = d - timedelta(days=d.weekday())
                return monday
            # "Неделя 10.03-16.03" или "10.03-16.03"
            m = re.search(r"(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?", s)
            if m:
                try:
                    day, month = int(m.group(1)), int(m.group(2))
                    year = int(m.group(3)) if m.group(3) else _local_year()
                    if year < 100:
                        year += 2000
                    d = date(year, month, day)
                    monday = d - timedelta(days=d.weekday())
                    return monday
                except (ValueError, IndexError):
                    pass
    return None


def parse_schedule_excel(file_bytes: bytes, week_start: Optional[date] = None) -> list[dict]:
    """
    Парсит Excel в формате "График работы на неделю":
    - Строки = сотрудники, колонки = дни (пн, вт, ср...)
    - Ячейка = "HH:MM-HH:MM" (начало-конец смены)

    Если week_start не передан, ищет дату в файле. Если не найдена — возвращает [].
    """
    wb = openpyxl.load_workbook(BytesIO(file_bytes), read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()

    if not rows:
        return []

    day_cols = find_day_columns(rows)
    if not day_cols:
        return []

    emp_col = find_employee_column(rows)
    if emp_col is None:
        emp_col = 1

    start_date = week_start or find_week_start(rows)
    if not start_date:
        return []  # Вызывающий код должен запросить дату

    result = []
    for row_idx, row in enumerate(rows[2:], start=2):  # Пропускаем заголовки
        if not row or len(row) <= max(day_cols.values(), default=0):
            continue

        emp_val = row[emp_col] if emp_col < len(row) else None
        if not emp_val:
            continue

        username = normalize_username(str(emp_val))
        if not username or username == "@":
            continue

        for day_idx, col_idx in day_cols.items():
            if col_idx >= len(row):
                continue
            shift = parse_shift_cell(row[col_idx])
            if not shift:
                continue

            shift_start, shift_end = shift
            d = start_date + timedelta(days=day_idx)
            result.append({
                "date": d,
                "day_of_week": DAY_NAMES[day_idx],
                "username": username,
                "full_name": str(emp_val).strip() if not str(emp_val).startswith("@") else None,
                "shift_start": shift_start,
                "shift_end": shift_end,
            })

    return result
