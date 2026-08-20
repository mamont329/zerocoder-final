"""Текстовые отчёты для Telegram.

Считают то же самое, что и веб-аналитика: те же функции из analytics,
только на выходе не графики, а строки. Формат — HTML разметка Telegram.
"""
from decimal import Decimal

from django.utils import timezone

from . import analytics, periods
from .analytics import money
from .models import OperationType

# Сколько категорий показывать в сводке, чтобы сообщение оставалось читаемым
TOP_CATEGORIES = 5

# С какой доли израсходованного лимита предупреждать заранее
NEAR_LIMIT_SHARE = Decimal('0.8')


def _period_queryset(user, period):
    start, end = periods.period_range(period)
    queryset = user.transactions.all()
    if start:
        queryset = queryset.filter(date__range=(start, end))
    return queryset, start, end


def period_report(user, period):
    """Сводка за период: итоги, топ категорий и советы."""
    queryset, start, end = _period_queryset(user, period)
    title = {
        periods.DAY: 'Сегодня',
        periods.WEEK: 'Эта неделя',
        periods.MONTH: 'Этот месяц',
        periods.YEAR: 'Этот год',
    }.get(period, 'За всё время')

    summary = analytics.totals(queryset)
    lines = [
        f'<b>{title}</b> · {periods.period_label(period, start, end)}',
        '',
        f'Доходы: <b>{money(summary["income"])} ₽</b>',
        f'Расходы: <b>{money(summary["expense"])} ₽</b>',
        f'Баланс: <b>{money(summary["balance"])} ₽</b>',
    ]

    categories = analytics.expenses_by_category(queryset)
    if categories:
        lines += ['', '<b>Куда ушли деньги</b>']
        for row in categories[:TOP_CATEGORIES]:
            lines.append(f'· {row["name"]} — {money(row["total"])} ₽ ({row["percent"]:.0f}%)')
        if len(categories) > TOP_CATEGORIES:
            other = sum(row['total'] for row in categories[TOP_CATEGORIES:])
            lines.append(f'· Прочее — {money(other)} ₽')
    else:
        lines += ['', 'Расходов за этот период не было.']

    return '\n'.join(lines)


def advice_report(user, period):
    """Советы и предупреждения за период."""
    queryset, start, end = _period_queryset(user, period)
    items = analytics.build_advice(user, queryset, start, end)

    marks = {'danger': '‼️', 'warning': '⚠️', 'success': '✅', 'info': 'ℹ️'}
    lines = ['<b>Советы</b>', '']
    for item in items:
        lines.append(f'{marks.get(item.level, "•")} <b>{item.title}</b>')
        lines.append(item.text)
        lines.append('')
    return '\n'.join(lines).strip()


def find_category(user, name):
    """Категория по названию без учёта регистра.

    Сравнение делается в Python, а не запросом с iexact: SQLite приводит регистр
    только для латиницы, и «еда» не нашла бы «Еду».
    """
    target = name.strip().casefold()
    return next((c for c in user.categories.all() if c.name.casefold() == target), None)


def category_report(user, name, period=periods.MONTH):
    """Траты по конкретной категории. Название ищется без учёта регистра."""
    category = find_category(user, name)
    if category is None:
        available = ', '.join(user.categories.values_list('name', flat=True))
        return f'Категория «{name}» не найдена.\n\nВаши категории: {available}'

    queryset, start, end = _period_queryset(user, period)
    queryset = queryset.filter(category=category)
    total = analytics.totals(queryset)
    amount = total['income'] if category.type == OperationType.INCOME else total['expense']

    lines = [
        f'<b>{category.name}</b> · {periods.period_label(period, start, end)}',
        '',
        f'Всего: <b>{money(amount)} ₽</b> за {queryset.count()} операц.',
    ]

    if category.monthly_limit:
        usage = next(
            (item for item in analytics.limit_usage(user) if item['category'].pk == category.pk),
            None,
        )
        if usage:
            mark = '‼️' if usage['over'] else '✅'
            lines.append(
                f'{mark} Лимит за месяц: {money(usage["spent"])} из {money(usage["limit"])} ₽'
            )

    recent = queryset.order_by('-date', '-created_at')[:5]
    if recent:
        lines += ['', '<b>Последние операции</b>']
        for item in recent:
            note = f' — {item.description}' if item.description else ''
            lines.append(f'· {item.date:%d.%m}: {money(item.amount)} ₽{note}')

    return '\n'.join(lines)


# Подписи сравнения для каждого периода: заголовок, «текущий», «предыдущий»
COMPARISON_TITLES = {
    periods.DAY: ('Сегодня против вчера', 'Сегодня', 'Вчера'),
    periods.WEEK: ('Эта неделя против прошлой', 'Эта неделя', 'Прошлая'),
    periods.MONTH: ('Этот месяц против прошлого', 'Этот месяц', 'Прошлый'),
    periods.YEAR: ('Этот год против прошлого', 'Этот год', 'Прошлый'),
}

# Подписи кнопки — чтобы пользователь заранее видел, с чем сравнит
COMPARISON_BUTTONS = {
    periods.DAY: 'Сравнить со вчера',
    periods.WEEK: 'Сравнить недели',
    periods.MONTH: 'Сравнить месяцы',
    periods.YEAR: 'Сравнить годы',
}


def compare_periods(user, period=periods.WEEK):
    """Сравнение расходов текущего периода с предыдущим таким же.

    Период берётся у отчёта, под которым нажали кнопку: сравнивать месяц
    с неделей бессмысленно.
    """
    if period not in COMPARISON_TITLES:
        return 'Для периода «всё время» сравнивать не с чем.'

    this_start, this_end = periods.period_range(period)
    previous_start, previous_end = periods.previous_range(period)
    title, current_label, previous_label = COMPARISON_TITLES[period]

    current = analytics.totals(user.transactions.filter(date__range=(this_start, this_end)))
    previous = analytics.totals(user.transactions.filter(date__range=(previous_start, previous_end)))
    difference = current['expense'] - previous['expense']

    if difference > 0:
        verdict = f'⚠️ Расходы выросли на {money(difference)} ₽'
    elif difference < 0:
        verdict = f'✅ Расходы снизились на {money(abs(difference))} ₽'
    else:
        verdict = 'Расходы не изменились'

    def dates(start, end):
        if period == periods.YEAR:
            # Для годов даты одинаковые, различает их только год
            return f'{start:%Y}'
        return f'{start:%d.%m}' if start == end else f'{start:%d.%m}–{end:%d.%m}'

    return '\n'.join([
        f'<b>{title}</b>',
        '',
        f'{current_label} ({dates(this_start, this_end)}): {money(current["expense"])} ₽',
        f'{previous_label} ({dates(previous_start, previous_end)}): {money(previous["expense"])} ₽',
        '',
        verdict,
    ])


def daily_digest(user):
    """Короткая сводка за день для рассылки по расписанию.

    Возвращает None, если за день не было операций — молчать лучше,
    чем каждый вечер слать «сегодня 0 ₽».
    """
    queryset, start, end = _period_queryset(user, periods.DAY)
    if not queryset.exists():
        return None

    summary = analytics.totals(queryset)
    lines = [
        f'<b>Итоги дня</b> · {start:%d.%m.%Y}',
        '',
        f'Расходы: <b>{money(summary["expense"])} ₽</b>',
    ]
    if summary['income']:
        lines.append(f'Доходы: <b>{money(summary["income"])} ₽</b>')

    categories = analytics.expenses_by_category(queryset)
    if categories:
        lines.append('')
        for row in categories[:3]:
            lines.append(f'· {row["name"]} — {money(row["total"])} ₽')

    return '\n'.join(lines)


def limit_warnings(user, today=None):
    """Предупреждения о лимитах вместе с ключом события.

    Ключ содержит категорию и месяц: превышение по «Еде» в августе — одно
    событие, и повторять его каждый вечер до конца месяца незачем. По этому
    ключу рассылка отмечает отправку в истории уведомлений.
    """
    today = today or timezone.localdate()
    month = f'{today:%Y-%m}'

    warnings = []
    for usage in analytics.limit_usage(user):
        category = usage['category']
        if usage['over']:
            warnings.append((
                f'limit:{category.pk}:{month}',
                f'‼️ <b>Лимит превышен: {category.name}</b>\n'
                f'Потрачено {money(usage["spent"])} ₽ при лимите {money(usage["limit"])} ₽.',
            ))
        elif usage['share'] >= NEAR_LIMIT_SHARE:
            warnings.append((
                f'near:{category.pk}:{month}',
                f'⚠️ <b>Лимит почти исчерпан: {category.name}</b>\n'
                f'Израсходовано {usage["percent"]:.0f}%, осталось '
                f'{money(usage["limit"] - usage["spent"])} ₽.',
            ))
    return warnings
