# Generated by Django 4.0.3 on 2022-09-16 20:11

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('user', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='banner_image',
            field=models.ImageField(blank=True, null=True, upload_to='user/banner_image'),
        ),
        migrations.AlterField(
            model_name='user',
            name='profile_image',
            field=models.ImageField(blank=True, null=True, upload_to='user/profile_image'),
        ),
    ]
