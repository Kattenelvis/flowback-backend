from django.db import models
from django.utils import timezone

from flowback.common.models import BaseModel
from flowback.user.models import User


class Account(BaseModel):
    account_number = models.CharField(max_length=20)
    account_name = models.CharField(max_length=100)
    user = models.ForeignKey(User, on_delete=models.CASCADE)

    def balance(self):
        debit_total = self.transactions.filter(debit_amount__isnull=False).aggregate(models.Sum('debit_amount')).get('debit_amount__sum', 0)
        credit_total = self.transactions.filter(credit_amount__isnull=False).aggregate(models.Sum('credit_amount')).get('credit_amount__sum', 0)

        return (debit_total or 0) - (credit_total or 0)

    def __str__(self):
        return self.account_name


class Transaction(BaseModel):
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='transactions')
    debit_amount = models.DecimalField(max_digits=15, decimal_places=5, null=True, blank=True)
    credit_amount = models.DecimalField(max_digits=15, decimal_places=5, null=True, blank=True)
    description = models.CharField(max_length=100)
    verification_number = models.CharField(max_length=20)
    date = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return self.description