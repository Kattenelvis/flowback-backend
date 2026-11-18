from django.db import migrations
from django.utils import timezone


def archive_polls_without_proposals(apps, schema_editor):
    Poll = apps.get_model('poll', 'Poll')
    PollProposal = apps.get_model('poll', 'PollProposal')

    polls_with_proposals = PollProposal.objects.filter(active=True).values('poll_id')

    Poll.objects.filter(dynamic=False,
                        proposal_end_date__lte=timezone.now()).exclude(id__in=polls_with_proposals).update(is_archived=True)


class Migration(migrations.Migration):

    dependencies = [
        ('poll', '0057_is_archived'),
    ]

    operations = [
        migrations.RunPython(archive_polls_without_proposals, migrations.RunPython.noop),
    ]
