# Generated by Django 4.0.3 on 2022-09-16 20:11

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('group', '0002_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='group',
            name='cover_image',
            field=models.ImageField(upload_to='group/cover_image'),
        ),
        migrations.AlterField(
            model_name='group',
            name='image',
            field=models.ImageField(upload_to='group/image'),
        ),
    ]
