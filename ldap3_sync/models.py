from django.db import models
# from django.conf import settings
# from django.contrib.auth.models import Group

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType

import ldap3

import petname

from django.utils.module_loading import import_string

# Store LDAP info about the created groups so that we can easily
# identify them in subsequent syncs

HELP_TEXT = ('DO NOT edit this unless you really know '
             'what your doing. It is much safer to delete '
             'this entire record and let the sync command '
             'recreate it.')


class LDAPConnection(models.Model):
    """Equivalent to an ldap3.Connection."""

    user = models.CharField(max_length=255, blank=True, null=True,
                            help_text='Bind username for the LDAP server. Format is server dependent but is usually the distinguished name of the user.')
    password = models.CharField(max_length=255, blank=True, null=True,
                                help_text='Password for the bind user.')
    pool = models.ForeignKey('LDAPPool', related_name='connections')
    auto_bind = models.CharField(max_length=128,
                                 default=ldap3.AUTO_BIND_NONE,
                                 choices=[(ldap3.AUTO_BIND_NONE, 'ldap3.AUTO_BIND_NONE'),
                                          (ldap3.AUTO_BIND_NO_TLS, 'ldap3.AUTO_BIND_NO_TLS'),
                                          (ldap3.AUTO_BIND_TLS_AFTER_BIND, 'ldap3.AUTO_BIND_TLS_AFTER_BIND'),
                                          (ldap3.AUTO_BIND_TLS_BEFORE_BIND, 'ldap3.AUTO_BIND_TLS_BEFORE_BIND')])
    version = models.PositiveIntegerField(default=3)
    authentication = models.CharField(max_length=128,
                                      null=True,
                                      blank=True,
                                      choices=[(ldap3.ANONYMOUS, 'ldap3.ANONYMOUS'),
                                               (ldap3.SIMPLE, 'ldap3.SIMPLE'),
                                               (ldap3.SASL, 'ldap3.SASL'),
                                               (ldap3.NTLM, 'ldap3.NTLM')])
    # TODO: Do the other client strategies make sense here?
    client_strategy = models.CharField(max_length=128,
                                       default=ldap3.SYNC,
                                       choices=[(ldap3.SYNC, 'ldap3.SYNC'),
                                                (ldap3.RESTARTABLE, 'ldap3.RESTARTABLE')])
    auto_referrals = models.BooleanField(default=True)
    sasl_mechanism = models.CharField(max_length=128,
                                      null=True,
                                      blank=True,
                                      choices=[(ldap3.EXTERNAL, 'ldap3.EXTERNAL'),
                                               (ldap3.DIGEST_MD5, 'ldap3.DIGEST_MD5'),
                                               (ldap3.KERBEROS, 'ldap3.KERBEROS'),
                                               (ldap3.GSSAPI, 'ldap3.GSSAPI')])
    sasl_credentials = models.CharField(max_length=255, blank=True, null=True, help_text='Path to an object to use as the SASL Credential.')
    read_only = models.BooleanField(default=False)
    lazy = models.BooleanField(default=False)
    check_names = models.BooleanField(default=True)
    collect_usage = models.BooleanField(default=False)
    raise_exceptions = models.BooleanField(default=False)
    pool_name = models.CharField(max_length=255, null=True, blank=True)
    pool_size = models.PositiveIntegerField(null=True, blank=True)
    pool_lifetime = models.PositiveIntegerField(null=True, blank=True)
    fast_decoder = models.BooleanField(default=True)
    receive_timeout = models.PositiveIntegerField(null=True, blank=True)
    return_empty_attributes = models.BooleanField(default=True)
    auto_range = models.BooleanField(default=True)
    use_referral_cache = models.BooleanField(default=False)
    auto_escape = models.BooleanField(default=True)
    auto_encode = models.BooleanField(default=True)

    def hydrate(self):
        """Rehydrate this LDAPConnection into a ldap.Connection object."""
        pool = self.pool.hydrate()

        return ldap3.Connection(pool,
                                user=self.user,
                                password=self.password,
                                auto_bind=self.auto_bind,
                                version=self.version,
                                authentication=self.authentication,
                                client_strategy=self.client_strategy,
                                auto_referrals=self.auto_referrals,
                                auto_range=self.auto_range,
                                sasl_mechanism=self.sasl_mechanism,
                                sasl_credentials=self.sasl_credentials,
                                check_names=self.check_names,
                                collect_usage=self.collect_usage,
                                read_only=self.read_only,
                                lazy=self.lazy,
                                raise_exceptions=self.raise_exceptions,
                                pool_name=self.pool_name,
                                pool_size=self.pool_size,
                                pool_lifetime=self.pool_lifetime,
                                fast_decoder=self.fast_decoder,
                                receive_timeout=self.receive_timeout,
                                return_empty_attributes=self.return_empty_attributes,
                                use_referral_cache=self.use_referral_cache,
                                auto_escape=self.auto_escape,
                                auto_encode=self.auto_encode)

    def __str__(self):
        return u'LDAPConnection({})'.format(','.join([i.host for i in self.pool.servers.all()]))

    class Meta:
        verbose_name = 'ldap3.Connection'
        verbose_name_plural = 'ldap3.Connections'


class LDAPPool(models.Model):
    """Equivalent to an ldap3.ServerPool."""

    servers = models.ManyToManyField('LDAPServer', related_name='pools')
    active = models.BooleanField(default=True)
    exhaust = models.BooleanField(default=False)
    pool_strategy = models.CharField(max_length=128,
                                     default=ldap3.ROUND_ROBIN,
                                     choices=[(ldap3.FIRST, 'ldap3.FIRST'),
                                              (ldap3.ROUND_ROBIN, 'ldap3.ROUND_ROBIN'),
                                              (ldap3.RANDOM, 'ldap3.RANDOM')])

    def hydrate(self):
        """Rehydrate this LDAPPool into an ldap3.ServerPool object."""
        hydrated_servers = [s.hydrate() for s in self.servers.all()]

        return ldap3.ServerPool(servers=hydrated_servers,
                                pool_strategy=self.pool_strategy,
                                active=self.active,
                                exhaust=self.exhaust)

    def __str__(self):
        return u'LDAPPool({})'.format(','.join([i.host for i in self.servers.all()]))

    class Meta:
        verbose_name = 'ldap3.ServerPool'
        verbose_name_plural = 'ldap3.ServerPools'


class LDAPServer(models.Model):
    """Equivalent to an ldap3.Server."""

    host = models.CharField(max_length=255)
    port = models.PositiveIntegerField(blank=True, null=True)
    use_ssl = models.BooleanField(default=False)
    get_info = models.CharField(max_length=128,
                                default=ldap3.SCHEMA,
                                choices=[(ldap3.NONE, 'ldap3.NONE'),
                                         (ldap3.DSA, 'ldap3.DSA'),
                                         (ldap3.SCHEMA, 'ldap3.SCHEMA'),
                                         (ldap3.ALL, 'ldap3.ALL'),
                                         (ldap3.OFFLINE_EDIR_8_8_8, 'ldap3.OFFLINE_EDIR_8_8_8'),
                                         (ldap3.OFFLINE_AD_2012_R2, 'ldap3.OFFLINE_AD_2012_R2'),
                                         (ldap3.OFFLINE_SLAPD_2_4, 'ldap3.OFFLINE_SLAPD_2_4'),
                                         (ldap3.OFFLINE_DS389_1_3_3, 'ldap3.OFFLINE_DS389_1_3_3')])
    mode = models.CharField(max_length=128,
                            default=ldap3.IP_SYSTEM_DEFAULT,
                            choices=[(ldap3.IP_SYSTEM_DEFAULT, 'ldap3.IP_SYSTEM_DEFAULT'),
                                     (ldap3.IP_V4_ONLY, 'ldap3.IP_V4_ONLY'),
                                     (ldap3.IP_V6_ONLY, 'ldap3.IP_V6_ONLY'),
                                     (ldap3.IP_V4_PREFERRED, 'ldap3.IP_V4_PREFERRED'),
                                     (ldap3.IP_V6_PREFERRED, 'ldap3.IP_V6_PREFERRED')])
    tls = models.CharField(max_length=255, blank=True, null=True, help_text='Path to a python object which contains TLS certificate information. LEAVE THIS BLANK.')
    connect_timeout = models.PositiveIntegerField(null=True, blank=True)
    allowed_referral_hosts = models.ManyToManyField('LDAPReferralHost', blank=True)

    def hydrate(self):
        """Rehydrate this LDAPServer into a ldap3.Server object."""
        # TODO: Think of a way to include a custom formatter.
        return ldap3.Server(self.host,
                            port=self.port,
                            use_ssl=self.use_ssl,
                            allowed_referral_hosts=[(h.hostname, h.allowed) for h in self.allowed_referral_hosts.all()],
                            get_info=self.get_info,
                            tls=self.tls,
                            connect_timeout=self.connect_timeout,
                            mode=self.mode)

    def __str__(self):
        if self.port is not None:
            return u'LDAPServer({}:{})'.format(self.host, self.port)
        else:
            return u'LDAPServer({})'.format(self.host)

    class Meta:
        verbose_name = 'ldap3.Server'
        verbose_name_plural = 'ldap3.Servers'


class LDAPReferralHost(models.Model):
    """ldap3.ReferralHost."""

    hostname = models.CharField(max_length=255)
    allowed = models.BooleanField(default=True)

    def __str__(self):
        """Unicode string representation of this Referral Host."""
        return u'LDAPReferralHost(hostname={})'.format(self.hostname)

    class Meta:
        verbose_name = 'ldap3.ReferralHost'
        verbose_name_plural = 'ldap3.ReferralHosts'


class LDAPSyncJob(models.Model):
    """Configuration for a Synchronisation Job."""

    name = models.CharField(max_length=255, default=petname.Generate(3, '.'), unique=True)
    target_django_model = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    synchronizer_class = models.CharField(max_length=255, default='ldap3_sync.utils.PETLSynchronizer')
    # sync_runner_class = models.CharField(max_length=255,
    #                                      default='ldap3_sync.utils.ScheduledSyncRunner',
    #                                      help_text='dotted path to the sync runner class.')
    ldap_connection = models.ForeignKey(LDAPConnection)
    base_ou = models.TextField()  # DN's can be quite long.
    search_filter = models.TextField()
    search_scope = models.CharField(max_length=100,
                                    default=ldap3.SUBTREE,
                                    choices=[(ldap3.BASE, 'ldap3.BASE'),
                                             (ldap3.LEVEL, 'ldap3.LEVEL'),
                                             (ldap3.SUBTREE, 'ldap3.SUBTREE')])
    ldap_key_attribute = models.CharField(max_length=255, help_text='The name of a unique attribute in the LDAP data that will be used for syncing.')
    django_key_attribute = models.CharField(max_length=255, help_text='The name of a unique attribute on the Django model that will be used for syncing.')
    do_create = models.BooleanField(default=True, help_text='If True then new models will ')
    do_update = models.BooleanField(default=True, help_text='U')
    do_delete = models.BooleanField(default=True)
    delete_action = models.CharField(max_length=50,
                                     default='DELETE',
                                     choices=(('DELETE', 'DELETE'), ('FUNCTION', 'Function')))
    delete_function = models.CharField(max_length=255, blank=True)  # String that points to a function that can be used for removal.
    logging_level = models.CharField(max_length=50, default='INFO', choices=[('DEBUG', 'DEBUG'),
                                                                             ('INFO', 'INFO'),
                                                                             ('WARNING', 'WARNING'),
                                                                             ('ERROR', 'ERROR'),
                                                                             ('CRITICAL', 'CRITICAL')])

    def __str__(self):
        """Return unicode string for this LDAPSync model."""
        return u'LDAP Sync Job: {}'.format(self.name)

    class Meta:
        verbose_name = 'Synchronizer Job'
        verbose_name_plural = 'Synchronizer Jobs'


class LDAPSyncAttributeMap(models.Model):
    """Maps LDAP attributes to Model Attributes."""

    sync_job = models.ForeignKey('LDAPSyncJob', related_name='attributes')
    ldap_attribute_name = models.CharField(max_length=255, help_text="LDAP Attribute Name.")
    model_attribute_name = models.CharField(max_length=255, help_text="Django Attribute Name.")

    class Meta:
        verbose_name = 'Synchronizer Attribute Map'
        verbose_name_plural = 'Synchronizer Attribute Maps'


class LDAPSyncDjangoQuerysetFilter(models.Model):
    """A filter that will be used in the django search to reitreve matching model objects."""

    sync_job = models.ForeignKey('LDAPSyncJob', related_name='filters')
    predicate = models.CharField(max_length=255, help_text='Filter predicate.')
    value = models.CharField(max_length=255, help_text='Value to filter against.')

    class Meta:
        verbose_name = 'Django Queryset Filter'
        verbose_name = 'Django Queryset Filters'


class LDAPSyncJobLog(models.Model):
    """The logging output from a LDAPSyncJob run."""

    sync_job = models.ForeignKey('LDAPSyncJob', related_name='logs')
    log_data = models.TextField(blank=True)
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField()
    successful = models.BooleanField(help_text='Simple boolean indicator as to wether this Synchonization job was successful.')

    @classmethod
    def store_log(cls, sync_job, log_data, started_at, ended_at, successful):
        """Convenience class method to take a sync_job and some log_data and store it. Will return the saved LDAPSyncJobLog."""
        l = LDAPSyncJobLog(sync_job=sync_job,
                           log_data=log_data,
                           started_at=started_at,
                           ended_at=ended_at,
                           successful=successful)
        return l.save()

    class Meta:
        verbose_name = 'Synchronizer Log'
        verbose_name_plural = 'Synchronizer Logs'
        ordering = ['started_at']
