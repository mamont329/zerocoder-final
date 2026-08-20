"""Аналитика операций: агрегаты, аномалии и советы.

Модуль ничего не знает про HTTP и шаблоны — на вход queryset, на выходе числа
и текст. Поэтому теми же функциями пользуется и веб, и Telegram-бот.
"""
from dataclasses import dataclass
from decimal import Decimal

import pandas as pd
from django.db.models import Sum
from django.utils.formats import number_format

from . import periods
from .models import OperationType

ZERO = Decimal('0.00')

# Во сколько раз траты должны превысить обычные, чтобы считаться аномалией
ANOMALY_RATIO = Decimal('1.5')
# Минимальная сумма превышения: скачок с 20 до 40 рублей никого не интересует
ANOMALY_MIN_DIFF = Decimal('500.00')
# Доля в расходах, начиная с которой категория считается «съедающей бюджет»
DOMINANT_SHARE = Decimal('0.40')


@dataclass
class Advice:
    """Совет или предупреждение для пользователя.

    level: success | info | warning | danger — совпадает со статусами Bootstrap.
    """

    level: str
    title: str
    text: str


def money(value, decimals=2):
    """Сумма в русском формате: 1 234 567,89.

    Тексты советов уходят и в веб, и в Telegram, поэтому формат задаётся здесь,
    а не шаблонными фильтрами.
    """
    return number_format(value, decimal_pos=decimals, force_grouping=True)


def totals(queryset):
    """Доходы, расходы и баланс по набору операций."""
    by_type = {row['type']: row['total'] for row in queryset.values('type').annotate(total=Sum('amount'))}
    income = by_type.get(OperationType.INCOME) or ZERO
    expense = by_type.get(OperationType.EXPENSE) or ZERO
    return {'income': income, 'expense': expense, 'balance': income - expense}


def expenses_by_category(queryset):
    """Расходы по категориям, от большего к меньшему.

    Возвращает список словарей: название, сумма, доля в общих расходах.
    """
    rows = list(
        queryset.filter(type=OperationType.EXPENSE)
        .values('category__name')
        .annotate(total=Sum('amount'))
        .order_by('-total')
    )
    if not rows:
        return []

    grand_total = sum(row['total'] for row in rows)
    return [
        {
            'name': row['category__name'],
            'total': row['total'],
            'share': (row['total'] / grand_total) if grand_total else ZERO,
            'percent': float(row['total'] / grand_total * 100) if grand_total else 0.0,
        }
        for row in rows
    ]


def compare(current_queryset, previous_queryset):
    """Сопоставляет итоги двух периодов: сколько было, сколько стало, насколько.

    Рост расходов — плохо, рост доходов — хорошо, поэтому «хорошесть» изменения
    считается здесь, а не в шаблоне: там это превратилось бы в условия на условиях.
    """
    current = totals(current_queryset)
    previous = totals(previous_queryset)

    rows = []
    for key, title, growth_is_good in (
        ('income', 'Доходы', True),
        ('expense', 'Расходы', False),
        ('balance', 'Баланс', True),
    ):
        now, before = current[key], previous[key]
        difference = now - before
        # Процент считается от прошлого значения. От нуля он не определён,
        # а от отрицательного (баланс в минусе) — бессмыслен: рост на «490%»
        # от минус десяти тысяч ничего не сообщает.
        percent = float(difference / before * 100) if before > ZERO else None
        rows.append({
            'title': title,
            'current': now,
            'previous': before,
            'difference': difference,
            'percent': abs(percent) if percent is not None else None,
            'grew': difference > ZERO,
            'changed': difference != ZERO,
            'good': (difference > ZERO) == growth_is_good if difference != ZERO else None,
        })
    return rows


def timeline(queryset, start, end, freq='D'):
    """Ряды доходов и расходов по времени без пропусков в датах.

    Пустые дни заполняются нулями через pandas: иначе линия графика
    перепрыгивала бы через дни без операций и врала о динамике.
    freq: 'D' — по дням, 'ME' — по месяцам.
    """
    rows = list(queryset.values('date', 'type').annotate(total=Sum('amount')).order_by('date'))

    columns = [OperationType.INCOME, OperationType.EXPENSE]
    if not rows:
        return pd.DataFrame(columns=columns, index=pd.DatetimeIndex([], name='date'))

    frame = pd.DataFrame(rows)
    frame['date'] = pd.to_datetime(frame['date'])
    frame['total'] = frame['total'].astype(float)

    pivot = frame.pivot_table(index='date', columns='type', values='total', aggfunc='sum', fill_value=0)
    for column in columns:
        if column not in pivot:
            pivot[column] = 0.0
    pivot = pivot[columns]

    # Границы периода могут быть шире, чем даты операций — растягиваем ряд на весь период
    first = pd.Timestamp(start) if start else pivot.index.min()
    last = pd.Timestamp(end) if end else pivot.index.max()
    full_range = pd.date_range(first, last, freq='D')
    pivot = pivot.reindex(full_range, fill_value=0.0)
    pivot.index.name = 'date'

    if freq != 'D':
        pivot = pivot.resample(freq).sum()
    return pivot


def limit_usage(user):
    """Расход и лимит по категориям, где лимит задан.

    Всегда считается за текущий месяц и не зависит от выбранного фильтра:
    лимит месячный, и сравнивать его с годовой суммой расходов бессмысленно.
    """
    start, end = periods.period_range(periods.MONTH)
    spent = {
        row['category_id']: row['total']
        for row in user.transactions.filter(type=OperationType.EXPENSE, date__range=(start, end))
        .values('category_id')
        .annotate(total=Sum('amount'))
    }

    usage = []
    for category in user.categories.filter(monthly_limit__isnull=False):
        total = spent.get(category.pk, ZERO)
        share = (total / category.monthly_limit) if category.monthly_limit else ZERO
        usage.append({
            'category': category,
            'spent': total,
            'limit': category.monthly_limit,
            'share': share,
            'percent': min(float(share) * 100, 100),
            'over': total > category.monthly_limit,
        })
    return sorted(usage, key=lambda item: item['share'], reverse=True)


def find_anomalies(user, start, end):
    """Категории, где траты за период заметно выше обычного.

    «Обычное» — средний расход по этой категории за три предыдущих периода
    такой же длины. Так сравнение честное: месяц с месяцем, неделя с неделей.
    """
    if not start or not end:
        return []

    span = (end - start).days + 1
    previous_start = start - pd.Timedelta(days=span * 3).to_pytimedelta()
    previous_end = start - pd.Timedelta(days=1).to_pytimedelta()

    current = {
        row['category__name']: row['total']
        for row in user.transactions.filter(type=OperationType.EXPENSE, date__range=(start, end))
        .values('category__name').annotate(total=Sum('amount'))
    }
    previous = {
        row['category__name']: row['total']
        for row in user.transactions.filter(type=OperationType.EXPENSE, date__range=(previous_start, previous_end))
        .values('category__name').annotate(total=Sum('amount'))
    }

    anomalies = []
    for name, total in current.items():
        if name not in previous:
            continue
        average = previous[name] / 3
        difference = total - average
        if average > ZERO and total >= average * ANOMALY_RATIO and difference >= ANOMALY_MIN_DIFF:
            anomalies.append({
                'name': name,
                'total': total,
                'average': average,
                'difference': difference,
                'ratio': total / average,
            })
    return sorted(anomalies, key=lambda item: item['difference'], reverse=True)


def build_advice(user, queryset, start, end):
    """Собирает советы и предупреждения по данным периода."""
    advice = []
    summary = totals(queryset)
    categories = expenses_by_category(queryset)

    if summary['expense'] == ZERO and summary['income'] == ZERO:
        return [Advice('info', 'Пока нечего анализировать',
                       'Добавьте операции за этот период — появятся графики и советы.')]

    # 1. Превышение лимитов — самое важное, поэтому первым.
    # Лимиты всегда про текущий месяц, поэтому в тексте это проговаривается.
    for usage in limit_usage(user):
        if usage['over']:
            advice.append(Advice(
                'danger',
                f'Лимит превышен: {usage["category"]}',
                f'В этом месяце потрачено {money(usage["spent"])} ₽ при лимите {money(usage["limit"])} ₽ — '
                f'превышение на {money(usage["spent"] - usage["limit"])} ₽.',
            ))
        elif usage['share'] >= Decimal('0.8'):
            advice.append(Advice(
                'warning',
                f'Лимит почти исчерпан: {usage["category"]}',
                f'В этом месяце израсходовано {usage["percent"]:.0f}% лимита — осталось '
                f'{money(usage["limit"] - usage["spent"])} ₽.',
            ))

    # 2. Резкий рост трат по категории
    for anomaly in find_anomalies(user, start, end):
        advice.append(Advice(
            'warning',
            f'Резкий рост расходов: {anomaly["name"]}',
            f'Потрачено {money(anomaly["total"])} ₽ — это в {anomaly["ratio"]:.1f} раза больше обычного '
            f'({money(anomaly["average"])} ₽ за такой же период).',
        ))

    # 3. Баланс периода
    if summary['balance'] < ZERO:
        advice.append(Advice(
            'danger', 'Расходы превысили доходы',
            f'За период потрачено на {money(abs(summary["balance"]))} ₽ больше, чем получено.',
        ))
    elif summary['income'] > ZERO:
        saved = summary['balance'] / summary['income']
        if saved >= Decimal('0.2'):
            advice.append(Advice(
                'success', 'Хороший запас',
                f'Отложено {saved * 100:.0f}% доходов — {money(summary["balance"])} ₽.',
            ))

    # 4. Категория, съедающая бюджет
    if categories and categories[0]['share'] >= DOMINANT_SHARE:
        leader = categories[0]
        advice.append(Advice(
            'info', f'Основная статья расходов: {leader["name"]}',
            f'На неё уходит {leader["share"] * 100:.0f}% всех трат — {money(leader["total"])} ₽.',
        ))

    if not advice:
        advice.append(Advice('success', 'Всё в порядке',
                             'Лимиты соблюдаются, резких скачков расходов нет.'))
    return advice
