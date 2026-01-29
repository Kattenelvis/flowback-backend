from django.apps import AppConfig
from django.core.signals import request_finished


class PollConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'flowback.poll'

    def ready(self):
        from . import signals

        request_finished.connect(signals.pollproposal_post_save)
