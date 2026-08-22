"""Сборка и запуск бота."""
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from django.core.exceptions import ImproperlyConfigured

from .handlers import router
from .storage import DjangoStorage

logger = logging.getLogger(__name__)


def get_bot():
    """Создаёт бота с токеном из окружения.

    HTML выбран разметкой по умолчанию: в отчётах нужны только жирный шрифт
    и моноширинный код, а Markdown требует экранировать слишком многое.
    """
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    if not token:
        raise ImproperlyConfigured(
            'Не задан TELEGRAM_BOT_TOKEN. Добавьте его в .env — см. .env.example'
        )
    return Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


def get_dispatcher():
    # Хранилище в базе, а не в памяти: незавершённый диалог переживёт перезапуск
    dispatcher = Dispatcher(storage=DjangoStorage())
    dispatcher.include_router(router)
    return dispatcher


async def run_polling():
    """Запускает бота в режиме опроса — для разработки и учебного стенда."""
    bot = get_bot()
    dispatcher = get_dispatcher()

    me = await bot.get_me()
    logger.info('Бот запущен: @%s', me.username)
    # Накопившиеся за время простоя команды не нужны
    await bot.delete_webhook(drop_pending_updates=True)
    try:
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()
