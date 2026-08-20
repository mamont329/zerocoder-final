import asyncio
import logging

from django.core.management.base import BaseCommand

from finance.bot.runner import run_polling


class Command(BaseCommand):
    help = 'Запускает Telegram-бота FinControl'

    def handle(self, *args, **options):
        logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
        self.stdout.write(self.style.SUCCESS('Бот запускается, остановка — Ctrl+C'))
        try:
            asyncio.run(run_polling())
        except KeyboardInterrupt:
            self.stdout.write('Бот остановлен')
