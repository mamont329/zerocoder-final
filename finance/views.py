import os
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth.views import PasswordChangeView
from django.contrib.auth.models import User
from django.db.models import Count, Max, Min, ProtectedError, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import CreateView, DeleteView, ListView, TemplateView, UpdateView

from . import accounts, analytics, charts, periods
from .analytics import totals
from .forms import (AccountForm, CategoryForm, ProfileForm, SignUpForm, SitePasswordChangeForm,
                    TransactionFilterForm, TransactionForm, UserCreateForm)
from .models import Category, OperationType, Transaction, purge_user

ZERO = Decimal('0.00')

# Начиная с такой длины периода график по дням превращается в частокол —
# переходим на помесячные значения
MONTHLY_THRESHOLD_DAYS = 70


def apply_filters(queryset, form, bounds=None):
    """Сужает выборку по данным формы фильтра. Общее для списка и аналитики.

    bounds позволяет подставить свои границы дат, оставив остальные условия
    формы: так выборка за прошлый период учитывает выбранные тип и категорию.
    """
    if not form.is_valid():
        return queryset

    data = form.cleaned_data
    start, end = bounds if bounds is not None else form.range()
    if start:
        queryset = queryset.filter(date__gte=start)
    if end:
        queryset = queryset.filter(date__lte=end)
    if data.get('type'):
        queryset = queryset.filter(type=data['type'])
    if data.get('category'):
        queryset = queryset.filter(category=data['category'])
    return queryset


class FilteredTransactionsMixin(LoginRequiredMixin):
    """Форма фильтра периода и подпись выбранного диапазона."""

    def get_filter_form(self):
        if not hasattr(self, '_filter_form'):
            self._filter_form = TransactionFilterForm(self.request.GET or None, user=self.request.user)
            self._filter_form.is_valid()
        return self._filter_form

    def get_period(self):
        form = self.get_filter_form()
        if form.is_valid():
            return form.range()
        return periods.period_range(periods.MONTH)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = self.get_filter_form()
        context['filter_form'] = form
        start, end = self.get_period()
        context['period_label'] = periods.period_label(
            form.cleaned_data.get('period') if form.is_valid() else periods.MONTH, start, end,
        )
        return context


class SignUpView(CreateView):
    """Регистрация с автоматическим входом: сразу после неё пользователь в кабинете."""

    form_class = SignUpForm
    template_name = 'registration/signup.html'
    success_url = reverse_lazy('dashboard')

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect('dashboard')
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        response = super().form_valid(form)
        login(self.request, self.object)
        messages.success(self.request, 'Добро пожаловать! Стартовые категории уже созданы.')
        return response


class OwnedQuerysetMixin(LoginRequiredMixin):
    """Ограничивает выборку данными текущего пользователя.

    Единое правило для всех представлений: чужие объекты недоступны даже по прямой ссылке.
    """

    def get_queryset(self):
        return super().get_queryset().filter(user=self.request.user)


class UserFormMixin:
    """Передаёт в форму текущего пользователя — она проставит его владельцем."""

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), 'user': self.request.user}


class PaginationQueryMixin:
    """Отдаёт в шаблон параметры запроса без page.

    Ссылки пагинации подклеивают их к себе, иначе при листании слетает фильтр.
    """

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        query = self.request.GET.copy()
        query.pop('page', None)
        context['query_string'] = query.urlencode()
        return context


class DashboardView(LoginRequiredMixin, TemplateView):
    """Главная: итоги за текущий месяц и последние операции."""

    template_name = 'finance/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        transactions = self.request.user.transactions.all()
        start, end = periods.period_range(periods.MONTH)
        month = transactions.filter(date__range=(start, end))

        context['month'] = totals(month)
        context['total_balance'] = totals(transactions)['balance']
        context['month_label'] = periods.period_label(periods.MONTH, start, end)
        context['recent'] = transactions.select_related('category')[:5]
        context['top_expenses'] = (
            month.filter(type=OperationType.EXPENSE)
            .values('category__name')
            .annotate(total=Sum('amount'))
            .order_by('-total')[:5]
        )
        return context


class TransactionListView(OwnedQuerysetMixin, FilteredTransactionsMixin, PaginationQueryMixin, ListView):
    """История операций с фильтрами по периоду, типу и категории."""

    model = Transaction
    template_name = 'finance/transaction_list.html'
    context_object_name = 'transactions'
    paginate_by = 20

    def get_queryset(self):
        queryset = super().get_queryset().select_related('category')
        return apply_filters(queryset, self.get_filter_form())

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['totals'] = totals(self.get_queryset())
        return context


class AnalyticsView(FilteredTransactionsMixin, TemplateView):
    """Аналитика: динамика по времени, структура расходов, лимиты и советы."""

    template_name = 'finance/analytics.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        start, end = self.get_period()
        queryset = apply_filters(user.transactions.all(), self.get_filter_form())

        # «Всё время» и открытый произвольный период не задают границ — берём их
        # из самих данных. Иначе длину периода не вычислить, и график по ошибке
        # сворачивался в одну месячную точку.
        edges = queryset.aggregate(first=Min('date'), last=Max('date'))
        chart_start = start or edges['first']
        chart_end = end or edges['last']

        # Длинный период рисуем по месяцам, короткий — по дням
        span = (chart_end - chart_start).days if chart_start and chart_end else 0
        by_month = span >= MONTHLY_THRESHOLD_DAYS
        frame = analytics.timeline(queryset, chart_start, chart_end, freq='ME' if by_month else 'D')

        # Сравнение с предыдущим периодом такой же длины
        period = self.get_filter_form().cleaned_data.get('period') if self.get_filter_form().is_valid() else None
        previous_bounds = periods.previous_bounds(chart_start, chart_end, period)
        comparison = None
        # У «всего времени» предыдущего периода нет по определению: до первой
        # операции сравнивать не с чем, вышло бы «было 0» на каждой строке
        if period != periods.ALL and previous_bounds[0]:
            previous = apply_filters(user.transactions.all(), self.get_filter_form(), previous_bounds)
            comparison = analytics.compare(queryset, previous)

        categories = analytics.expenses_by_category(queryset)
        context.update({
            'comparison': comparison,
            'previous_label': periods.period_label(period, *previous_bounds),
            'totals': totals(queryset),
            'categories': categories,
            'limits': analytics.limit_usage(user),
            'advice': analytics.build_advice(user, queryset, start, end),
            'timeline_chart': charts.timeline_chart(frame, by_month=by_month),
            'cumulative_chart': charts.cumulative_chart(frame, by_month=by_month),
            'category_chart': charts.category_chart(categories),
            'operations_count': queryset.count(),
        })
        return context


class TransactionCreateView(LoginRequiredMixin, UserFormMixin, CreateView):
    model = Transaction
    form_class = TransactionForm
    template_name = 'finance/transaction_form.html'
    success_url = reverse_lazy('transaction_list')
    extra_context = {'title': 'Новая операция', 'submit': 'Добавить'}

    def form_valid(self, form):
        messages.success(self.request, 'Операция добавлена.')
        return super().form_valid(form)


class TransactionUpdateView(OwnedQuerysetMixin, UserFormMixin, UpdateView):
    model = Transaction
    form_class = TransactionForm
    template_name = 'finance/transaction_form.html'
    success_url = reverse_lazy('transaction_list')
    extra_context = {'title': 'Изменение операции', 'submit': 'Сохранить'}

    def form_valid(self, form):
        messages.success(self.request, 'Операция изменена.')
        return super().form_valid(form)


class TransactionDeleteView(OwnedQuerysetMixin, DeleteView):
    model = Transaction
    template_name = 'finance/confirm_delete.html'
    success_url = reverse_lazy('transaction_list')
    extra_context = {'title': 'Удаление операции'}

    def form_valid(self, form):
        messages.success(self.request, 'Операция удалена.')
        return super().form_valid(form)


class CategoryListView(OwnedQuerysetMixin, PaginationQueryMixin, ListView):
    """Категории пользователя с суммой операций по каждой."""

    model = Category
    template_name = 'finance/category_list.html'
    context_object_name = 'categories'
    paginate_by = 10

    def get_queryset(self):
        # Сортировку задаём явно: с annotate() умолчание из Meta теряется,
        # а без порядка страницы пагинации могут дублировать строки
        return (
            super().get_queryset()
            .annotate(total=Sum('transactions__amount'))
            .order_by('type', 'name')
        )


class CategoryCreateView(LoginRequiredMixin, UserFormMixin, CreateView):
    model = Category
    form_class = CategoryForm
    template_name = 'finance/category_form.html'
    success_url = reverse_lazy('category_list')
    extra_context = {'title': 'Новая категория', 'submit': 'Создать'}

    def form_valid(self, form):
        messages.success(self.request, 'Категория создана.')
        return super().form_valid(form)


class CategoryUpdateView(OwnedQuerysetMixin, UserFormMixin, UpdateView):
    model = Category
    form_class = CategoryForm
    template_name = 'finance/category_form.html'
    success_url = reverse_lazy('category_list')
    extra_context = {'title': 'Изменение категории', 'submit': 'Сохранить'}

    def form_valid(self, form):
        messages.success(self.request, 'Категория изменена.')
        return super().form_valid(form)


class CategoryDeleteView(OwnedQuerysetMixin, DeleteView):
    model = Category
    template_name = 'finance/confirm_delete.html'
    success_url = reverse_lazy('category_list')
    extra_context = {'title': 'Удаление категории'}

    def form_valid(self, form):
        """Категорию с операциями удалять нельзя — объясняем это вместо страницы ошибки."""
        count = self.object.transactions.count()
        try:
            response = super().form_valid(form)
        except ProtectedError:
            messages.error(
                self.request,
                f'Нельзя удалить категорию «{self.object}»: с ней связано операций — {count}. '
                f'Перенесите их в другую категорию или удалите.',
            )
            return redirect('category_list')
        messages.success(self.request, 'Категория удалена.')
        return response


class ProfileView(LoginRequiredMixin, UpdateView):
    """Профиль: привязка Telegram и настройки уведомлений."""

    form_class = ProfileForm
    template_name = 'finance/profile.html'
    success_url = reverse_lazy('profile')

    def get_object(self, queryset=None):
        return self.request.user.profile

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['profile'] = self.object
        context['bot_username'] = os.getenv('TELEGRAM_BOT_USERNAME', '')
        context['is_last_staff'] = is_last_active_staff(self.request.user)
        return context

    def form_valid(self, form):
        messages.success(self.request, 'Настройки сохранены.')
        return super().form_valid(form)


class TelegramUnlinkView(LoginRequiredMixin, View):
    """Отвязка Telegram из кабинета."""

    def post(self, request, *args, **kwargs):
        request.user.profile.unlink()
        messages.success(request, 'Telegram отвязан, код привязки обновлён.')
        return redirect('profile')


class AccountUpdateView(LoginRequiredMixin, UpdateView):
    """Редактирование своих учётных данных."""

    form_class = AccountForm
    template_name = 'finance/account_form.html'
    success_url = reverse_lazy('profile')

    def get_object(self, queryset=None):
        return self.request.user

    def form_valid(self, form):
        messages.success(self.request, 'Данные аккаунта сохранены.')
        return super().form_valid(form)


def is_last_active_staff(user):
    """Последний сотрудник с доступом к управлению пользователями.

    Если он отключит себя, включить кого-либо обратно будет некому —
    останется только консоль сервера.
    """
    if not user.is_staff:
        return False
    return not User.objects.filter(is_staff=True, is_active=True).exclude(pk=user.pk).exists()


class AccountDeactivateView(LoginRequiredMixin, View):
    """Отключение своей учётной записи.

    Данные не стираются: аккаунт помечается неактивным, вход и бот перестают
    работать. Безвозвратное удаление — только через раздел «Пользователи».
    """

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and is_last_active_staff(request.user):
            messages.error(
                request,
                'Вы единственный сотрудник с доступом к управлению пользователями — '
                'отключить себя нельзя. Сначала назначьте другого сотрудника.',
            )
            return redirect('profile')
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        return render(request, 'finance/account_deactivate.html')

    def post(self, request, *args, **kwargs):
        password = request.POST.get('password', '')
        if not request.user.check_password(password):
            messages.error(request, 'Неверный пароль — аккаунт не отключён.')
            return redirect('account_deactivate')

        user = request.user
        user.is_active = False
        user.save(update_fields=['is_active'])
        # Telegram отвязывается сразу: иначе бот продолжит слать отчёты
        if hasattr(user, 'profile'):
            user.profile.unlink()

        logout(request)
        messages.success(
            request,
            'Аккаунт отключён. Данные сохранены — восстановить доступ может администратор.',
        )
        return redirect('login')


class StaffRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Раздел управления пользователями доступен только персоналу."""

    def test_func(self):
        return self.request.user.is_staff


class UserListView(StaffRequiredMixin, PaginationQueryMixin, ListView):
    """Список пользователей сервиса с числом операций."""

    model = User
    template_name = 'finance/user_list.html'
    context_object_name = 'users'
    paginate_by = 20

    def get_queryset(self):
        return User.objects.annotate(operations=Count('transactions')).order_by('-is_active', 'username')


class UserCreateView(StaffRequiredMixin, CreateView):
    """Создание пользователя администратором с временным паролем."""

    form_class = UserCreateForm
    template_name = 'finance/user_form.html'
    extra_context = {'title': 'Новый пользователь', 'submit': 'Создать'}

    def form_valid(self, form):
        user = form.save()
        password = accounts.set_temporary_password(user)
        delivered = accounts.deliver_password(user, password, self.request.build_absolute_uri('/'))

        # Пароль показывается один раз, поэтому кладём его в сессию,
        # а не в адрес страницы: адреса остаются в истории браузера и логах
        self.request.session['issued_credentials'] = {
            'user_id': user.pk,
            'username': user.username,
            'password': password,
            'delivered': delivered,
            'reason': 'created',
        }
        return redirect('user_credentials')


class UserResetPasswordView(StaffRequiredMixin, View):
    """Сброс пароля сотрудником: выдаём новый и требуем сменить его при входе."""

    def get(self, request, pk, *args, **kwargs):
        account = get_object_or_404(User, pk=pk)
        return render(request, 'finance/user_reset_confirm.html', {
            'account': account,
            'channels': accounts.available_channels(account),
        })

    def post(self, request, pk, *args, **kwargs):
        user = get_object_or_404(User, pk=pk)
        # Галочки каналов: администратор может снять любую или все
        selected = request.POST.getlist('channels')
        password = accounts.set_temporary_password(user)
        delivered = accounts.deliver_password(
            user, password, request.build_absolute_uri('/'), channels=selected,
        )

        request.session['issued_credentials'] = {
            'user_id': user.pk,
            'username': user.username,
            'password': password,
            'delivered': delivered,
            'reason': 'reset',
        }
        return redirect('user_credentials')


class UserCredentialsView(StaffRequiredMixin, TemplateView):
    """Показ выданного пароля — ровно один раз."""

    template_name = 'finance/user_credentials.html'

    def get(self, request, *args, **kwargs):
        # pop, а не get: обновление страницы не должно показывать пароль снова
        credentials = request.session.pop('issued_credentials', None)
        if not credentials:
            messages.info(request, 'Пароль уже был показан. Если он потерян — сбросьте его заново.')
            return redirect('user_list')
        return self.render_to_response(self.get_context_data(credentials=credentials))


class UserToggleActiveView(StaffRequiredMixin, View):
    """Включение и отключение чужой учётной записи."""

    def post(self, request, pk, *args, **kwargs):
        user = get_object_or_404(User, pk=pk)
        if user == request.user:
            messages.error(request, 'Нельзя отключить самого себя.')
            return redirect('user_list')

        user.is_active = not user.is_active
        user.save(update_fields=['is_active'])
        if not user.is_active and hasattr(user, 'profile'):
            user.profile.unlink()

        state = 'включён' if user.is_active else 'отключён'
        messages.success(request, f'Пользователь {user.username} {state}.')
        return redirect('user_list')


class UserDeleteView(StaffRequiredMixin, DeleteView):
    """Безвозвратное удаление пользователя вместе со всеми его данными."""

    model = User
    template_name = 'finance/user_confirm_delete.html'
    success_url = reverse_lazy('user_list')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['operations'] = self.object.transactions.count()
        return context

    def form_valid(self, form):
        if self.object == self.request.user:
            messages.error(self.request, 'Нельзя удалить самого себя.')
            return redirect('user_list')

        username = self.object.username
        purge_user(self.object)
        messages.success(self.request, f'Пользователь {username} удалён со всеми данными.')
        return redirect(self.success_url)


class SitePasswordChangeView(LoginRequiredMixin, PasswordChangeView):
    """Смена пароля со снятием требования сменить его."""

    form_class = SitePasswordChangeForm
    template_name = 'finance/password_change_form.html'
    success_url = reverse_lazy('password_change_done')

    def is_forced(self):
        return self.request.user.profile.must_change_password

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), 'forced': self.is_forced()}

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['forced'] = self.is_forced()
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        profile = self.request.user.profile
        if profile.must_change_password:
            profile.must_change_password = False
            profile.save(update_fields=['must_change_password'])
            messages.success(self.request, 'Пароль задан, доступ к сервису открыт.')
        return response
