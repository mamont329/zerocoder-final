from datetime import timedelta
from decimal import Decimal

from asgiref.sync import async_to_sync
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from . import analytics, periods, reports
from .bot import services
from .bot.keyboards import categories_keyboard, report_actions
from .models import Category, OperationType, Transaction


class SignUpTests(TestCase):
    def test_new_user_gets_default_categories(self):
        """После регистрации пользователь сразу может добавлять операции."""
        response = self.client.post(reverse('signup'), {
            'username': 'newbie',
            'password1': 'Sl0zhniy-Parol',
            'password2': 'Sl0zhniy-Parol',
        })
        self.assertRedirects(response, reverse('dashboard'))
        user = User.objects.get(username='newbie')
        self.assertEqual(user.categories.count(), 7)
        self.assertTrue(user.categories.filter(type=OperationType.INCOME).exists())


class AccessTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user('owner', password='pass')
        self.stranger = User.objects.create_user('stranger', password='pass')
        self.category = self.owner.categories.get(name='Еда')
        self.transaction = Transaction.objects.create(
            user=self.owner, type=OperationType.EXPENSE,
            amount=Decimal('100.00'), category=self.category,
        )

    def test_anonymous_is_redirected_to_login(self):
        response = self.client.get(reverse('transaction_list'))
        self.assertIn(reverse('login'), response.url)

    def test_stranger_cannot_open_foreign_transaction(self):
        """Чужая операция недоступна даже по прямой ссылке."""
        self.client.force_login(self.stranger)
        response = self.client.get(reverse('transaction_edit', args=[self.transaction.pk]))
        self.assertEqual(response.status_code, 404)

    def test_form_offers_only_own_categories(self):
        self.client.force_login(self.stranger)
        response = self.client.get(reverse('transaction_add'))
        categories = response.context['form'].fields['category'].queryset
        self.assertEqual(list(categories), list(self.stranger.categories.all()))


class TransactionFlowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('user', password='pass')
        self.client.force_login(self.user)
        self.food = self.user.categories.get(name='Еда')
        self.salary = self.user.categories.get(name='Зарплата')

    def test_add_transaction(self):
        response = self.client.post(reverse('transaction_add'), {
            'type': OperationType.EXPENSE,
            'amount': '250.50',
            'date': timezone.localdate().isoformat(),
            'category': self.food.pk,
            'description': 'Обед',
        })
        self.assertRedirects(response, reverse('transaction_list'))
        self.assertEqual(self.user.transactions.count(), 1)

    def test_type_must_match_category(self):
        """Доход в категорию расходов форма не пропускает."""
        response = self.client.post(reverse('transaction_add'), {
            'type': OperationType.INCOME,
            'amount': '250.50',
            'date': timezone.localdate().isoformat(),
            'category': self.food.pk,
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('category', response.context['form'].errors)
        self.assertEqual(self.user.transactions.count(), 0)

    def test_period_filter_excludes_old_operations(self):
        today = timezone.localdate()
        Transaction.objects.create(user=self.user, type=OperationType.EXPENSE,
                                   amount=Decimal('10.00'), category=self.food, date=today)
        Transaction.objects.create(user=self.user, type=OperationType.EXPENSE,
                                   amount=Decimal('20.00'), category=self.food,
                                   date=today - timedelta(days=1))

        response = self.client.get(reverse('transaction_list'), {'period': 'day'})
        self.assertEqual(len(response.context['transactions']), 1)
        self.assertEqual(response.context['totals']['expense'], Decimal('10.00'))

    def test_custom_period_with_one_bound(self):
        """Произвольный период может быть открытым: указано только «с» или только «по»."""
        today = timezone.localdate()
        Transaction.objects.create(user=self.user, type=OperationType.EXPENSE,
                                   amount=Decimal('10.00'), category=self.food, date=today)
        Transaction.objects.create(user=self.user, type=OperationType.EXPENSE,
                                   amount=Decimal('20.00'), category=self.food,
                                   date=today - timedelta(days=10))

        only_from = self.client.get(reverse('transaction_list'), {
            'period': 'custom', 'date_from': today.isoformat(), 'date_to': '',
        })
        self.assertEqual(only_from.status_code, 200)
        self.assertEqual(only_from.context['totals']['expense'], Decimal('10.00'))

        only_to = self.client.get(reverse('transaction_list'), {
            'period': 'custom', 'date_from': '', 'date_to': (today - timedelta(days=5)).isoformat(),
        })
        self.assertEqual(only_to.status_code, 200)
        self.assertEqual(only_to.context['totals']['expense'], Decimal('20.00'))

        both_empty = self.client.get(reverse('transaction_list'), {
            'period': 'custom', 'date_from': '', 'date_to': '',
        })
        self.assertEqual(both_empty.status_code, 200)
        self.assertEqual(both_empty.context['totals']['expense'], Decimal('30.00'))

    def test_totals_on_dashboard(self):
        today = timezone.localdate()
        Transaction.objects.create(user=self.user, type=OperationType.INCOME,
                                   amount=Decimal('1000.00'), category=self.salary, date=today)
        Transaction.objects.create(user=self.user, type=OperationType.EXPENSE,
                                   amount=Decimal('300.00'), category=self.food, date=today)

        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.context['month']['income'], Decimal('1000.00'))
        self.assertEqual(response.context['month']['expense'], Decimal('300.00'))
        self.assertEqual(response.context['month']['balance'], Decimal('700.00'))


class CategoryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('user', password='pass')
        self.client.force_login(self.user)

    def test_duplicate_name_rejected(self):
        response = self.client.post(reverse('category_add'), {'name': 'Еда', 'type': OperationType.EXPENSE})
        self.assertEqual(response.status_code, 200)
        self.assertIn('name', response.context['form'].errors)

    def test_category_with_transactions_is_protected(self):
        """Удаление категории с операциями не проходит, история остаётся целой."""
        food = self.user.categories.get(name='Еда')
        Transaction.objects.create(user=self.user, type=OperationType.EXPENSE,
                                   amount=Decimal('10.00'), category=food)

        response = self.client.post(reverse('category_delete', args=[food.pk]), follow=True)
        self.assertTrue(Category.objects.filter(pk=food.pk).exists())
        self.assertContains(response, 'Нельзя удалить категорию')

    def test_category_list_is_paginated(self):
        """Категории разбиваются по 10 на страницу — независимо от списка операций."""
        # 7 стандартных категорий + 15 созданных = 22, то есть три страницы
        Category.objects.bulk_create([
            Category(user=self.user, name=f'Категория {i}', type=OperationType.EXPENSE)
            for i in range(15)
        ])
        response = self.client.get(reverse('category_list'))
        self.assertTrue(response.context['is_paginated'])
        self.assertEqual(response.context['paginator'].num_pages, 3)
        self.assertEqual(len(response.context['categories']), 10)

        last = self.client.get(reverse('category_list'), {'page': 3})
        self.assertEqual(len(last.context['categories']), 2)

    def test_empty_category_is_deleted(self):
        empty = Category.objects.create(user=self.user, name='Прочее', type=OperationType.EXPENSE)
        self.client.post(reverse('category_delete', args=[empty.pk]))
        self.assertFalse(Category.objects.filter(pk=empty.pk).exists())


class AnalyticsTests(TestCase):
    """Аналитика: агрегаты, ряды по времени, лимиты, аномалии и советы."""

    def setUp(self):
        self.user = User.objects.create_user('analyst', password='pass')
        self.client.force_login(self.user)
        self.food = self.user.categories.get(name='Еда')
        self.salary = self.user.categories.get(name='Зарплата')
        self.today = timezone.localdate()
        self.month_start = self.today.replace(day=1)

    def spend(self, amount, days_ago=0, category=None):
        return Transaction.objects.create(
            user=self.user, type=OperationType.EXPENSE, amount=Decimal(amount),
            category=category or self.food, date=self.today - timedelta(days=days_ago),
        )

    def test_page_opens_without_data(self):
        """Пустой период не ломает страницу: графиков нет, есть объяснение."""
        response = self.client.get(reverse('analytics'))
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context['timeline_chart'])
        self.assertEqual(response.context['advice'][0].level, 'info')

    def test_charts_are_built_when_data_exists(self):
        self.spend('500.00')
        Transaction.objects.create(user=self.user, type=OperationType.INCOME,
                                   amount=Decimal('1000.00'), category=self.salary, date=self.today)

        response = self.client.get(reverse('analytics'))
        self.assertIn('plotly', response.context['timeline_chart'])
        self.assertIn('plotly', response.context['category_chart'])

    def test_timeline_fills_gaps_with_zero(self):
        """Дни без операций попадают в ряд нулями, иначе график врёт о динамике."""
        self.spend('100.00', days_ago=2)
        frame = analytics.timeline(self.user.transactions.all(),
                                   self.today - timedelta(days=4), self.today)
        self.assertEqual(len(frame), 5)
        self.assertEqual(frame['expense'].sum(), 100.0)
        self.assertEqual(frame['income'].sum(), 0.0)

    def test_category_shares(self):
        self.spend('750.00')
        self.spend('250.00', category=self.user.categories.get(name='Транспорт'))

        rows = analytics.expenses_by_category(self.user.transactions.all())
        self.assertEqual(rows[0]['name'], 'Еда')
        self.assertAlmostEqual(rows[0]['percent'], 75.0)
        self.assertAlmostEqual(rows[1]['percent'], 25.0)

    def test_limit_is_always_about_current_month(self):
        """Годовой фильтр не должен превращать месячный лимит в годовой."""
        self.food.monthly_limit = Decimal('1000.00')
        self.food.save()
        self.spend('900.00')                      # текущий месяц
        self.spend('5000.00', days_ago=200)       # прошлый год

        response = self.client.get(reverse('analytics'), {'period': 'year'})
        usage = response.context['limits'][0]
        self.assertEqual(usage['spent'], Decimal('900.00'))
        self.assertFalse(usage['over'])

    def test_limit_exceeded_produces_warning(self):
        self.food.monthly_limit = Decimal('1000.00')
        self.food.save()
        self.spend('1500.00')

        response = self.client.get(reverse('analytics'))
        levels = {item.level for item in response.context['advice']}
        titles = ' '.join(item.title for item in response.context['advice'])
        self.assertIn('danger', levels)
        self.assertIn('Лимит превышен', titles)

    def test_anomaly_detected(self):
        """Траты вдвое выше средних за три прошлых периода — это аномалия."""
        for days in (35, 65, 95):
            self.spend('1000.00', days_ago=days)
        self.spend('4000.00', days_ago=1)

        anomalies = analytics.find_anomalies(self.user, self.month_start, self.today)
        self.assertTrue(any(item['name'] == 'Еда' for item in anomalies))

    def test_stable_spending_is_not_anomaly(self):
        for days in (35, 65, 95):
            self.spend('1000.00', days_ago=days)
        self.spend('1050.00', days_ago=1)

        self.assertEqual(analytics.find_anomalies(self.user, self.month_start, self.today), [])


class BotServiceTests(TestCase):
    """Логика бота, которая работает с базой: привязка, категории, операции."""

    def setUp(self):
        self.user = User.objects.create_user('tguser', password='pass')
        self.chat_id = 555000111

    def call(self, service, *args):
        """Запускает асинхронный сервис бота из синхронного теста.

        Именно async_to_sync, а не asyncio.run: он возвращает обращения к базе
        в текущий поток, иначе SQLite отдаёт «database table is locked».
        """
        return async_to_sync(service)(*args)

    def test_link_by_code(self):
        code = self.user.profile.link_code
        linked = self.call(services.link_account, self.chat_id, code.lower())
        self.assertEqual(linked, self.user)
        self.assertEqual(self.call(services.get_user, self.chat_id), self.user)

    def test_wrong_code_does_not_link(self):
        self.assertIsNone(self.call(services.link_account, self.chat_id, 'НЕВЕРНЫЙ'))
        self.assertIsNone(self.call(services.get_user, self.chat_id))

    def test_chat_serves_only_one_account(self):
        """Привязка нового аккаунта к тому же чату отбирает его у прежнего."""
        other = User.objects.create_user('other', password='pass')
        self.call(services.link_account, self.chat_id, self.user.profile.link_code)
        self.call(services.link_account, self.chat_id, other.profile.link_code)

        self.user.profile.refresh_from_db()
        self.assertIsNone(self.user.profile.telegram_id)
        self.assertEqual(self.call(services.get_user, self.chat_id), other)

    def test_unlink_changes_code(self):
        old_code = self.user.profile.link_code
        self.call(services.link_account, self.chat_id, old_code)
        self.call(services.unlink_account, self.chat_id)

        self.user.profile.refresh_from_db()
        self.assertIsNone(self.user.profile.telegram_id)
        self.assertNotEqual(self.user.profile.link_code, old_code)

    def test_categories_sorted_by_usage(self):
        """Ходовые категории идут первыми — по ним чаще всего и добавляют."""
        transport = self.user.categories.get(name='Транспорт')
        for _ in range(3):
            Transaction.objects.create(user=self.user, type=OperationType.EXPENSE,
                                       amount=Decimal('100.00'), category=transport)

        categories = self.call(services.categories_of_type, self.user, OperationType.EXPENSE)
        self.assertEqual(categories[0], transport)
        self.assertTrue(all(c.type == OperationType.EXPENSE for c in categories))

    def test_create_category_from_chat(self):
        category, error = self.call(services.create_category, self.user, '  Кофе  ', OperationType.EXPENSE)
        self.assertIsNone(error)
        self.assertEqual(category.name, 'Кофе')
        self.assertEqual(category.type, OperationType.EXPENSE)

    def test_duplicate_category_rejected_ignoring_case(self):
        category, error = self.call(services.create_category, self.user, 'еда', OperationType.EXPENSE)
        self.assertIsNone(category)
        self.assertIn('уже есть', error)

    def test_create_operation_takes_type_from_category(self):
        salary = self.user.categories.get(name='Зарплата')
        transaction = self.call(services.create_operation, self.user, salary, '95000.00', 'Аванс')
        self.assertEqual(transaction.type, OperationType.INCOME)
        self.assertEqual(self.user.transactions.count(), 1)


class BotKeyboardTests(TestCase):
    """Раскладка клавиатуры выбора категории."""

    def make(self, count, page=0):
        categories = [Category(pk=i, name=f'Категория {i}') for i in range(count)]
        return categories_keyboard(categories, page)

    def texts(self, keyboard):
        return [[button.text for button in row] for row in keyboard.inline_keyboard]

    def test_no_pagination_for_short_list(self):
        rows = self.texts(self.make(10))
        self.assertEqual(rows[-2:], [['+ Новая категория'], ['Отмена']])
        self.assertNotIn(['‹', '+ Новая категория', '›'], rows)

    def test_pagination_appears_for_long_list(self):
        rows = self.texts(self.make(14))
        self.assertIn(['‹', '+ Новая категория', '›'], rows)
        self.assertIn(['Страница 1 из 2'], rows)
        # Восемь категорий по две в ряд плюс навигация, счётчик и отмена
        self.assertEqual(len(rows), 4 + 3)

    def test_last_page_holds_remainder(self):
        rows = self.texts(self.make(14, page=1))
        self.assertIn(['Страница 2 из 2'], rows)
        self.assertEqual(sum(len(row) for row in rows[:3]), 6)

    def test_cancel_is_always_on_its_own_row(self):
        for count in (3, 10, 14):
            self.assertEqual(self.texts(self.make(count))[-1], ['Отмена'])


class ComparisonTests(TestCase):
    """Сравнение с предыдущим периодом такой же длины."""

    def setUp(self):
        self.user = User.objects.create_user('compare', password='pass')
        self.food = self.user.categories.get(name='Еда')
        self.today = timezone.localdate()

    def spend(self, amount, date):
        Transaction.objects.create(user=self.user, type=OperationType.EXPENSE,
                                   amount=Decimal(amount), category=self.food, date=date)

    def test_previous_month_is_calendar_month(self):
        month_start = self.today.replace(day=1)
        previous_start, previous_end = periods.previous_range(periods.MONTH, self.today)
        self.assertEqual(previous_end, month_start - timedelta(days=1))
        self.assertEqual(previous_start.day, 1)
        self.assertEqual(previous_start.month, previous_end.month)

    def test_previous_week_is_seven_days_back(self):
        start, end = periods.period_range(periods.WEEK, self.today)
        previous_start, previous_end = periods.previous_range(periods.WEEK, self.today)
        self.assertEqual(previous_start, start - timedelta(days=7))
        self.assertEqual(previous_end, start - timedelta(days=1))

    def test_previous_day_is_yesterday(self):
        previous_start, previous_end = periods.previous_range(periods.DAY, self.today)
        self.assertEqual(previous_start, self.today - timedelta(days=1))
        self.assertEqual(previous_end, self.today - timedelta(days=1))

    def test_month_comparison_uses_months(self):
        """Под месячным отчётом сравниваются месяцы, а не недели."""
        month_start = self.today.replace(day=1)
        self.spend('1000.00', month_start)
        self.spend('400.00', month_start - timedelta(days=1))

        text = reports.compare_periods(self.user, periods.MONTH)
        self.assertIn('Этот месяц против прошлого', text)
        # Разряды разделяются неразрывным пробелом
        self.assertIn('1\xa0000,00', text)
        self.assertIn('400,00', text)
        self.assertIn('выросли', text)

    def test_all_period_has_nothing_to_compare(self):
        self.assertIn('сравнивать не с чем', reports.compare_periods(self.user, periods.ALL))

    def test_button_label_matches_period(self):
        """Подпись кнопки говорит, с чем будет сравнение."""
        for period, expected in [(periods.DAY, 'Сравнить со вчера'),
                                 (periods.MONTH, 'Сравнить месяцы')]:
            buttons = [b.text for row in report_actions(period).inline_keyboard for b in row]
            self.assertIn(expected, buttons)

    def test_no_compare_button_for_all_period(self):
        buttons = [b.text for row in report_actions(periods.ALL).inline_keyboard for b in row]
        self.assertFalse([b for b in buttons if b.startswith('Сравнить')])


class WebComparisonTests(TestCase):
    """Сравнение периодов на странице аналитики."""

    def setUp(self):
        self.user = User.objects.create_user('web', password='pass')
        self.client.force_login(self.user)
        self.food = self.user.categories.get(name='Еда')
        self.salary = self.user.categories.get(name='Зарплата')
        self.today = timezone.localdate()
        self.month_start = self.today.replace(day=1)

    def add(self, category, amount, date):
        Transaction.objects.create(user=self.user, type=category.type,
                                   amount=Decimal(amount), category=category, date=date)

    def test_month_is_compared_with_previous_month(self):
        previous_day = self.month_start - timedelta(days=1)
        self.add(self.food, '1000.00', self.month_start)
        self.add(self.food, '500.00', previous_day)

        response = self.client.get(reverse('analytics'), {'period': 'month'})
        rows = {row['title']: row for row in response.context['comparison']}
        self.assertEqual(rows['Расходы']['current'], Decimal('1000.00'))
        self.assertEqual(rows['Расходы']['previous'], Decimal('500.00'))
        self.assertEqual(rows['Расходы']['difference'], Decimal('500.00'))
        self.assertAlmostEqual(rows['Расходы']['percent'], 100.0)
        # Рост расходов — плохая новость
        self.assertFalse(rows['Расходы']['good'])

    def test_income_growth_is_good(self):
        self.add(self.salary, '1000.00', self.month_start)
        self.add(self.salary, '500.00', self.month_start - timedelta(days=1))

        response = self.client.get(reverse('analytics'), {'period': 'month'})
        rows = {row['title']: row for row in response.context['comparison']}
        self.assertTrue(rows['Доходы']['good'])

    def test_no_comparison_for_all_time(self):
        response = self.client.get(reverse('analytics'), {'period': 'all'})
        self.assertIsNone(response.context['comparison'])

    def test_custom_period_compares_with_same_length(self):
        """Произвольный диапазон сравнивается с таким же по длине, идущим раньше."""
        self.add(self.food, '300.00', self.today - timedelta(days=2))
        self.add(self.food, '100.00', self.today - timedelta(days=7))

        response = self.client.get(reverse('analytics'), {
            'period': 'custom',
            'date_from': (self.today - timedelta(days=4)).isoformat(),
            'date_to': self.today.isoformat(),
        })
        rows = {row['title']: row for row in response.context['comparison']}
        self.assertEqual(rows['Расходы']['current'], Decimal('300.00'))
        self.assertEqual(rows['Расходы']['previous'], Decimal('100.00'))

    def test_percent_hidden_when_previous_is_not_positive(self):
        """От нулевой или отрицательной базы процент не считается."""
        self.add(self.food, '300.00', self.month_start)

        response = self.client.get(reverse('analytics'), {'period': 'month'})
        rows = {row['title']: row for row in response.context['comparison']}
        self.assertIsNone(rows['Расходы']['percent'])
        self.assertEqual(rows['Расходы']['difference'], Decimal('300.00'))

    def test_filters_apply_to_previous_period_too(self):
        """Фильтр по категории действует на обе части сравнения."""
        transport = self.user.categories.get(name='Транспорт')
        self.add(self.food, '900.00', self.month_start)
        self.add(transport, '100.00', self.month_start)
        self.add(transport, '400.00', self.month_start - timedelta(days=1))
        self.add(self.food, '700.00', self.month_start - timedelta(days=1))

        response = self.client.get(reverse('analytics'), {
            'period': 'month', 'category': transport.pk,
        })
        rows = {row['title']: row for row in response.context['comparison']}
        self.assertEqual(rows['Расходы']['current'], Decimal('100.00'))
        self.assertEqual(rows['Расходы']['previous'], Decimal('400.00'))


class OpenPeriodChartTests(TestCase):
    """Открытый произвольный период: границы берутся из данных."""

    def setUp(self):
        self.user = User.objects.create_user('charts', password='pass')
        self.client.force_login(self.user)
        self.food = self.user.categories.get(name='Еда')
        self.today = timezone.localdate()

    def spend(self, amount, days_ago):
        Transaction.objects.create(user=self.user, type=OperationType.EXPENSE,
                                   amount=Decimal(amount), category=self.food,
                                   date=self.today - timedelta(days=days_ago))

    def test_open_ended_period_is_drawn_by_days(self):
        """Раньше незаданный конец считался «длинным» периодом и график схлопывался."""
        for days in (0, 3, 10):
            self.spend('100.00', days)

        response = self.client.get(reverse('analytics'), {
            'period': 'custom',
            'date_from': (self.today - timedelta(days=10)).isoformat(),
            'date_to': '',
        })
        chart = response.context['timeline_chart']
        self.assertIsNotNone(chart)
        self.assertNotIn('"dtick":"M1"', chart)

    def test_long_period_is_drawn_by_months(self):
        self.spend('100.00', 0)
        self.spend('100.00', 200)

        response = self.client.get(reverse('analytics'), {'period': 'all'})
        self.assertIn('"dtick":"M1"', response.context['timeline_chart'])

    def test_all_time_has_no_comparison(self):
        self.spend('100.00', 0)
        response = self.client.get(reverse('analytics'), {'period': 'all'})
        self.assertIsNone(response.context['comparison'])

    def test_open_ended_period_is_compared(self):
        """У открытого диапазона длина берётся по данным — сравнение возможно.

        Диапазон получается [today-5 … today-1], то есть пять дней;
        предыдущий такой же — [today-10 … today-6].
        """
        self.spend('300.00', 1)
        self.spend('100.00', 8)

        response = self.client.get(reverse('analytics'), {
            'period': 'custom',
            'date_from': (self.today - timedelta(days=5)).isoformat(),
            'date_to': '',
        })
        rows = {row['title']: row for row in response.context['comparison']}
        self.assertEqual(rows['Расходы']['current'], Decimal('300.00'))
        self.assertEqual(rows['Расходы']['previous'], Decimal('100.00'))
