import secrets

from django.db import migrations


def create_profiles(apps, schema_editor):
    """Выдаёт профиль пользователям, созданным до появления модели."""
    User = apps.get_model('auth', 'User')
    Profile = apps.get_model('finance', 'Profile')

    for user in User.objects.filter(profile__isnull=True):
        Profile.objects.create(user=user, link_code=secrets.token_hex(3).upper())


def noop(apps, schema_editor):
    """Откат профили не удаляет: в них может быть уже привязанный Telegram."""


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0004_profile'),
    ]

    operations = [
        migrations.RunPython(create_profiles, noop),
    ]
