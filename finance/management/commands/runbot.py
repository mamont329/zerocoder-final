import asyncio
import logging

from django.core.exceptions import ImproperlyConfigured
from django.core.management.base import BaseCommand, CommandError

from finance.bot.runner import run_polling


class Command(BaseCommand):
    help = 'Запускает Telegram-бота FinControl'

    def handle(self, *args, **options):
        logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
        self.stdout.write(self.style.SUCCESS('Бот запускается, остановка — Ctrl+C'))
        try:
            asyncio.run(run_polling())
        except ImproperlyConfigured as error:
            # Отсутствие токена — обычная ситуация при первом запуске,
            # трейсбек тут только пугает
            raise CommandError(error) from None
        except KeyboardInterrupt:
            self.stdout.write('Бот остановлен')
