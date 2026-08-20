from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

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
