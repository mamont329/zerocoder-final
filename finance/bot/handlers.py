"""Обработчики команд и кнопок бота."""
from decimal import Decimal, InvalidOperation

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from .. import periods
from ..analytics import money
from ..models import OperationType
from . import services
from .keyboards import ADD_EXPENSE, ADD_INCOME, MAIN_MENU, TODAY, categories_keyboard, report_actions

router = Router()

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
    """Шаги добавления операции: сумма → категория → описание.

    Один сценарий на доход и расход: отличается только набор категорий,
    а тип операции потом берётся из выбранной категории. Шаг new_category —
    боковая ветка для случая, когда подходящей категории ещё нет.
    """

    amount = State()
    category = State()
    new_category = State()
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
            f'Готово, чат привязан к аккаунту <b>{user.username}</b>.\n\n{HELP}',
            reply_markup=MAIN_MENU,
        )
        return

    user = await services.get_user(message.chat.id)
    if user is None:
        await message.answer(NOT_LINKED)
        return
    await message.answer(f'С возвращением, {user.username}!\n\n{HELP}', reply_markup=MAIN_MENU)


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


@router.message(AddOperation.amount)
async def add_amount(message: Message, state: FSMContext):
    raw = (message.text or '').replace(',', '.').strip()
    try:
        amount = Decimal(raw)
    except InvalidOperation:
        await message.answer('Не похоже на сумму. Отправьте число, например <code>350.50</code>')
        return
    if amount <= 0:
        await message.answer('Сумма должна быть больше нуля.')
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


async def ask_description(message: Message, state: FSMContext, category):
    """Общий последний шаг: категория выбрана, осталось описание."""
    await state.update_data(category_id=category.pk)
    await state.set_state(AddOperation.description)
    await message.answer(
        f'Категория: <b>{category.name}</b>\n'
        'Добавьте описание или отправьте <code>-</code>, чтобы пропустить.'
    )


@router.callback_query(AddOperation.category, F.data.startswith('add:category:'))
async def add_category(callback: CallbackQuery, state: FSMContext):
    user = await services.get_user(callback.message.chat.id)
    category = await services.get_category(user, int(callback.data.split(':')[-1]))
    if category is None:
        await callback.answer('Категория не найдена', show_alert=True)
        return

    await ask_description(callback.message, state, category)
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
        await message.answer(f'{error}\nПопробуйте другое название.')
        return

    await ask_description(message, state, category)


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
    transaction = await services.create_operation(user, category, data['amount'], description)
    await state.clear()

    sign = '+' if transaction.type == OperationType.INCOME else '−'
    await message.answer(
        f'Записал: <b>{sign}{money(transaction.amount)} ₽</b> · {category.name}',
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
