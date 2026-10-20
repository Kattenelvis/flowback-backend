import datetime
import json
import os
import subprocess
import sys
from decimal import Decimal


from django.conf import settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status
from django.test import TestCase
from .models import Account, Transaction

from flowback.user.models import User

LEDGER_MODULE = 'flowback_addon.flowback_ledger_module'


class AccountListAPITestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email='test@user.com', username='testuser', password='testpass')
        self.client.force_authenticate(user=self.user)

    def test_account_list_api(self):
        url = reverse('api:addon:ledger:ledger_list') + '?id=1'
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_account_list_api_ignores_unknown_param(self):
        url = reverse('api:addon:ledger:ledger_list') + '?invalid_param=1'
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_account_list_api_empty(self):
        url = reverse('api:addon:ledger:ledger_list')
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 0)

    def test_account_list_api_invalid_query_param(self):
        url = reverse('api:addon:ledger:ledger_list') + '?id=abc'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_account_list_api_invalid_orderby_param(self):
        url = reverse('api:addon:ledger:ledger_list') + '?id=invalid_param'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class AccountCreateAPITestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email='test@user.com', username='testuser', password='testpass')
        self.client.force_authenticate(user=self.user)

    def test_account_create_api(self):
        url = reverse('api:addon:ledger:ledger_create')
        data = {'account_number': '123456789', 'account_name': 'Test Account'}
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Account.objects.count(), 1)
        account = Account.objects.first()
        self.assertEqual(account.account_number, data['account_number'])
        self.assertEqual(account.account_name, data['account_name'])

    def test_account_create_api_with_error(self):
        url = reverse('api:addon:ledger:ledger_create')
        data = {'account_number': '123456789'}
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Account.objects.count(), 0)


class AccountUpdateApiTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email='test@user.com', username='testuser', password='testpass')
        self.client.force_authenticate(user=self.user)
        self.account = Account.objects.create(
            account_number='123456789', account_name='Test Account', user=self.user)

    def test_account_update_api(self):
        url = reverse('api:addon:ledger:ledger_update',
                      args=[self.account.id])
        payload = {'account_number': '987654321',
                   'account_name': 'Updated Account'}
        response = self.client.post(url, payload)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Account.objects.get(
            id=self.account.id).account_name, payload['account_name'])
        self.assertEqual(Account.objects.get(
            id=self.account.id).account_number, payload['account_number'])

    def test_account_update_api_missing_fields(self):
        url = reverse('api:addon:ledger:ledger_update',
                      args=[self.account.id])
        payload = {'account_number': '123456789'}
        response = self.client.post(url, payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Account.objects.get(
            id=self.account.id).account_name, 'Test Account')

    def test_account_update_api_invalid_id(self):
        url = reverse('api:addon:ledger:ledger_update', args=[999])
        payload = {'account_number': '987654321',
                   'account_name': 'Updated Account'}
        response = self.client.post(url, payload)
        response_json = json.loads(response.content.decode('utf-8'))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response_json['detail'][0], 'account does not exist')

    def test_account_update_api_empty_payload(self):
        url = reverse('api:addon:ledger:ledger_update',
                      args=[self.account.id])
        payload = {}
        response = self.client.post(url, payload)
        response_json = json.loads(response.content.decode('utf-8'))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Account.objects.get(
            id=self.account.id).account_name, 'Test Account')
        self.assertEqual(
            response_json['detail']['account_number'][0], 'This field is required.')
        self.assertEqual(
            response_json['detail']['account_name'][0], 'This field is required.')

    def test_account_update_api_with_other_user(self):
        other_user = User.objects.create_user(
            email='test2@user.com', username='testuser2', password='testpass')
        self.client.force_authenticate(user=other_user)
        url = reverse('api:addon:ledger:ledger_update',
                      args=[self.account.id])
        payload = {'account_number': '987654321',
                   'account_name': 'Updated Account'}
        response = self.client.post(url, payload)
        response_json = json.loads(response.content.decode('utf-8'))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response_json['detail'][0], 'account does not exist')


class AccountDeleteAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email='test@user.com', username='testuser', password='testpass')
        self.account = Account.objects.create(
            account_number='123456789', account_name='Test Account', user=self.user)
        self.client.force_authenticate(user=self.user)

    def test_account_delete_api(self):
        url = reverse('api:addon:ledger:ledger_delete',
                      args=[self.account.id])
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(Account.objects.filter(id=self.account.id).exists())

    def test_account_delete_api_invalid_id(self):
        url = reverse('api:addon:ledger:ledger_delete', args=[999])
        response = self.client.post(url)
        response_json = json.loads(response.content.decode('utf-8'))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response_json['detail'][0], 'account does not exist')

    def test_account_delete_api_with_other_user(self):
        other_user = User.objects.create_user(
            email='test2@user.com', username='testuser2', password='testpass')
        self.client.force_authenticate(user=other_user)
        url = reverse('api:addon:ledger:ledger_delete',
                      args=[self.account.id])
        response = self.client.post(url)
        response_json = json.loads(response.content.decode('utf-8'))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response_json['detail'][0], 'account does not exist')


class TransactionListAPITest(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email='test@user.com', username='testuser', password='testpass')
        self.account = Account.objects.create(
            account_number='123456789', account_name='Test Account', user=self.user)
        self.client.force_authenticate(user=self.user)

    def test_transaction_list_api(self):
        url = reverse('api:addon:ledger:ledger_transactions_list') + '?id=1'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_transaction_list_api_ignores_unknown_param(self):
        url = reverse('api:addon:ledger:ledger_transactions_list') + '?invalid_param=1'
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_transaction_list_api_empty(self):
        url = reverse('api:addon:ledger:ledger_transactions_list')
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 0)

    def test_transaction_list_api_invalid_query_param(self):
        url = reverse('api:addon:ledger:ledger_transactions_list') + '?id=abc'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_transaction_list_api_invalid_orderby_param(self):
        url = reverse('api:addon:ledger:ledger_transactions_list') + '?id=invalid_param'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class TransactionCreateAPITestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email='test@user.com', username='testuser', password='testpass')
        self.account = Account.objects.create(
            account_number='123456789', account_name='Test Account', user=self.user)
        self.client.force_authenticate(user=self.user)

    def test_transaction_create_api(self):
        url = reverse('api:addon:ledger:ledger_transactions_create',
                      args=[self.account.id])
        data = {
            'description': 'Test transaction',
            'verification_number': '123',
            'credit_amount': 20,
            'date': datetime.datetime.now()
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Transaction.objects.count(), 1)
        transaction = Transaction.objects.first()
        self.assertEqual(transaction.description, data['description'])
        self.assertEqual(transaction.verification_number,
                         data['verification_number'])
        self.assertEqual(transaction.credit_amount, data['credit_amount'])

    def test_transaction_create_api_with_error(self):
        url = reverse('api:addon:ledger:ledger_transactions_create',
                      args=[self.account.id])
        data = {
            'description': 'Test transaction',
            'verification_number': '123',
            'credit_amount': 20,
            'debit_amount': 20,
            'date': datetime.datetime.now()
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Transaction.objects.count(), 0)


class TransactionUpdateApiTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email='test@user.com', username='testuser', password='testpass')
        self.client.force_authenticate(user=self.user)
        self.account = Account.objects.create(
            account_number='123456789', account_name='Test Account', user=self.user)
        self.transaction = Transaction.objects.create(
            description='Test transaction',
            verification_number='123',
            credit_amount=20,
            debit_amount=0,
            date=datetime.datetime.now(datetime.timezone.utc),
            account=self.account)

    def test_transaction_update_api(self):
        url = reverse('api:addon:ledger:ledger_transactions_update',
                      args=[self.account.id, self.transaction.id])
        payload = {
            'description': 'Update transaction',
            'verification_number': '123',
            'debit_amount': 5,
            'date': datetime.datetime.now(datetime.timezone.utc)
        }
        response = self.client.post(url, payload)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Transaction.objects.get(
            id=self.transaction.id, account_id=self.account.id).description, payload['description'])
        self.assertEqual(Transaction.objects.get(
            id=self.transaction.id).verification_number, payload['verification_number'])
        self.assertEqual(Transaction.objects.get(
            id=self.transaction.id).debit_amount, payload['debit_amount'])
        self.assertEqual(Transaction.objects.get(
            id=self.transaction.id).credit_amount, 0)

    def test_transaction_update_api_missing_fields(self):
        url = reverse('api:addon:ledger:ledger_transactions_update',
                      args=[self.account.id, self.transaction.id])
        payload = {'description': 'Update transaction',
            'verification_number': '123',}
        response = self.client.post(url, payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Transaction.objects.get(
            id=self.transaction.id).description, 'Test transaction')

    def test_transaction_update_api_invalid_id(self):
        url = reverse('api:addon:ledger:ledger_transactions_update', args=[self.account.id, 999])
        payload = {
            'description': 'Update transaction',
            'verification_number': '123',
            'debit_amount': 5,
            'date': datetime.datetime.now(datetime.timezone.utc)
        }
        response = self.client.post(url, payload)
        response_json = json.loads(response.content.decode('utf-8'))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response_json['detail'][0], 'transaction does not exist')

    def test_transaction_update_api_empty_payload(self):
        url = reverse('api:addon:ledger:ledger_transactions_update',
                      args=[self.account.id, self.transaction.id])
        payload = {}
        response = self.client.post(url, payload)
        response_json = json.loads(response.content.decode('utf-8'))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Account.objects.get(
            id=self.account.id).account_name, 'Test Account')
        self.assertEqual(
            response_json['detail']['description'][0], 'This field is required.')
        self.assertEqual(
            response_json['detail']['verification_number'][0], 'This field is required.')

    def test_transaction_update_api_with_other_user(self):
        other_user = User.objects.create_user(
            email='test2@user.com', username='testuser2', password='testpass')
        self.client.force_authenticate(user=other_user)
        url = reverse('api:addon:ledger:ledger_transactions_update',
                      args=[self.account.id, self.transaction.id])
        payload = {
            'description': 'Update transaction',
            'verification_number': '123',
            'debit_amount': 5,
            'date': datetime.datetime.now(datetime.timezone.utc)
        }
        response = self.client.post(url, payload)
        response_json = json.loads(response.content.decode('utf-8'))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response_json['detail'][0], 'transaction does not exist')
        
    def test_transaction_update_api_with_debit_and_credit_amount(self):
        url = reverse('api:addon:ledger:ledger_transactions_update',
                      args=[self.account.id, self.transaction.id])
        data = {
            'description': 'Update transaction',
            'verification_number': '123',
            'credit_amount': 20,
            'debit_amount': 20,
            'date': datetime.datetime.now()
        }
        response = self.client.post(url, data)
        response_json = json.loads(response.content.decode('utf-8'))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response_json['detail']['non_field_errors'][0], 'Each transaction must have either a debit or a credit amount, but not both')

class TransactionDeleteAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email='test@user.com', username='testuser', password='testpass')
        self.client.force_authenticate(user=self.user)
        self.account = Account.objects.create(
            account_number='123456789', account_name='Test Account', user=self.user)
        self.transaction = Transaction.objects.create(
            description='Test transaction',
            verification_number='123',
            credit_amount=20,
            debit_amount=0,
            date=datetime.datetime.now(datetime.timezone.utc),
            account=self.account)

    def test_transaction_delete_api(self):
        url = reverse('api:addon:ledger:ledger_transactions_delete',
                      args=[self.account.id, self.transaction.id])
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(Transaction.objects.filter(id=self.transaction.id).exists())

    def test_transaction_delete_api_invalid_id(self):
        self.client.force_login(self.user)
        url = reverse('api:addon:ledger:ledger_transactions_delete', args=[self.account.id, 999])
        response = self.client.post(url)
        response_json = json.loads(response.content.decode('utf-8'))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response_json['detail'][0], 'transaction does not exist')

    def test_transaction_delete_api_with_other_user(self):
        other_user = User.objects.create_user(
            email='test2@user.com', username='testuser2', password='testpass')
        self.client.force_authenticate(user=other_user)
        url = reverse('api:addon:ledger:ledger_transactions_delete',
                      args=[self.account.id, self.transaction.id])
        response = self.client.post(url)
        response_json = json.loads(response.content.decode('utf-8'))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response_json['detail'][0], 'transaction does not exist')


def make_user(name='testuser'):
    return User.objects.create_user(email=f'{name}@user.com', username=name, password='testpass')


def make_transaction(account, debit=None, credit=None, description='Test transaction', date=None):
    return Transaction.objects.create(account=account,
                                      debit_amount=debit,
                                      credit_amount=credit,
                                      description=description,
                                      verification_number='1',
                                      date=date or datetime.datetime.now(datetime.timezone.utc))


class TransactionListScopeAndFilterTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = make_user()
        self.other_user = make_user('otheruser')
        self.client.force_authenticate(user=self.user)

        self.account = Account.objects.create(account_number='1', account_name='Cash', user=self.user)
        self.account_2 = Account.objects.create(account_number='2', account_name='Bank', user=self.user)
        self.other_account = Account.objects.create(account_number='3', account_name='Other', user=self.other_user)
        self.url = reverse('api:addon:ledger:ledger_transactions_list')

    def ids(self, query=''):
        response = self.client.get(self.url + query)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return [transaction['id'] for transaction in response.data['results']]

    def test_only_own_transactions_are_listed(self):
        own = make_transaction(self.account, debit=10)
        make_transaction(self.other_account, debit=99)

        self.assertEqual(self.ids(), [own.id])

    def test_other_users_account_id_gives_no_transactions(self):
        make_transaction(self.other_account, debit=99)

        self.assertEqual(self.ids(f'?account_ids={self.other_account.id}'), [])

    def test_filter_by_single_and_multiple_accounts(self):
        t1 = make_transaction(self.account, debit=1)
        t2 = make_transaction(self.account_2, credit=2)

        self.assertEqual(self.ids(f'?account_ids={self.account.id}'), [t1.id])
        self.assertCountEqual(self.ids(f'?account_ids={self.account.id}&account_ids={self.account_2.id}'), [t1.id, t2.id])

    def test_filter_by_description_is_case_insensitive(self):
        match = make_transaction(self.account, debit=1, description='Office Rent')
        make_transaction(self.account, debit=1, description='Salary')

        self.assertEqual(self.ids('?description=rent'), [match.id])

    def test_filter_by_dates_is_inclusive(self):
        utc = datetime.timezone.utc
        early = make_transaction(self.account, debit=1, date=datetime.datetime(2024, 1, 1, 23, 30, tzinfo=utc))
        middle = make_transaction(self.account, debit=1, date=datetime.datetime(2024, 1, 15, 12, 0, tzinfo=utc))
        late = make_transaction(self.account, debit=1, date=datetime.datetime(2024, 2, 1, 0, 30, tzinfo=utc))

        self.assertCountEqual(self.ids('?date_after=2024-01-01'), [early.id, middle.id, late.id])
        self.assertCountEqual(self.ids('?date_after=2024-01-02&date_before=2024-01-31'), [middle.id])
        self.assertCountEqual(self.ids('?date_before=2024-01-01'), [early.id])
        self.assertCountEqual(self.ids('?date_after=2024-02-01'), [late.id])

    def test_invalid_filters_are_rejected(self):
        for query in ['?date_after=notadate', '?account_ids=abc', '?date_before=2024-13-45']:
            response = self.client.get(self.url + query)
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, query)

    def test_newest_transactions_first_and_paginated(self):
        for day in range(1, 4):
            make_transaction(self.account, debit=day, date=datetime.datetime(2024, 1, day, 12, tzinfo=datetime.timezone.utc))

        response = self.client.get(self.url + '?limit=2')
        self.assertEqual(response.data['count'], 3)
        self.assertEqual(len(response.data['results']), 2)
        self.assertEqual([t['debit_amount'] for t in response.data['results']], [3, 2])
        self.assertIsNotNone(response.data['next'])

    def test_output_includes_account_and_owner(self):
        make_transaction(self.account, debit=10)

        result = self.client.get(self.url).data['results'][0]
        self.assertEqual(result['account']['account_name'], 'Cash')
        self.assertEqual(result['account']['created_by']['id'], self.user.id)
        self.assertEqual(result['debit_amount'], 10)
        self.assertEqual(result['credit_amount'], None)


class AccountListScopeTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = make_user()
        self.client.force_authenticate(user=self.user)
        self.url = reverse('api:addon:ledger:ledger_list')

    def test_only_own_accounts_with_balance(self):
        account = Account.objects.create(account_number='1', account_name='Cash', user=self.user)
        Account.objects.create(account_number='2', account_name='Other', user=make_user('otheruser'))
        make_transaction(account, debit=100)
        make_transaction(account, credit=30)

        response = self.client.get(self.url)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['account_name'], 'Cash')
        self.assertEqual(response.data['results'][0]['balance'], 70)

    def test_filter_by_id(self):
        first = Account.objects.create(account_number='1', account_name='Cash', user=self.user)
        Account.objects.create(account_number='2', account_name='Bank', user=self.user)

        response = self.client.get(self.url + f'?id={first.id}')
        self.assertEqual([account['id'] for account in response.data['results']], [first.id])

    def test_unauthenticated_is_rejected(self):
        response = APIClient().get(self.url)
        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))


class TransactionWriteBehaviourTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = make_user()
        self.client.force_authenticate(user=self.user)
        self.account = Account.objects.create(account_number='1', account_name='Cash', user=self.user)
        self.account_2 = Account.objects.create(account_number='2', account_name='Bank', user=self.user)

    def update_url(self, transaction, account=None):
        return reverse('api:addon:ledger:ledger_transactions_update',
                       args=[(account or self.account).id, transaction.id])

    def payload(self, **kwargs):
        return {'description': 'Edited', 'verification_number': '5',
                'date': datetime.datetime.now(datetime.timezone.utc).isoformat(), **kwargs}

    def test_create_returns_transaction_id_and_stores_both_sides(self):
        url = reverse('api:addon:ledger:ledger_transactions_create', args=[self.account.id])
        response = self.client.post(url, self.payload(debit_amount=12.5, credit_amount=0), format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        transaction = Transaction.objects.get(id=response.data)
        self.assertEqual(transaction.debit_amount, Decimal('12.5'))
        self.assertEqual(transaction.credit_amount, 0)

    def test_create_without_date_defaults_to_now(self):
        url = reverse('api:addon:ledger:ledger_transactions_create', args=[self.account.id])
        data = self.payload(credit_amount=3)
        del data['date']
        response = self.client.post(url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertLess(abs(timezone.now() - Transaction.objects.get().date), datetime.timedelta(minutes=1))

    def test_create_rejects_zero_negative_and_null_amounts(self):
        url = reverse('api:addon:ledger:ledger_transactions_create', args=[self.account.id])
        for amounts in [{'debit_amount': 0, 'credit_amount': 0},
                        {'debit_amount': -5, 'credit_amount': 0},
                        {'debit_amount': 0, 'credit_amount': -5},
                        {'debit_amount': None, 'credit_amount': None},
                        {}]:
            response = self.client.post(url, self.payload(**amounts), format='json')
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, amounts)

        self.assertEqual(Transaction.objects.count(), 0)

    def test_create_with_null_other_side_is_accepted(self):
        url = reverse('api:addon:ledger:ledger_transactions_create', args=[self.account.id])
        response = self.client.post(url, self.payload(debit_amount=None, credit_amount=4), format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_create_in_other_users_account_is_rejected(self):
        other_account = Account.objects.create(account_number='9', account_name='Other', user=make_user('otheruser'))
        url = reverse('api:addon:ledger:ledger_transactions_create', args=[other_account.id])
        response = self.client.post(url, self.payload(debit_amount=1), format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Transaction.objects.count(), 0)

    def test_update_credit_transaction_keeps_credit_amount(self):
        transaction = make_transaction(self.account, debit=0, credit=20)
        response = self.client.post(self.update_url(transaction),
                                    self.payload(debit_amount=0, credit_amount=35), format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        transaction.refresh_from_db()
        self.assertEqual(transaction.credit_amount, 35)
        self.assertEqual(transaction.debit_amount, 0)

    def test_update_switches_debit_to_credit(self):
        transaction = make_transaction(self.account, debit=20, credit=0)
        response = self.client.post(self.update_url(transaction),
                                    self.payload(debit_amount=0, credit_amount=7), format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        transaction.refresh_from_db()
        self.assertEqual((transaction.debit_amount, transaction.credit_amount), (0, 7))

    def test_update_can_move_transaction_to_another_account(self):
        transaction = make_transaction(self.account, debit=20, credit=0)
        response = self.client.post(self.update_url(transaction),
                                    self.payload(debit_amount=20, new_account_id=self.account_2.id), format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        transaction.refresh_from_db()
        self.assertEqual(transaction.account_id, self.account_2.id)
        self.assertEqual(transaction.description, 'Edited')

    def test_update_cannot_move_transaction_to_other_users_account(self):
        other_account = Account.objects.create(account_number='9', account_name='Other', user=make_user('otheruser'))
        transaction = make_transaction(self.account, debit=20, credit=0)
        response = self.client.post(self.update_url(transaction),
                                    self.payload(debit_amount=20, new_account_id=other_account.id), format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        transaction.refresh_from_db()
        self.assertEqual(transaction.account_id, self.account.id)

    def test_update_and_delete_require_matching_account_in_url(self):
        transaction = make_transaction(self.account, debit=20, credit=0)

        response = self.client.post(self.update_url(transaction, account=self.account_2),
                                    self.payload(debit_amount=1), format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        url = reverse('api:addon:ledger:ledger_transactions_delete', args=[self.account_2.id, transaction.id])
        self.assertEqual(self.client.post(url).status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(Transaction.objects.filter(id=transaction.id).exists())

    def test_deleting_account_deletes_its_transactions(self):
        make_transaction(self.account, debit=20)
        url = reverse('api:addon:ledger:ledger_delete', args=[self.account.id])

        self.assertEqual(self.client.post(url).status_code, status.HTTP_200_OK)
        self.assertEqual(Transaction.objects.count(), 0)


class LedgerModuleSettingTest(TestCase):
    """FLOWBACK_LEDGER_MODULE is the switch that turns the addon on or off"""

    def integrations(self, **env):
        base_env = {key: value for key, value in os.environ.items()
                    if key not in ('FLOWBACK_LEDGER_MODULE', 'INTEGRATIONS')}
        output = subprocess.run(
            [sys.executable, '-c', 'import backend.settings as s; print(s.INTEGRATIONS); print(s.INSTALLED_APPS)'],
            cwd=settings.BASE_DIR, env={**base_env, **env}, capture_output=True, text=True, check=True).stdout

        return output.splitlines()

    def test_module_is_off_by_default(self):
        integrations, installed_apps = self.integrations()
        self.assertEqual(integrations, '[]')
        self.assertNotIn(LEDGER_MODULE, installed_apps)

    def test_module_is_enabled_by_flag(self):
        integrations, installed_apps = self.integrations(FLOWBACK_LEDGER_MODULE='True')
        self.assertEqual(integrations, str([LEDGER_MODULE]))
        self.assertIn(LEDGER_MODULE, installed_apps)

    def test_flag_false_keeps_module_off(self):
        integrations, _ = self.integrations(FLOWBACK_LEDGER_MODULE='False')
        self.assertEqual(integrations, '[]')

    def test_module_is_not_added_twice(self):
        integrations, installed_apps = self.integrations(FLOWBACK_LEDGER_MODULE='True', INTEGRATIONS=LEDGER_MODULE)
        self.assertEqual(integrations, str([LEDGER_MODULE]))
        self.assertEqual(installed_apps.count(LEDGER_MODULE), 1)

    def test_module_is_mounted_when_enabled(self):
        self.assertTrue(reverse('api:addon:ledger:ledger_list').endswith('/ledger/account/list'))
