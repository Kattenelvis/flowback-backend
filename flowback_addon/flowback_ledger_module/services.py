from django.utils import timezone

from flowback.common.services import model_update, get_object
from .models import Account, Transaction
from flowback.user.models import User


def account_create(*, user_id: int, account_number: str, account_name: str) -> Account:
    user = get_object(User, id=user_id)
    account = Account(account_number=account_number,
                      account_name=account_name,
                      user=user)

    account.full_clean()
    account.save()

    return account


def account_update(user_id: int, account_id: int, data) -> Account:
    user = get_object(User, id=user_id)
    account = get_object(Account, id=account_id, user=user)

    non_side_effect_fields = ['account_number', 'account_name', 'updated_at']
    account, has_updated = model_update(instance=account,
                                        fields=non_side_effect_fields,
                                        data=data)
    return account


def account_delete(user_id: int, account_id: int):
    user = get_object(User, id=user_id)
    account = get_object(Account, id=account_id, user=user)
    account.delete()


def transaction_create(*,
                       user_id: int,
                       account_id: int,
                       description: str,
                       verification_number: str,
                       debit_amount: float = None,
                       credit_amount: float = None,
                       date=None) -> Transaction:
    user = get_object(User, id=user_id)
    account = get_object(Account, id=account_id, user=user)

    transaction = Transaction(
        account=account,
        debit_amount=debit_amount or 0,
        credit_amount=credit_amount or 0,
        description=description,
        verification_number=verification_number,
        date=date or timezone.now()
    )

    transaction.full_clean()
    transaction.save()

    return transaction


def transaction_update(user_id: int, account_id: int, transaction_id: int, data) -> Transaction:
    user = get_object(User, id=user_id)
    transaction = get_object(Transaction, id=transaction_id, account_id=account_id, account__user=user)

    # A transaction is either a debit or a credit, so the side that isn't sent is cleared
    data['debit_amount'] = data.get('debit_amount') or 0
    data['credit_amount'] = data.get('credit_amount') or 0

    new_account_id = data.pop('new_account_id', None)
    if new_account_id is not None and new_account_id != transaction.account_id:
        transaction.account = get_object(Account, id=new_account_id, user=user)
        transaction.save(update_fields=['account', 'updated_at'])

    non_side_effect_fields = [
        'debit_amount', 'credit_amount', 'description', 'verification_number', 'date', 'updated_at']
    transaction, has_updated = model_update(instance=transaction,
                                            fields=non_side_effect_fields,
                                            data=data)
    return transaction


def transaction_delete(user_id: int, account_id: int, transaction_id: int):
    user = get_object(User, id=user_id)
    transaction = get_object(Transaction, id=transaction_id, account_id=account_id, account__user=user)

    transaction.delete()
