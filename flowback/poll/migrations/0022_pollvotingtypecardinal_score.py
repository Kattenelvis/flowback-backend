# Generated by Django 4.2.7 on 2023-12-25 15:21

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('poll', '0021_rename_score_pollvotingtypecardinal_raw_score'),
    ]

    operations = [
        migrations.AddField(
            model_name='pollvotingtypecardinal',
            name='score',
            field=models.IntegerField(blank=True, null=True),
        ),
    ]
