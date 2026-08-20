from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


class OperationType(models.TextChoices):
    """Направление движения денег. Общее для категорий и операций."""

    INCOME = 'income', 'Доход'
    EXPENSE = 'expense', 'Расход'


# Набор категорий, который получает каждый новый пользователь при регистрации.
# Пользователь может их переименовать или удалить — это лишь стартовая точка.
DEFAULT_CATEGORIES = [
    ('Еда', OperationType.EXPENSE),
    ('Транспорт', OperationType.EXPENSE),
    ('Развлечения', OperationType.EXPENSE),
    ('Жильё', OperationType.EXPENSE),
    ('Здоровье', OperationType.EXPENSE),
    ('Зарплата', OperationType.INCOME),
    ('Подработка', OperationType.INCOME),
]


class Category(models.Model):
    """Категория операций пользователя (например: Еда, Транспорт, Зарплата)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='categories',
        verbose_name='Пользователь',
    )
    name = models.CharField('Название', max_length=100)
    type = models.CharField(
        'Тип',
        max_length=10,
        choices=OperationType.choices,
        default=OperationType.EXPENSE,
    )
    monthly_limit = models.DecimalField(
        'Лимит расходов в месяц',
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text='Только для категорий расходов. При превышении пользователь получит предупреждение',
    )

    class Meta:
        verbose_name = 'категория'
        verbose_name_plural = 'категории'
        ordering = ['type', 'name']
        constraints = [
            models.UniqueConstraint(fields=['user', 'name'], name='unique_category_per_user'),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        if self.type == OperationType.INCOME and self.monthly_limit is not None:
            raise ValidationError({'monthly_limit': 'Лимит задаётся только для категорий расходов.'})


class Transaction(models.Model):
    """Финансовая операция: доход или расход."""

    # Оставлено для обратной совместимости: Transaction.Type.INCOME читается привычнее
    Type = OperationType

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='transactions',
        verbose_name='Пользователь',
    )
    type = models.CharField('Тип', max_length=10, choices=OperationType.choices)
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
        ordering = ['-date', '-created_at']
        indexes = [
            models.Index(fields=['user', 'date'], name='transaction_user_date_idx'),
        ]

    def __str__(self):
        sign = '+' if self.type == OperationType.INCOME else '−'
        return f'{sign}{self.amount} · {self.category} · {self.date}'

    def clean(self):
        if self.category_id is None:
            return
        # Чужую категорию к своей операции подставить нельзя
        if self.user_id and self.category.user_id != self.user_id:
            raise ValidationError({'category': 'Категория принадлежит другому пользователю.'})
        # Доход нельзя записать в категорию расходов и наоборот
        if self.type and self.category.type != self.type:
            raise ValidationError({
                'category': f'Категория «{self.category}» предназначена для операций '
                            f'типа «{self.category.get_type_display()}».'
            })
