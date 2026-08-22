"""Хранилище диалогов бота в базе данных.

Штатное MemoryStorage держит незавершённые сценарии в оперативной памяти:
после перезапуска бота пользователь, начавший добавлять трату, остаётся
с введённой суммой в никуда. Здесь то же самое лежит в таблице, поэтому
диалог переживает перезапуск.
"""
from asgiref.sync import sync_to_async

from aiogram.fsm.state import State
from aiogram.fsm.storage.base import BaseStorage, StorageKey

from ..models import BotDialog


def dialog_key(key: StorageKey):
    """Строковый ключ диалога: бот, чат и пользователь вместе."""
    return f'{key.bot_id}:{key.chat_id}:{key.user_id}:{key.destiny}'


class DjangoStorage(BaseStorage):
    """Состояние и данные сценария в таблице finance_botdialog."""

    @sync_to_async
    def _write(self, key, **fields):
        BotDialog.objects.update_or_create(key=dialog_key(key), defaults=fields)

    @sync_to_async
    def _read(self, key):
        return BotDialog.objects.filter(key=dialog_key(key)).first()

    @sync_to_async
    def _drop(self, key):
        BotDialog.objects.filter(key=dialog_key(key)).delete()

    async def set_state(self, key: StorageKey, state=None) -> None:
        name = state.state if isinstance(state, State) else state
        if name is None:
            # Сценарий завершён: данные больше не нужны, строку не копим
            await self._drop(key)
            return
        await self._write(key, state=name)

    async def get_state(self, key: StorageKey):
        dialog = await self._read(key)
        return dialog.state if dialog else None

    async def set_data(self, key: StorageKey, data) -> None:
        await self._write(key, data=dict(data))

    async def get_data(self, key: StorageKey) -> dict:
        dialog = await self._read(key)
        return dict(dialog.data) if dialog else {}

    async def close(self) -> None:
        """Соединениями с базой управляет Django — закрывать нечего."""
