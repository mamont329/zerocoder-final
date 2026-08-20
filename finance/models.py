import secrets
from urllib.parse import urlencode

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


class Profile(models.Model):
    """Настройки пользователя и его связь с Telegram.

    Создаётся вместе с пользователем. Привязка к чату происходит по коду:
    пользователь берёт код в кабинете и отправляет боту командой /start.
    """

    CODE_LENGTH = 6

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profile',
        verbose_name='Пользователь',
    )
    middle_name = models.CharField(
        'Отчество',
        max_length=150,
        blank=True,
        help_text='В модели Django его нет, поэтому храним рядом с остальными настройками',
    )
    must_change_password = models.BooleanField(
        'Требуется смена пароля',
        default=False,
        help_text='Ставится при заведении учётной записи и после сброса пароля',
    )
    telegram_id = models.BigIntegerField(
        'Telegram ID',
        null=True,
        blank=True,
        unique=True,
        help_text='Идентификатор чата, куда бот шлёт отчёты',
    )
    link_code = models.CharField('Код привязки', max_length=12, unique=True)
    daily_report = models.BooleanField(
        'Ежедневный отчёт',
        default=True,
        help_text='Присылать сводку за день в Telegram',
    )

    class Meta:
        verbose_name = 'профиль'
        verbose_name_plural = 'профили'

    def __str__(self):
        return f'Профиль {self.user}'

    @staticmethod
    def generate_code():
        """Код привязки: короткий, но неугадываемый — по нему бот находит аккаунт."""
        return secrets.token_hex(Profile.CODE_LENGTH // 2).upper()

    def save(self, *args, **kwargs):
        if not self.link_code:
            self.link_code = self.generate_code()
        super().save(*args, **kwargs)

    @property
    def is_linked(self):
        return self.telegram_id is not None

    @property
    def full_name(self):
        """Фамилия, имя и отчество — в привычном для документов порядке."""
        parts = [self.user.last_name, self.user.first_name, self.middle_name]
        return ' '.join(part for part in parts if part)

    def unlink(self):
        """Отвязывает Telegram и выдаёт новый код: старый мог остаться в чужой переписке."""
        self.telegram_id = None
        self.link_code = self.generate_code()
        self.save(update_fields=['telegram_id', 'link_code'])


class NotificationLog(models.Model):
    """Что и когда бот уже отправлял пользователю.

    Нужна, чтобы не повторяться: предупреждение о превышенном лимите
    интересно один раз за месяц, а не каждый вечер до конца месяца.
    """

    class Kind(models.TextChoices):
        DIGEST = 'digest', 'Сводка за день'
        LIMIT = 'limit', 'Превышение лимита'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications',
        verbose_name='Пользователь',
    )
    kind = models.CharField('Тип', max_length=20, choices=Kind.choices)
    key = models.CharField(
        'Ключ события',
        max_length=100,
        help_text='Отличает события друг от друга: дата сводки, категория и месяц лимита',
    )
    sent_at = models.DateTimeField('Отправлено', auto_now_add=True)

    class Meta:
        verbose_name = 'уведомление'
        verbose_name_plural = 'уведомления'
        ordering = ['-sent_at']
        constraints = [
            models.UniqueConstraint(fields=['user', 'kind', 'key'], name='unique_notification'),
        ]

    def __str__(self):
        return f'{self.get_kind_display()} · {self.key}'

    @classmethod
    def send_once(cls, user, kind, key):
        """Отмечает событие отправленным. False — значит уже отправляли.

        Ограничение уникальности в базе делает проверку надёжной даже если
        рассылка случайно запустится дважды одновременно.
        """
        _, created = cls.objects.get_or_create(user=user, kind=kind, key=key)
        return created


class SavedReport(models.Model):
    """Избранный отчёт — сохранённый набор фильтров под своим именем."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='saved_reports',
        verbose_name='Пользователь',
    )
    name = models.CharField('Название', max_length=100)
    period = models.CharField('Период', max_length=20)
    date_from = models.DateField('С', null=True, blank=True)
    date_to = models.DateField('По', null=True, blank=True)
    type = models.CharField('Тип операций', max_length=10, blank=True)
    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='saved_reports',
        verbose_name='Категория',
    )
    created_at = models.DateTimeField('Создан', auto_now_add=True)

    class Meta:
        verbose_name = 'сохранённый отчёт'
        verbose_name_plural = 'сохранённые отчёты'
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(fields=['user', 'name'], name='unique_report_per_user'),
        ]

    def __str__(self):
        return self.name

    def as_query(self):
        """Параметры запроса, восстанавливающие фильтр на странице."""
        params = {'period': self.period}
        if self.date_from:
            params['date_from'] = self.date_from.isoformat()
        if self.date_to:
            params['date_to'] = self.date_to.isoformat()
        if self.type:
            params['type'] = self.type
        if self.category_id:
            params['category'] = str(self.category_id)
        return urlencode(params)


def purge_user(user):
    """Удаляет пользователя вместе со всеми его данными.

    Операции убираются первым шагом. Категории ушли бы каскадом вслед за
    владельцем, но их держат операции с on_delete=PROTECT, а план удаления
    Django строит до сигналов — то есть падает раньше, чем что-то можно
    поправить обработчиком.
    """
    Transaction.objects.filter(user=user).delete()
    user.delete()
