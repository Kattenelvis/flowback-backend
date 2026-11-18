from django.db import migrations, models

import flowback.schedule.recurrence


class Migration(migrations.Migration):

    dependencies = [
        ('schedule', '0023_scheduleevent_repeat_frequency_end_date_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='scheduleevent',
            name='timezone',
            field=models.CharField(default='UTC', max_length=64, validators=[flowback.schedule.recurrence.validate_timezone_name]),
        ),
    ]
