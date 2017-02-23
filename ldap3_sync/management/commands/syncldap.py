from django.core.management.base import BaseCommand, CommandError
from ldap3_sync.utils import CLISyncRunner
from ldap3_sync.models import LDAPSyncJob


class Command(BaseCommand):
    help = "Run a preconfigured LDAPSyncJob."

    def add_arguments(self, parser):
        parser.add_argument('job_name', type=str)

    def handle(self, *args, **options):
        try:
            sync_job = LDAPSyncJob.objects.get(name=options['job_name'])
        except LDAPSyncJob.DoesNotExist:
            raise CommandError('LDAPSyncJob with name {} does not exist.'.format(options['job_name']))
        runner = CLISyncRunner(sync_job)
        runner.run()
