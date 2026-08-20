from django.apps import AppConfig


class FinanceConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'finance'
    verbose_name = 'Финансы'

    def ready(self):
        # Импорт подключает обработчики сигналов
        from . import signals  # noqa: F401
