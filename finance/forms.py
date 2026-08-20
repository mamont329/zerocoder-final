from django import forms
from django.utils.safestring import mark_safe
from django.contrib.auth.forms import PasswordChangeForm, UserCreationForm
from django.contrib.auth.models import User

from . import periods
from .models import Category, OperationType, Profile, SavedReport, Transaction

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


class UniqueUsernameMixin:
    """Логин уникален: под ним входят, и двух одинаковых быть не может."""

    def clean_username(self):
        username = self.cleaned_data['username'].strip()
        taken = User.objects.filter(username__iexact=username).exclude(pk=self.instance.pk)
        if taken.exists():
            raise forms.ValidationError('Такое имя пользователя уже занято.')
        return username


class AccountForm(UniqueUsernameMixin, forms.ModelForm):
    """Данные учётной записи: логин, ФИО и почта.

    Отчества в модели Django нет, поэтому оно живёт в профиле — форма
    сохраняет обе части вместе, чтобы для пользователя это была одна анкета.
    """

    middle_name = forms.CharField(label='Отчество', required=False,
                                  widget=forms.TextInput(attrs=CONTROL))

    class Meta:
        model = User
        fields = ('username', 'last_name', 'first_name', 'email')
        labels = {
            'username': 'Имя пользователя',
            'last_name': 'Фамилия',
            'first_name': 'Имя',
            'email': 'Электронная почта',
        }
        help_texts = {'username': 'Используется для входа'}
        widgets = {
            'username': forms.TextInput(attrs=CONTROL),
            'last_name': forms.TextInput(attrs=CONTROL),
            'first_name': forms.TextInput(attrs=CONTROL),
            'email': forms.EmailInput(attrs=CONTROL),
        }

    # Отчество показываем сразу после имени, а не в конце анкеты
    field_order = ('username', 'last_name', 'first_name', 'middle_name', 'email')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields['middle_name'].initial = self.instance.profile.middle_name

    def save(self, commit=True):
        user = super().save(commit)
        profile = user.profile
        profile.middle_name = self.cleaned_data['middle_name'].strip()
        profile.save(update_fields=['middle_name'])
        return user


class UserCreateForm(UniqueUsernameMixin, forms.ModelForm):
    """Заведение пользователя администратором.

    Пароль не запрашивается: он генерируется системой и показывается один раз
    после создания. Администратору не приходится ничего выдумывать, а
    пользователь всё равно сменит его при первом входе.
    """

    middle_name = forms.CharField(label='Отчество', required=False,
                                  widget=forms.TextInput(attrs=CONTROL))
    is_staff = forms.BooleanField(
        label='Сделать сотрудником сервиса',
        required=False,
        help_text='Сотрудники видят раздел «Пользователи»: заводят учётные записи, '
                  'отключают доступ, сбрасывают пароли и удаляют аккаунты',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
    )

    class Meta:
        model = User
        fields = ('username', 'last_name', 'first_name', 'email', 'is_staff')
        labels = {
            'username': 'Имя пользователя',
            'last_name': 'Фамилия',
            'first_name': 'Имя',
            'email': 'Электронная почта',
        }
        help_texts = {
            'username': 'Используется для входа',
            'email': 'Если указать, пароль уйдёт письмом',
        }
        widgets = {
            'username': forms.TextInput(attrs=CONTROL),
            'last_name': forms.TextInput(attrs=CONTROL),
            'first_name': forms.TextInput(attrs=CONTROL),
            'email': forms.EmailInput(attrs=CONTROL),
        }

    field_order = ('username', 'last_name', 'first_name', 'middle_name', 'email', 'is_staff')

    def save(self, commit=True):
        user = super().save(commit)
        profile = user.profile
        profile.middle_name = self.cleaned_data['middle_name'].strip()
        profile.save(update_fields=['middle_name'])
        return user


class SitePasswordChangeForm(PasswordChangeForm):
    """Смена пароля с понятными подписями и проверкой на повтор.

    Подписи зависят от того, обязательная эта смена или добровольная:
    при обязательной «старый пароль» — это временный, выданный администратором,
    и называть его надо именно так, иначе непонятно, какой из паролей вводить.
    """

    def __init__(self, user, *args, forced=False, **kwargs):
        super().__init__(user, *args, **kwargs)

        if forced:
            self.fields['old_password'].label = 'Временный пароль'
            self.fields['old_password'].help_text = (
                'Тот, что выдал администратор: пришёл письмом, в Telegram '
                'или был передан лично'
            )
        else:
            self.fields['old_password'].label = 'Текущий пароль'
            self.fields['old_password'].help_text = 'Пароль, которым вы пользуетесь сейчас'

        self.fields['new_password1'].label = 'Новый пароль'
        self.fields['new_password2'].label = 'Повторите новый пароль'

        # Django перечисляет требования своих валидаторов списком — дописываем
        # своё пунктом в тот же список, чтобы правило было видно заранее,
        # а не всплывало ошибкой после отправки формы
        requirement = 'Новый пароль должен отличаться от текущего.'
        help_text = self.fields['new_password1'].help_text
        if '</ul>' in help_text:
            help_text = help_text.replace('</ul>', f'<li>{requirement}</li></ul>')
        else:
            help_text = f'{help_text} {requirement}'.strip()
        self.fields['new_password1'].help_text = mark_safe(help_text)

    def clean_new_password1(self):
        """Новый пароль должен отличаться от прежнего.

        Django этого не проверяет, а без проверки обязательная смена
        обходится вводом того же самого пароля — и временный пароль,
        который видел администратор, остаётся рабочим.
        """
        password = self.cleaned_data['new_password1']
        if self.user.check_password(password):
            raise forms.ValidationError('Новый пароль совпадает с текущим — придумайте другой.')
        return password


class SavedReportForm(UserOwnedFormMixin, forms.ModelForm):
    """Сохранение текущего набора фильтров под своим именем.

    Сами фильтры берутся из формы фильтра, поэтому здесь только название:
    пользователь не заполняет то, что уже выбрал на странице.
    """

    class Meta:
        model = SavedReport
        fields = ('name',)
        labels = {'name': 'Название отчёта'}
        widgets = {'name': forms.TextInput(attrs={
            **CONTROL, 'placeholder': 'Например: Месячный анализ',
        })}

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        existing = SavedReport.objects.filter(user=self.user).exclude(pk=self.instance.pk)
        if any(report.name.casefold() == name.casefold() for report in existing):
            raise forms.ValidationError('Отчёт с таким названием уже сохранён.')
        return name
