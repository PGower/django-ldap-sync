from __future__ import absolute_import, unicode_literals
from celery import shared_task, Task
from .models import LDAPSyncJob
from .utils import BackgroundSyncRunner


@shared_task
def syncldap(sync_job_name):
    """Retrieve the given sync_job by name and attempt to run it."""
    try:
        sync_job = LDAPSyncJob.objects.get(name=sync_job_name)
    except LDAPSyncJob.DoesNotExist as e:
        return f'FAILED: {e}'
    runner = BackgroundSyncRunner(sync_job)
    runner.run()
    return 'RUN'

