from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import ProtectedError, Sum
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, ListView, TemplateView, UpdateView

from . import analytics, charts, periods
from .analytics import totals
from .forms import CategoryForm, SignUpForm, TransactionFilterForm, TransactionForm
from .models import Category, OperationType, Transaction

ZERO = Decimal('0.00')

# Начиная с такой длины периода график по дням превращается в частокол —
# переходим на помесячные значения
MONTHLY_THRESHOLD_DAYS = 70


def apply_filters(queryset, form):
    """Сужает выборку по данным формы фильтра. Общее для списка и аналитики."""
    if not form.is_valid():
        return queryset

    data = form.cleaned_data
    start, end = form.range()
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

        # Длинный период рисуем по месяцам, короткий — по дням
        span = (end - start).days if start and end else None
        by_month = span is None or span >= MONTHLY_THRESHOLD_DAYS
        frame = analytics.timeline(queryset, start, end, freq='ME' if by_month else 'D')

        categories = analytics.expenses_by_category(queryset)
        context.update({
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
