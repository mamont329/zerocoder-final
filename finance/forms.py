from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from . import periods
from .models import Category, OperationType, Profile, Transaction

CONTROL = {'class': 'form-control'}
SELECT = {'class': 'form-select'}


class CategorySelect(forms.Select):
    """Список категорий, где каждый пункт помечен типом операции.

    Атрибут data-type читает скрипт на странице и прячет категории,
    не подходящие к выбранному типу операции.
    """

    def create_option(self, name, value, *args, **kwargs):
        option = super().create_option(name, value, *args, **kwargs)
        category = getattr(value, 'instance', None)
        if category is not None:
            option['attrs']['data-type'] = category.type
        return option


class SignUpForm(UserCreationForm):
    """Регистрация. Почта необязательна, но пригодится для уведомлений."""

    email = forms.EmailField(label='Электронная почта', required=False, widget=forms.EmailInput(attrs=CONTROL))

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'email')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ('username', 'password1', 'password2'):
            self.fields[name].widget.attrs.update(CONTROL)


class UserOwnedFormMixin:
    """Привязывает форму к текущему пользователю: он владелец создаваемого объекта."""

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        if user is not None:
            self.instance.user = user


class TransactionForm(UserOwnedFormMixin, forms.ModelForm):
    class Meta:
        model = Transaction
        fields = ('type', 'amount', 'date', 'category', 'description')
        widgets = {
            'type': forms.Select(attrs=SELECT),
            'amount': forms.NumberInput(attrs={**CONTROL, 'step': '0.01', 'min': '0.01', 'placeholder': '0.00'}),
            'date': forms.DateInput(attrs={**CONTROL, 'type': 'date'}, format='%Y-%m-%d'),
            'category': CategorySelect(attrs=SELECT),
            'description': forms.TextInput(attrs={**CONTROL, 'placeholder': 'Необязательно'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.user is not None:
            self.fields['category'].queryset = self.user.categories.all()


class CategoryForm(UserOwnedFormMixin, forms.ModelForm):
    class Meta:
        model = Category
        fields = ('name', 'type', 'monthly_limit')
        widgets = {
            'name': forms.TextInput(attrs={**CONTROL, 'placeholder': 'Например: Продукты'}),
            'type': forms.Select(attrs=SELECT),
            'monthly_limit': forms.NumberInput(attrs={**CONTROL, 'step': '0.01', 'min': '0', 'placeholder': 'Без лимита'}),
        }

    def clean_name(self):
        """Своё сообщение вместо ошибки базы: имена категорий уникальны в пределах пользователя.

        Сравниваем в Python: SQLite приводит регистр только для латиницы,
        поэтому запрос с iexact пропустил бы пару «Еда» и «еда».
        """
        name = self.cleaned_data['name'].strip()
        existing = Category.objects.filter(user=self.user)
        if self.instance.pk:
            existing = existing.exclude(pk=self.instance.pk)
        if any(other.name.casefold() == name.casefold() for other in existing):
            raise forms.ValidationError('Категория с таким названием уже есть.')
        return name


class TransactionFilterForm(forms.Form):
    """Фильтр списка операций: период, тип, категория."""

    period = forms.ChoiceField(
        label='Период',
        choices=periods.PERIOD_CHOICES,
        required=False,
        widget=forms.Select(attrs={**SELECT, 'id': 'id_period'}),
    )
    date_from = forms.DateField(
        label='С', required=False,
        widget=forms.DateInput(attrs={**CONTROL, 'type': 'date'}, format='%Y-%m-%d'),
    )
    date_to = forms.DateField(
        label='По', required=False,
        widget=forms.DateInput(attrs={**CONTROL, 'type': 'date'}, format='%Y-%m-%d'),
    )
    type = forms.ChoiceField(
        label='Тип',
        choices=[('', 'Все')] + OperationType.choices,
        required=False,
        widget=forms.Select(attrs=SELECT),
    )
    category = forms.ModelChoiceField(
        label='Категория',
        queryset=Category.objects.none(),
        required=False,
        empty_label='Все',
        widget=forms.Select(attrs=SELECT),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields['category'].queryset = user.categories.all()

    def clean(self):
        data = super().clean()
        if not data.get('period'):
            data['period'] = periods.MONTH
        start, end = data.get('date_from'), data.get('date_to')
        if start and end and start > end:
            raise forms.ValidationError('Начало периода позже его конца.')
        return data

    def range(self):
        """Границы выбранного периода с учётом произвольных дат."""
        data = self.cleaned_data if self.is_valid() else {}
        period = data.get('period') or periods.MONTH
        if period == periods.CUSTOM:
            return data.get('date_from'), data.get('date_to')
        return periods.period_range(period)


class ProfileForm(forms.ModelForm):
    """Настройки уведомлений. Telegram ID и код правятся только ботом."""

    class Meta:
        model = Profile
        fields = ('daily_report',)
        widgets = {'daily_report': forms.CheckboxInput(attrs={'class': 'form-check-input'})}
