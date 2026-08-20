"""Выдача паролей и доставка их пользователю.

Пароль генерируется системой, а не придумывается администратором: так он
заведомо стойкий, и никто, кроме владельца, его потом не знает — при первом
входе пользователь обязан задать свой.
"""
import logging

from django.core.mail import send_mail
from django.utils.crypto import get_random_string

logger = logging.getLogger(__name__)

# Без похожих друг на друга символов: пароль часто диктуют голосом
# или переписывают руками, а 0/O и 1/l/I в этом деле — источник ошибок
ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789'
PASSWORD_LENGTH = 12


def generate_password():
    return get_random_string(PASSWORD_LENGTH, ALPHABET)


def set_temporary_password(user, password=None):
    """Выдаёт пользователю временный пароль и требует сменить его при входе."""
    password = password or generate_password()
    user.set_password(password)
    user.save(update_fields=['password'])

    profile = user.profile
    profile.must_change_password = True
    profile.save(update_fields=['must_change_password'])
    return password


def _message(user, password, site_url):
    return (
        f'Учётная запись FinControl\n\n'
        f'Логин: {user.username}\n'
        f'Временный пароль: {password}\n\n'
        f'Войдите на {site_url} — при первом входе система попросит задать свой пароль.'
    )


EMAIL = 'email'
TELEGRAM = 'telegram'


def available_channels(user):
    """Куда вообще можно отправить пароль этому пользователю."""
    channels = []
    if user.email:
        channels.append(EMAIL)
    profile = getattr(user, 'profile', None)
    if profile and profile.is_linked:
        channels.append(TELEGRAM)
    return channels


def deliver_password(user, password, site_url='http://127.0.0.1:8000/', channels=None):
    """Отправляет пароль выбранными каналами.

    channels=None — все доступные. Пустой список означает, что администратор
    снял все галочки и передаст пароль сам: на странице он показан с кнопкой
    копирования. Возвращает названия каналов, куда пароль действительно ушёл.
    """
    allowed = set(available_channels(user) if channels is None else channels)
    text = _message(user, password, site_url)
    delivered = []

    if EMAIL in allowed and user.email:
        try:
            send_mail(
                subject='FinControl: доступ к учётной записи',
                message=text,
                from_email=None,
                recipient_list=[user.email],
                fail_silently=False,
            )
            delivered.append(f'почта {user.email}')
        except Exception as error:
            # Не роняем создание пользователя из-за недоступной почты
            logger.warning('Не удалось отправить пароль на почту: %s', error)

    profile = getattr(user, 'profile', None)
    if TELEGRAM in allowed and profile and profile.is_linked:
        from .bot.notify import send_to_chat

        if send_to_chat(profile.telegram_id, text):
            delivered.append('Telegram')

    return delivered
