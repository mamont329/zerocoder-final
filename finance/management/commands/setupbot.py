import asyncio
from pathlib import Path

from aiogram.types import BotCommand, FSInputFile, InputProfilePhotoStatic
from django.conf import settings
from django.core.management.base import BaseCommand

from finance.bot.runner import get_bot

# Аватарка рисуется скриптом scripts/make_avatar.py
AVATAR_PATH = Path(settings.BASE_DIR) / 'scripts' / 'avatar.jpg'

# Имя бота, его описания и меню команд — часть проекта, а не ручная настройка
# в @BotFather: так при переносе на другой токен ничего не забудется.
BOT_NAME = 'FinControl'

# Показывается на пустом экране чата до первого сообщения
DESCRIPTION = (
    'Учёт личных финансов FinControl. Показывает расходы и доходы за день, '
    'неделю и месяц, считает траты по категориям, предупреждает о превышении '
    'лимитов и позволяет записать трату прямо из чата.'
)

# Короткое описание — в профиле бота и в списке чатов
SHORT_DESCRIPTION = 'Учёт личных финансов: отчёты, лимиты и быстрая запись трат.'

COMMANDS = [
    BotCommand(command='today', description='Расходы за сегодня'),
    BotCommand(command='week', description='Статистика за неделю'),
    BotCommand(command='month', description='Статистика за месяц'),
    BotCommand(command='year', description='Статистика за год'),
    BotCommand(command='category', description='Траты по категории: /category еда'),
    BotCommand(command='add', description='Добавить трату'),
    BotCommand(command='income', description='Добавить доход'),
    BotCommand(command='advice', description='Советы и предупреждения'),
    BotCommand(command='unlink', description='Отвязать этот чат'),
    BotCommand(command='help', description='Справка'),
]


async def apply_settings(stdout, style):
    bot = get_bot()
    try:
        # Старое меню удаляем целиком: иначе команды прошлого бота останутся висеть
        await bot.delete_my_commands()
        await bot.set_my_commands(COMMANDS)
        stdout.write(style.SUCCESS(f'Меню команд обновлено: {len(COMMANDS)} шт.'))

        await bot.set_my_description(DESCRIPTION)
        await bot.set_my_short_description(SHORT_DESCRIPTION)
        stdout.write(style.SUCCESS('Описания обновлены'))

        try:
            await bot.set_my_name(BOT_NAME)
            stdout.write(style.SUCCESS(f'Имя бота: {BOT_NAME}'))
        except Exception as error:
            # Telegram ограничивает частоту смены имени — это не повод падать
            stdout.write(style.WARNING(f'Имя не изменено: {error}'))

        if AVATAR_PATH.exists():
            # Аватарка принимается только в JPG и только новым файлом:
            # повторно использовать уже загруженный file_id Telegram не даёт
            await bot.set_my_profile_photo(
                photo=InputProfilePhotoStatic(photo=FSInputFile(AVATAR_PATH))
            )
            stdout.write(style.SUCCESS(f'Аватарка загружена: {AVATAR_PATH.name}'))
        else:
            stdout.write(style.WARNING(
                f'Аватарка не найдена ({AVATAR_PATH}). Нарисуйте её: python scripts/make_avatar.py'
            ))

        me = await bot.get_me()
        stdout.write(f'Готово: @{me.username} — {me.first_name}')
    finally:
        await bot.session.close()


class Command(BaseCommand):
    help = 'Прописывает боту имя, описания и меню команд'

    def handle(self, *args, **options):
        asyncio.run(apply_settings(self.stdout, self.style))
