"""Работа с периодами отчётности: «сегодня», «неделя», «месяц», «год».

Вынесено отдельно, потому что одни и те же периоды нужны и веб-фильтрам,
и аналитике, и командам Telegram-бота.
"""
from datetime import date, timedelta

from django.utils import timezone

ALL = 'all'
DAY = 'day'
WEEK = 'week'
MONTH = 'month'
YEAR = 'year'
CUSTOM = 'custom'

PERIOD_CHOICES = [
    (MONTH, 'Текущий месяц'),
    (DAY, 'Сегодня'),
    (WEEK, 'Текущая неделя'),
    (YEAR, 'Текущий год'),
    (ALL, 'Всё время'),
    (CUSTOM, 'Произвольный период'),
]


def period_range(period, today=None):
    """Возвращает границы периода (начало, конец) включительно.

    Для «всего времени» границы — None: фильтр по дате не применяется.
    Периоды календарные: неделя начинается с понедельника, месяц — с первого числа.
    """
    today = today or timezone.localdate()

    if period == DAY:
        return today, today
    if period == WEEK:
        start = today - timedelta(days=today.weekday())
        return start, start + timedelta(days=6)
    if period == MONTH:
        start = today.replace(day=1)
        return start, _end_of_month(start)
    if period == YEAR:
        return date(today.year, 1, 1), date(today.year, 12, 31)
    return None, None


def _end_of_month(first_day):
    """Последний день месяца, которому принадлежит first_day."""
    if first_day.month == 12:
        return date(first_day.year, 12, 31)
    return date(first_day.year, first_day.month + 1, 1) - timedelta(days=1)


def period_label(period, start, end):
    """Человеческая подпись периода для заголовков и отчётов.

    Произвольный период может быть открытым с любой стороны: пользователь
    вправе указать только «с» или только «по».
    """
    if start is None and end is None:
        return 'за всё время'
    if start is None:
        return f'по {end:%d.%m.%Y}'
    if end is None:
        return f'с {start:%d.%m.%Y}'
    if start == end:
        return f'за {start:%d.%m.%Y}'
    return f'с {start:%d.%m.%Y} по {end:%d.%m.%Y}'
