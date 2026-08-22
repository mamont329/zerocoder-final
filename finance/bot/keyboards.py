"""Клавиатуры бота."""
from math import ceil

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from ..reports import COMPARISON_BUTTONS

# Telegram не умеет красить кнопки, поэтому расход и доход различаются
# кружками: красный — деньги ушли, зелёный — пришли.
ADD_EXPENSE = '🔴 Добавить трату'
ADD_INCOME = '🟢 Добавить доход'
TODAY = 'Сегодня'

# Постоянная строка под полем ввода: два частых действия и быстрый отчёт.
# Остальное живёт в меню команд, чтобы не занимать экран.
MAIN_MENU = ReplyKeyboardMarkup(
    keyboard=[[
        KeyboardButton(text=ADD_EXPENSE),
        KeyboardButton(text=ADD_INCOME),
        KeyboardButton(text=TODAY),
    ]],
    resize_keyboard=True,
)

# Пока категорий немного, список показывается целиком: страницы ради десяти
# кнопок только мешают. Дальше клавиатура становится нечитаемой — и включаются.
PAGINATION_THRESHOLD = 10
PAGE_SIZE = 8


def report_actions(period='day'):
    """Кнопки под отчётом: подробности и сравнение — по тому же периоду."""
    rows = [[InlineKeyboardButton(text='Подробнее', callback_data=f'details:{period}')]]
    if period in COMPARISON_BUTTONS:
        rows[0].append(InlineKeyboardButton(
            text=COMPARISON_BUTTONS[period], callback_data=f'compare:{period}',
        ))
    rows.append([InlineKeyboardButton(text='Добавить трату', callback_data='add:expense')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def page_count(total):
    """Сколько страниц займёт список категорий."""
    if total <= PAGINATION_THRESHOLD:
        return 1
    return ceil(total / PAGE_SIZE)


def date_keyboard():
    """Выбор даты операции: два частых варианта и ручной ввод.

    Дата в ТЗ — обязательное поле, и из чата тоже должна задаваться:
    трату часто записывают на следующий день.
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text='Сегодня', callback_data='add:date:today'),
            InlineKeyboardButton(text='Вчера', callback_data='add:date:yesterday'),
        ],
        [InlineKeyboardButton(text='Другая дата', callback_data='add:date:custom')],
        [InlineKeyboardButton(text='Отмена', callback_data='add:cancel')],
    ])


def description_keyboard():
    """Последний шаг: можно вернуться к дате, если ошибся с ней.

    Дата без года разрешается автоматически, и результат не всегда совпадает
    с ожиданием — «23.09» в августе это прошлый сентябрь. Возврат нужен,
    чтобы поправить, не начиная ввод заново.
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='Изменить дату', callback_data='add:back:date')],
        [InlineKeyboardButton(text='Отмена', callback_data='add:cancel')],
    ])


def categories_keyboard(categories, page=0):
    """Выбор категории: по две в ряд, плюс создание новой и постраничные стрелки.

    Категории приходят отсортированными по частоте использования, поэтому
    ходовые оказываются на первой странице.
    """
    pages = page_count(len(categories))
    page = max(0, min(page, pages - 1))

    visible = categories if pages == 1 else categories[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    buttons = [
        InlineKeyboardButton(text=category.name, callback_data=f'add:category:{category.pk}')
        for category in visible
    ]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]

    new_category = InlineKeyboardButton(text='+ Новая категория', callback_data='add:new')
    if pages > 1:
        # Стрелки по краям, создание в центре; листание закольцовано
        previous_page = (page - 1) % pages
        next_page = (page + 1) % pages
        rows.append([
            InlineKeyboardButton(text='‹', callback_data=f'add:page:{previous_page}'),
            new_category,
            InlineKeyboardButton(text='›', callback_data=f'add:page:{next_page}'),
        ])
        rows.append([InlineKeyboardButton(
            text=f'Страница {page + 1} из {pages}', callback_data='add:noop',
        )])
    else:
        rows.append([new_category])

    # Отмена отдельной строкой: рядом со стрелками в неё легко попасть мимо
    rows.append([InlineKeyboardButton(text='Отмена', callback_data='add:cancel')])
    return InlineKeyboardMarkup(inline_keyboard=rows)
