from django.db.models.signals import post_save
from django.dispatch import receiver

from flowback.poll.models import PollProposalKPI, PollProposal


# Generate KPIs for new proposals
@receiver(post_save, sender=PollProposal)
def pollproposal_post_save(instance, created, *args, **kwargs):
    if created and instance.poll.version == 2:
        PollProposalKPI.generate_kpis(proposal_id=instance.id)