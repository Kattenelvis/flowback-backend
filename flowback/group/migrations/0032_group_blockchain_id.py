# Generated by Django 4.2.7 on 2024-06-13 15:01

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('group', '0031_groupuserdelegatepool_blockchain_id'),
    ]

    operations = [
        migrations.AddField(
            model_name='group',
            name='blockchain_id',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
    ]
