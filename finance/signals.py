from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import DEFAULT_CATEGORIES, Category


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_default_categories(sender, instance, created, **kwargs):
    """Выдаёт новому пользователю стартовый набор категорий.

    Сигнал, а не код формы регистрации: так набор появится и при регистрации
    на сайте, и при createsuperuser, и у пользователей, пришедших из Telegram.
    """
    if not created:
        return
    Category.objects.bulk_create(
        [Category(user=instance, name=name, type=type_) for name, type_ in DEFAULT_CATEGORIES],
        ignore_conflicts=True,
    )
