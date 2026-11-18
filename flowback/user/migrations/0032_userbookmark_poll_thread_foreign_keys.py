from django.db import migrations, models
import django.db.models.deletion
from django.db.models import F, Q


def copy_generic_bookmarks_to_foreign_keys(apps, schema_editor):
    UserBookmark = apps.get_model('user', 'UserBookmark')
    Poll = apps.get_model('poll', 'Poll')
    GroupThread = apps.get_model('group', 'GroupThread')

    for model_name, target, field in (('poll', Poll, 'poll_id'), ('groupthread', GroupThread, 'thread_id')):
        UserBookmark.objects.filter(content_type__model=model_name,
                                    object_id__in=target.objects.values('id')).update(**{field: F('object_id')})

    # Bookmarks pointing at deleted objects (or unsupported models) can't be represented anymore
    UserBookmark.objects.filter(poll__isnull=True, thread__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('group', '0063_groupuser_permission_blank'),
        ('poll', '0056_alter_pollvotingtyperanking_unique_together_and_more'),
        ('user', '0031_username_no_invisible_characters'),
    ]

    operations = [
        migrations.AddField(
            model_name='userbookmark',
            name='poll',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='poll.poll'),
        ),
        migrations.AddField(
            model_name='userbookmark',
            name='thread',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='group.groupthread'),
        ),
        migrations.RunPython(copy_generic_bookmarks_to_foreign_keys),
        migrations.RemoveConstraint(
            model_name='userbookmark',
            name='unique_bookmark',
        ),
        migrations.RemoveField(
            model_name='userbookmark',
            name='content_type',
        ),
        migrations.RemoveField(
            model_name='userbookmark',
            name='object_id',
        ),
        migrations.AddConstraint(
            model_name='userbookmark',
            constraint=models.CheckConstraint(check=Q(('poll__isnull', False), ('thread__isnull', True)) | Q(('poll__isnull', True), ('thread__isnull', False)), name='bookmark_exactly_one_target'),
        ),
        migrations.AddConstraint(
            model_name='userbookmark',
            constraint=models.UniqueConstraint(condition=Q(('poll__isnull', False)), fields=('user', 'poll'), name='unique_poll_bookmark'),
        ),
        migrations.AddConstraint(
            model_name='userbookmark',
            constraint=models.UniqueConstraint(condition=Q(('thread__isnull', False)), fields=('user', 'thread'), name='unique_thread_bookmark'),
        ),
    ]
