from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0012_chat_rewrite_data'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='messagechannelparticipant',
            name='active',
        ),
        migrations.RemoveField(
            model_name='messagechannelparticipant',
            name='closed_at',
        ),
        migrations.RemoveField(
            model_name='messagechannelparticipant',
            name='timestamp',
        ),
    ]
