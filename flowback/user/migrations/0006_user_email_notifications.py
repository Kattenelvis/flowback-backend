# Generated by Django 4.0.8 on 2023-04-22 15:03

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('user', '0005_user_kanban_refill'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='email_notifications',
            field=models.BooleanField(default=False),
        ),
    ]
