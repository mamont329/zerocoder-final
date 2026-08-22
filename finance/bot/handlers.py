"""Обработчики команд и кнопок бота."""
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from django.core.exceptions import ValidationError
from django.utils import timezone

from .. import periods
from ..analytics import money
from ..reports import esc
from ..models import OperationType
from . import services
from .keyboards import (ADD_EXPENSE, ADD_INCOME, MAIN_MENU, TODAY, categories_keyboard,
                        date_keyboard, description_keyboard, report_actions)

router = Router()

# Модель хранит 12 цифр при двух знаках после запятой — больше не поместится
MAX_AMOUNT = Decimal('9999999999.99')

NOT_LINKED = (
    'Этот чат не привязан к аккаунту FinControl.\n\n'
    'Откройте раздел «Профиль» на сайте, скопируйте код привязки '
    'и отправьте команду:\n<code>/start ВАШ_КОД</code>'
)

HELP = (
    '<b>Что я умею</b>\n\n'
    '/today — расходы за сегодня\n'
    '/week — статистика за неделю\n'
    '/month — статистика за месяц\n'
    '/category еда — траты по категории\n'
    '/add — добавить трату\n'
    '/income — добавить доход\n'
    '/advice — советы и предупреждения\n'
    '/unlink — отвязать этот чат\n\n'
    'Ещё есть кнопки под сообщениями и меню внизу экрана.'
)


class AddOperation(StatesGroup):
    """Шаги добавления операции: сумма → категория → дата → описание.

    Один сценарий на доход и расход: отличается только набор категорий,
    а тип операции потом берётся из выбранной категории. Шаг new_category —
    боковая ветка для случая, когда подходящей категории ещё нет.
    """

    amount = State()
    category = State()
    new_category = State()
    date = State()
    custom_date = State()
    description = State()


async def require_user(message):
    """Возвращает привязанного пользователя или объясняет, как привязаться."""
    user = await services.get_user(message.chat.id)
    if user is None:
        await message.answer(NOT_LINKED)
    return user


# Без deep_link: этот параметр означает «аргументов быть не должно»,
# а нам нужен именно /start с кодом привязки
@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject):
    code = (command.args or '').strip()
    if code:
        user = await services.link_account(message.chat.id, code)
        if user is None:
            await message.answer('Код не подошёл. Проверьте его в разделе «Профиль» на сайте.')
            return
        await message.answer(
            f'Готово, чат привязан к аккаунту <b>{esc(user.username)}</b>.\n\n{HELP}',
            reply_markup=MAIN_MENU,
        )
        return

    user = await services.get_user(message.chat.id)
    if user is None:
        await message.answer(NOT_LINKED)
        return
    await message.answer(f'С возвращением, {esc(user.username)}!\n\n{HELP}', reply_markup=MAIN_MENU)


@router.message(Command('help'))
async def cmd_help(message: Message):
    await message.answer(HELP, reply_markup=MAIN_MENU)


@router.message(Command('unlink'))
async def cmd_unlink(message: Message):
    user = await require_user(message)
    if user is None:
        return
    await services.unlink_account(message.chat.id)
    await message.answer('Чат отвязан. Код привязки в кабинете обновлён.')


@router.message(Command('today'))
@router.message(F.text == TODAY)
async def cmd_today(message: Message):
    user = await require_user(message)
    if user is None:
        return
    text = await services.build_period_report(user, periods.DAY)
    await message.answer(text, reply_markup=report_actions(periods.DAY))


@router.message(Command('week'))
async def cmd_week(message: Message):
    user = await require_user(message)
    if user is None:
        return
    text = await services.build_period_report(user, periods.WEEK)
    await message.answer(text, reply_markup=report_actions(periods.WEEK))


@router.message(Command('month'))
async def cmd_month(message: Message):
    user = await require_user(message)
    if user is None:
        return
    text = await services.build_period_report(user, periods.MONTH)
    await message.answer(text, reply_markup=report_actions(periods.MONTH))


@router.message(Command('year'))
async def cmd_year(message: Message):
    user = await require_user(message)
    if user is None:
        return
    text = await services.build_period_report(user, periods.YEAR)
    await message.answer(text, reply_markup=report_actions(periods.YEAR))


@router.message(Command('advice'))
async def cmd_advice(message: Message):
    user = await require_user(message)
    if user is None:
        return
    text = await services.build_advice_report(user, periods.MONTH)
    await message.answer(text)


@router.message(Command('category'))
async def cmd_category(message: Message, command: CommandObject):
    user = await require_user(message)
    if user is None:
        return
    name = (command.args or '').strip()
    if not name:
        await message.answer('Укажите категорию: <code>/category еда</code>')
        return
    text = await services.build_category_report(user, name)
    await message.answer(text)


@router.callback_query(F.data.startswith('details:'))
async def show_details(callback: CallbackQuery):
    """Советы по тому же периоду, что и отчёт, под которым нажали кнопку."""
    user = await services.get_user(callback.message.chat.id)
    if user is None:
        await callback.answer('Чат не привязан', show_alert=True)
        return
    period = callback.data.split(':')[-1] or periods.MONTH
    text = await services.build_advice_report(user, period)
    await callback.message.answer(text)
    await callback.answer()


@router.callback_query(F.data.startswith('compare:'))
async def compare_periods(callback: CallbackQuery):
    """Сравнение с предыдущим периодом той же длины, что и отчёт."""
    user = await services.get_user(callback.message.chat.id)
    if user is None:
        await callback.answer('Чат не привязан', show_alert=True)
        return
    period = callback.data.split(':')[-1] or periods.WEEK
    text = await services.build_comparison(user, period)
    await callback.message.answer(text)
    await callback.answer()


# --- Добавление операции ------------------------------------------------------

async def start_adding(message: Message, state: FSMContext, operation_type):
    what = 'потратили' if operation_type == OperationType.EXPENSE else 'получили'
    await state.set_state(AddOperation.amount)
    await state.update_data(operation_type=operation_type)
    await message.answer(
        f'Сколько {what}? Отправьте сумму числом, например <code>350.50</code>'
    )


@router.message(Command('add'))
@router.message(F.text == ADD_EXPENSE)
async def cmd_add_expense(message: Message, state: FSMContext):
    user = await require_user(message)
    if user is None:
        return
    await start_adding(message, state, OperationType.EXPENSE)


@router.message(Command('income'))
@router.message(F.text == ADD_INCOME)
async def cmd_add_income(message: Message, state: FSMContext):
    user = await require_user(message)
    if user is None:
        return
    await start_adding(message, state, OperationType.INCOME)


@router.callback_query(F.data == 'add:expense')
async def add_from_button(callback: CallbackQuery, state: FSMContext):
    user = await services.get_user(callback.message.chat.id)
    if user is None:
        await callback.answer('Чат не привязан', show_alert=True)
        return
    await start_adding(callback.message, state, OperationType.EXPENSE)
    await callback.answer()


def parse_amount(raw):
    """Разбирает сумму из сообщения. Возвращает пару (сумма, ошибка).

    Decimal принимает 'nan' и 'Infinity' без исключения, и дальше любое
    сравнение с nan падает уже вне блока try. Поэтому конечность проверяется
    отдельно, до всех сравнений.
    """
    try:
        amount = Decimal(raw.replace(',', '.').strip())
    except InvalidOperation:
        return None, 'Не похоже на сумму. Отправьте число, например <code>350.50</code>'

    if not amount.is_finite():
        return None, 'Сумма должна быть обычным числом.'
    if amount <= 0:
        return None, 'Сумма должна быть больше нуля.'
    if amount > MAX_AMOUNT:
        return None, f'Слишком большая сумма. Максимум — {money(MAX_AMOUNT)} ₽.'

    # Модель хранит два знака после запятой: округляем здесь, иначе
    # ValidationError вылезет в самом конце сценария
    return amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP), None


# Слова, которыми дату называют чаще, чем числами
RELATIVE_DAYS = {'сегодня': 0, 'вчера': 1, 'позавчера': 2}


def recent_date(day, month=None, today=None):
    """Ближайшая прошедшая дата с таким днём и, если указан, месяцем.

    Недостающая часть берётся из текущей: «25.12» в августе — это прошлый
    декабрь, а «02» в конце месяца — второе число текущего. Отступаем назад,
    только если дата иначе оказалась бы в будущем, которого ещё не было.
    Заодно так решается «31» в марте: в феврале такого числа нет, берётся январь.
    """
    today = today or timezone.localdate()
    year, current_month = today.year, month or today.month

    # Двенадцати шагов хватает: любое число встречается хотя бы раз в году
    for _ in range(12):
        try:
            candidate = date(year, current_month, day)
        except ValueError:
            candidate = None

        if candidate and candidate <= today:
            return candidate

        if month:
            # Месяц задан пользователем — двигаем только год
            year -= 1
        else:
            current_month -= 1
            if current_month == 0:
                current_month, year = 12, year - 1
    return None


def parse_date(raw):
    """Дата из сообщения.

    Понимает слова «сегодня», «вчера», «позавчера», полные даты «25.12.2026»
    и «25.12.26», дату без года «25.12» и одно число «25» — день текущего
    или прошлого месяца.
    """
    raw = raw.strip().lower()

    if raw in RELATIVE_DAYS:
        return timezone.localdate() - timedelta(days=RELATIVE_DAYS[raw])

    # Полная дата: год указан явно, ничего не достраиваем
    for fmt in ('%d.%m.%Y', '%d.%m.%y'):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue

    # День с месяцем, но без года
    try:
        parsed = datetime.strptime(raw, '%d.%m').date()
    except ValueError:
        pass
    else:
        return recent_date(parsed.day, parsed.month)

    # Одно число — день месяца
    if raw.isdigit() and 1 <= int(raw) <= 31:
        return recent_date(int(raw))

    return None


@router.message(AddOperation.amount)
async def add_amount(message: Message, state: FSMContext):
    amount, error = parse_amount(message.text or '')
    if error:
        await message.answer(error)
        return

    data = await state.get_data()
    user = await services.get_user(message.chat.id)
    categories = await services.categories_of_type(user, data['operation_type'])

    await state.update_data(amount=str(amount))
    await state.set_state(AddOperation.category)

    if not categories:
        # Не тупик: категорию можно завести прямо здесь
        await state.set_state(AddOperation.new_category)
        await message.answer('Подходящих категорий пока нет. Как назовём новую?')
        return

    await message.answer('Выберите категорию:', reply_markup=categories_keyboard(categories))


async def ask_date(message: Message, state: FSMContext, category):
    """Категория выбрана — уточняем дату операции."""
    await state.update_data(category_id=category.pk)
    await state.set_state(AddOperation.date)
    await message.answer(
        f'Категория: <b>{esc(category.name)}</b>\n'
        'Когда это было? Выберите кнопкой или напишите: «вчера», «25.12».',
        reply_markup=date_keyboard(),
    )


async def ask_description(message: Message, state: FSMContext, when):
    """Последний шаг: дата известна, осталось описание."""
    await state.update_data(date=when.isoformat())
    await state.set_state(AddOperation.description)
    await message.answer(
        f'Дата: <b>{when:%d.%m.%Y}</b>\n'
        'Добавьте описание или отправьте <code>-</code>, чтобы пропустить.',
        reply_markup=description_keyboard(),
    )


@router.callback_query(AddOperation.date, F.data.startswith('add:date:'))
async def add_date(callback: CallbackQuery, state: FSMContext):
    choice = callback.data.split(':')[-1]

    if choice == 'custom':
        await state.set_state(AddOperation.custom_date)
        await callback.message.answer(
            'Отправьте дату: <code>25.12.2026</code>, <code>25.12</code>, '
            'просто число <code>25</code> или словом — <code>вчера</code>.'
        )
        await callback.answer()
        return

    today = timezone.localdate()
    chosen = today if choice == 'today' else today - timedelta(days=1)
    await ask_description(callback.message, state, chosen)
    await callback.answer()


async def accept_date(message: Message, state: FSMContext, hint):
    """Разбирает написанную дату и переходит к описанию.

    Будущее отсекается здесь: правило есть и в модели, но сказать о нём
    сразу честнее, чем принять дату и споткнуться на сохранении.
    """
    parsed = parse_date(message.text or '')
    if parsed is None:
        await message.answer(hint)
        return
    if parsed > timezone.localdate():
        await message.answer('Дата не может быть в будущем — операции вносятся по факту.')
        return
    await ask_description(message, state, parsed)


@router.message(AddOperation.date)
async def add_date_typed(message: Message, state: FSMContext):
    """Дата, написанная текстом, пока на экране кнопки.

    Без этого обработчика слово «вчера» уходило в общий обработчик, и вместо
    ответа пользователь получал справку, оставаясь на том же шаге.
    """
    await accept_date(message, state, (
        'Выберите дату кнопкой или напишите её: <code>вчера</code>, '
        '<code>25</code>, <code>25.12</code> или <code>25.12.2026</code>.'
    ))


@router.message(AddOperation.custom_date)
async def add_custom_date(message: Message, state: FSMContext):
    await accept_date(message, state, (
        'Не разобрал дату. Отправьте её в формате <code>25.12.2026</code>, '
        '<code>25.12</code>, просто числом <code>25</code> или словом — <code>вчера</code>.'
    ))


@router.callback_query(AddOperation.category, F.data.startswith('add:category:'))
async def add_category(callback: CallbackQuery, state: FSMContext):
    user = await services.get_user(callback.message.chat.id)
    category = await services.get_category(user, int(callback.data.split(':')[-1]))
    if category is None:
        await callback.answer('Категория не найдена', show_alert=True)
        return

    await ask_date(callback.message, state, category)
    await callback.answer()


@router.callback_query(AddOperation.category, F.data.startswith('add:page:'))
async def add_page(callback: CallbackQuery, state: FSMContext):
    """Листание страниц категорий — правим ту же клавиатуру, не плодя сообщений."""
    data = await state.get_data()
    user = await services.get_user(callback.message.chat.id)
    categories = await services.categories_of_type(user, data['operation_type'])
    page = int(callback.data.split(':')[-1])

    await callback.message.edit_reply_markup(reply_markup=categories_keyboard(categories, page))
    await callback.answer()


@router.callback_query(F.data == 'add:noop')
async def add_noop(callback: CallbackQuery):
    """Номер страницы — не кнопка, но Telegram ждёт ответа на нажатие."""
    await callback.answer()


@router.callback_query(AddOperation.category, F.data == 'add:new')
async def add_new_category(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AddOperation.new_category)
    data = await state.get_data()
    kind = 'расходов' if data['operation_type'] == OperationType.EXPENSE else 'доходов'
    await callback.message.answer(f'Название новой категории {kind}:')
    await callback.answer()


@router.message(AddOperation.new_category)
async def save_new_category(message: Message, state: FSMContext):
    data = await state.get_data()
    user = await services.get_user(message.chat.id)
    category, error = await services.create_category(
        user, message.text or '', data['operation_type'],
    )
    if error:
        await message.answer(f'{esc(error)}\nПопробуйте другое название.')
        return

    await ask_date(message, state, category)


@router.callback_query(AddOperation.description, F.data == 'add:back:date')
async def back_to_date(callback: CallbackQuery, state: FSMContext):
    """Возврат к вводу даты, когда она разошлась с ожиданием."""
    data = await state.get_data()
    user = await services.get_user(callback.message.chat.id)
    category = await services.get_category(user, data['category_id'])
    if category is None:
        await callback.answer('Категория не найдена', show_alert=True)
        return

    await ask_date(callback.message, state, category)
    await callback.answer()


@router.callback_query(F.data == 'add:cancel')
async def add_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer('Добавление отменено.', reply_markup=MAIN_MENU)
    await callback.answer()


@router.message(AddOperation.description)
async def add_description(message: Message, state: FSMContext):
    data = await state.get_data()
    description = (message.text or '').strip()
    if description == '-':
        description = ''

    user = await services.get_user(message.chat.id)
    category = await services.get_category(user, data['category_id'])
    when = datetime.strptime(data['date'], '%Y-%m-%d').date()

    try:
        transaction = await services.create_operation(
            user, category, data['amount'], description, when,
        )
    except ValidationError as error:
        # Модель — последний рубеж: её жалобы должны доходить до пользователя,
        # а не теряться в логе обработчика
        await state.clear()
        problems = '; '.join(sum(error.message_dict.values(), []))
        await message.answer(
            f'Не удалось сохранить операцию: {esc(problems)}\nПопробуйте ещё раз.',
            reply_markup=MAIN_MENU,
        )
        return

    await state.clear()
    sign = '+' if transaction.type == OperationType.INCOME else '−'
    await message.answer(
        f'Записал: <b>{sign}{money(transaction.amount)} ₽</b> · {esc(category.name)}',
        reply_markup=MAIN_MENU,
    )


@router.message()
async def fallback(message: Message):
    """Любое непонятное сообщение — подсказка вместо молчания."""
    user = await services.get_user(message.chat.id)
    if user is None:
        await message.answer(NOT_LINKED)
        return
    await message.answer(HELP, reply_markup=MAIN_MENU)
