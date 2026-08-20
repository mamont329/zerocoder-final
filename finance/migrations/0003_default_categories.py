from django.db import migrations

# Список продублирован намеренно: миграция должна отражать состояние на момент
# её написания и не меняться, даже если набор категорий в коде потом расширят.
DEFAULT_CATEGORIES = [
    ('Еда', 'expense'),
    ('Транспорт', 'expense'),
    ('Развлечения', 'expense'),
    ('Жильё', 'expense'),
    ('Здоровье', 'expense'),
    ('Зарплата', 'income'),
    ('Подработка', 'income'),
]


def create_categories_for_existing_users(apps, schema_editor):
    """Выдаёт стартовый набор категорий пользователям, созданным до появления сигнала."""
    User = apps.get_model('auth', 'User')
    Category = apps.get_model('finance', 'Category')
    for user in User.objects.all():
        existing = set(user.categories.values_list('name', flat=True))
        Category.objects.bulk_create([
            Category(user=user, name=name, type=type_)
            for name, type_ in DEFAULT_CATEGORIES
            if name not in existing
        ])


def noop(apps, schema_editor):
    """Откат ничего не удаляет: пользователь мог успеть завести операции."""


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0002_category_type'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.RunPython(create_categories_for_existing_users, noop),
    ]
