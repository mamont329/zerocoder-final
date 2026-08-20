"""Отправка сообщений ботом из синхронного кода.

Веб-представления и management-команды синхронные, а aiogram асинхронный,
поэтому вызовы заворачиваются в async_to_sync. Сессия закрывается сразу:
это разовые отправки, а не долгоживущий бот.
"""
import logging

from asgiref.sync import async_to_sync

from .runner import get_bot

logger = logging.getLogger(__name__)


async def _send(chat_id, text):
    bot = get_bot()
    try:
        await bot.send_message(chat_id, text)
    finally:
        await bot.session.close()


def send_to_chat(chat_id, text):
    """Отправляет сообщение в чат. Возвращает True при успехе.

    Ошибки не пробрасываются: недоступный Telegram не должен ронять
    создание пользователя или рассылку отчётов.
    """
    try:
        async_to_sync(_send)(chat_id, text)
        return True
    except Exception as error:
        logger.warning('Не удалось отправить сообщение в чат %s: %s', chat_id, error)
        return False
