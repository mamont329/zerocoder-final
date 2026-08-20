"""Обращения к базе из бота.

aiogram работает асинхронно, а ORM Django — синхронно, поэтому каждый вызов
завёрнут в sync_to_async. Вся работа с базой собрана здесь, чтобы обработчики
оставались тонкими и не путались в двух моделях выполнения.
"""
from decimal import Decimal

from asgiref.sync import sync_to_async
from django.core.exceptions import ValidationError
from django.db.models import Count

from .. import periods, reports
from ..models import Category, OperationType, Profile, Transaction


@sync_to_async
def get_user(telegram_id):
    """Пользователь, привязавший этот чат.

    None — если привязки нет или аккаунт отключён: отключение должно закрывать
    доступ везде, а не только на сайте.
    """
    profile = (
        Profile.objects.filter(telegram_id=telegram_id, user__is_active=True)
        .select_related('user').first()
    )
    return profile.user if profile else None


@sync_to_async
def link_account(telegram_id, code):
    """Привязывает чат к аккаунту по коду из кабинета.

    Возвращает пользователя или None, если код не подошёл.
    """
    profile = (
        Profile.objects.filter(link_code__iexact=code.strip(), user__is_active=True)
        .select_related('user').first()
    )
    if profile is None:
        return None

    # Один и тот же чат не может обслуживать двух пользователей
    Profile.objects.filter(telegram_id=telegram_id).exclude(pk=profile.pk).update(telegram_id=None)
    profile.telegram_id = telegram_id
    profile.save(update_fields=['telegram_id'])
    return profile.user


@sync_to_async
def unlink_account(telegram_id):
    """Отвязывает чат и выдаёт новый код привязки."""
    profile = Profile.objects.filter(telegram_id=telegram_id).first()
    if profile:
        profile.unlink()


@sync_to_async
def build_period_report(user, period):
    return reports.period_report(user, period)


@sync_to_async
def build_advice_report(user, period):
    return reports.advice_report(user, period)


@sync_to_async
def build_category_report(user, name, period=periods.MONTH):
    return reports.category_report(user, name, period)


@sync_to_async
def build_comparison(user, period):
    return reports.compare_periods(user, period)


@sync_to_async
def categories_of_type(user, operation_type):
    """Категории нужного направления, ходовые — первыми.

    Порядок по числу операций: в чате важнее быстро ткнуть в «Еду»,
    чем видеть алфавит.
    """
    return list(
        user.categories.filter(type=operation_type)
        .annotate(uses=Count('transactions'))
        .order_by('-uses', 'name')
    )


@sync_to_async
def create_category(user, name, operation_type):
    """Создаёт категорию из чата.

    Возвращает пару (категория, ошибка): в боте удобнее разбирать её на месте,
    чем ловить исключение. Дубликаты проверяются в Python — SQLite приводит
    регистр только для латиницы.
    """
    name = ' '.join(name.split())
    if not name:
        return None, 'Название не может быть пустым.'
    if len(name) > 100:
        return None, 'Название длиннее 100 символов.'

    target = name.casefold()
    if any(existing.name.casefold() == target for existing in user.categories.all()):
        return None, f'Категория «{name}» уже есть.'

    category = Category(user=user, name=name, type=operation_type)
    try:
        category.full_clean()
    except ValidationError as error:
        return None, '; '.join(sum(error.message_dict.values(), []))
    category.save()
    return category, None


@sync_to_async
def get_category(user, category_id):
    return user.categories.filter(pk=category_id).first()


@sync_to_async
def create_operation(user, category, amount, description=''):
    """Создаёт операцию с проверками модели.

    Тип берётся у категории — она уже знает, доход это или расход.
    full_clean вызывается явно: бот пишет в базу мимо форм, а правила
    (сумма больше нуля, тип совпадает с категорией) должны действовать и здесь.
    """
    transaction = Transaction(
        user=user,
        type=category.type,
        amount=Decimal(amount),
        category=category,
        description=description,
    )
    transaction.full_clean()
    transaction.save()
    return transaction
