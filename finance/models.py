from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


class Category(models.Model):
    """Категория операций пользователя (например: Еда, Транспорт, Зарплата)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='categories',
        verbose_name='Пользователь',
    )
    name = models.CharField('Название', max_length=100)
    monthly_limit = models.DecimalField(
        'Лимит расходов в месяц',
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text='При превышении лимита пользователь получит предупреждение',
    )

    class Meta:
        verbose_name = 'категория'
        verbose_name_plural = 'категории'
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(fields=['user', 'name'], name='unique_category_per_user'),
        ]

    def __str__(self):
        return self.name


class Transaction(models.Model):
    """Финансовая операция: доход или расход."""

    class Type(models.TextChoices):
        INCOME = 'income', 'Доход'
        EXPENSE = 'expense', 'Расход'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='transactions',
        verbose_name='Пользователь',
    )
    type = models.CharField('Тип', max_length=10, choices=Type.choices)
    amount = models.DecimalField(
        'Сумма',
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0.01)],
    )
    date = models.DateField('Дата', default=timezone.localdate)
    category = models.ForeignKey(
        Category,
        # PROTECT: категорию с операциями удалить нельзя — операции не потеряются
        on_delete=models.PROTECT,
        related_name='transactions',
        verbose_name='Категория',
    )
    description = models.CharField('Описание', max_length=255, blank=True)
    created_at = models.DateTimeField('Создана', auto_now_add=True)

    class Meta:
        verbose_name = 'операция'
        verbose_name_plural = 'операции'
        ordering = ['-date', '-id']

    def __str__(self):
        sign = '+' if self.type == self.Type.INCOME else '−'
        return f'{sign}{self.amount} · {self.category} · {self.date}'
