"""Ежедневная рассылка сводок в Telegram — запускается планировщиком."""
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils import timezone

from finance import reports
from finance.bot.notify import send_to_chat
from finance.models import NotificationLog


class Command(BaseCommand):
    help = 'Отправляет сводку за день пользователям, включившим уведомления'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Показать текст сообщения, ничего не отправляя',
        )
        parser.add_argument(
            '--user',
            help='Работать только с одним пользователем (по логину) — для проверки',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Отправить повторно, не глядя в историю — для проверки доставки',
        )
        parser.add_argument(
            '--status',
            action='store_true',
            help='Показать, кому и когда уходили уведомления, ничего не отправляя',
        )

    def handle(self, *args, **options):
        self.force = options['force']
        today = timezone.localdate()

        recipients = User.objects.filter(
            is_active=True,
            profile__daily_report=True,
            profile__telegram_id__isnull=False,
        ).select_related('profile')
        if options['user']:
            recipients = recipients.filter(username=options['user'])

        if options['status']:
            self.show_status(recipients)
            return

        if not recipients:
            self.stdout.write(self.style.WARNING(
                'Получателей нет: нужен привязанный Telegram и включённый '
                '«Ежедневный отчёт» в профиле.'
            ))
            return

        if options['dry_run']:
            self.preview(recipients, today)
            return

        self.send(recipients, today)

    # --- Режимы -------------------------------------------------------------

    def preview(self, recipients, today):
        """Показывает сообщение целиком, не заглядывая в историю.

        История здесь намеренно игнорируется: задача режима — показать текст,
        а не повторить решение рассылки. Что сделает обычный запуск,
        дописывается отдельной строкой.
        """
        for user in recipients:
            self.stdout.write(self.style.WARNING(f'--- {user.username}'))

            parts = self.collect(user, today, ignore_history=True)
            if not parts:
                self.stdout.write('Отправлять нечего: за сегодня нет операций, '
                                  'лимиты не превышены.')
                self.stdout.write('')
                continue

            self.stdout.write('\n\n'.join(text for _, _, text in parts))
            self.stdout.write('')

            fresh = [part for part in parts if not self.already_sent(user, part[0], part[1])]
            if fresh:
                self.stdout.write(self.style.SUCCESS(
                    f'Обычный запуск отправит это сообщение ({len(fresh)} из {len(parts)} блоков новые).'
                ))
            else:
                self.stdout.write(
                    'Всё это уже отправлено сегодня, поэтому обычная рассылка промолчит. '
                    'Доставить это сообщение ещё раз можно только повторной отправкой.'
                )
            self.stdout.write('')

    def send(self, recipients, today):
        sent = skipped = 0
        for user in recipients:
            parts = self.collect(user, today, ignore_history=False)

            if not parts:
                skipped += 1
                self.stdout.write(f'{user.username}: {self.why_nothing(user, today)}')
                continue

            message = '\n\n'.join(text for _, _, text in parts)
            if send_to_chat(user.profile.telegram_id, message):
                sent += 1
                # Отмечаем только доставленное: не дошло — повторим при следующем запуске
                for kind, key, _ in parts:
                    NotificationLog.objects.get_or_create(user=user, kind=kind, key=key)
                self.stdout.write(self.style.SUCCESS(f'{user.username}: отправлено'))
            else:
                self.stdout.write(self.style.ERROR(
                    f'{user.username}: не доставлено, попробуем при следующем запуске'
                ))

        self.stdout.write(f'Итого: отправлено {sent}, пропущено {skipped}')

    def show_status(self, recipients):
        """Что и когда уходило — чтобы проверить, отработало ли расписание."""
        if not recipients:
            self.stdout.write(self.style.WARNING(
                'Получателей нет: нужен привязанный Telegram и включённый '
                '«Ежедневный отчёт» в профиле.'
            ))
        else:
            self.stdout.write('Получатели ежедневной сводки:')
        for user in recipients:
            last = user.notifications.filter(kind=NotificationLog.Kind.DIGEST).first()
            when = f'{timezone.localtime(last.sent_at):%d.%m.%Y %H:%M}' if last else 'ещё не отправлялась'
            self.stdout.write(f'  {user.username}: последняя сводка — {when}')

        recent = NotificationLog.objects.select_related('user')[:10]
        if recent:
            self.stdout.write('')
            self.stdout.write('Последние уведомления:')
            for item in recent:
                sent_at = timezone.localtime(item.sent_at)
                self.stdout.write(
                    f'  {sent_at:%d.%m %H:%M} · {item.user.username} · '
                    f'{item.get_kind_display()} · {item.key}'
                )

    # --- Сборка сообщения ---------------------------------------------------

    def collect(self, user, today, ignore_history):
        """Блоки сообщения: сводка за день и предупреждения о лимитах.

        Возвращает тройки (тип, ключ события, текст). При ignore_history=False
        отсеивает то, что уже отправляли — это и есть защита от повторов.
        """
        parts = []

        digest = reports.daily_digest(user)
        if digest:
            parts.append((NotificationLog.Kind.DIGEST, f'{today:%Y-%m-%d}', digest))

        for key, text in reports.limit_warnings(user, today):
            parts.append((NotificationLog.Kind.LIMIT, key, text))

        if ignore_history or self.force:
            return parts
        return [part for part in parts if not self.already_sent(user, part[0], part[1])]

    @staticmethod
    def already_sent(user, kind, key):
        return NotificationLog.objects.filter(user=user, kind=kind, key=key).exists()

    def why_nothing(self, user, today):
        """Объясняет, почему пользователю ничего не уходит.

        Два случая выглядят одинаково, но означают разное: данных нет вовсе
        или всё уже отправлено сегодня.
        """
        if not self.collect(user, today, ignore_history=True):
            return 'за сегодня нет операций, лимиты не превышены'

        last = user.notifications.filter(kind=NotificationLog.Kind.DIGEST).first()
        when = f' в {timezone.localtime(last.sent_at):%H:%M}' if last else ''
        return f'уже отправлено сегодня{when}, нужна повторная отправка'
