from django.db import models
from django.conf import settings
from django.contrib.auth.models import Group

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType

from django.db.models.fields import AutoField

# import ldap3

# Store LDAP info about the created groups so that we can easily
# identify them in subsequent syncs

HELP_TEXT = ('DO NOT edit this unless you really know '
             'what your doing. It is much safer to delete '
             'this entire record and let the sync command '
             'recreate it.')


class LDAPSyncRecord(models.Model):
    '''Used to record a link between any model synchronised by django-ldap3-sync and its distinguished_name in the directory'''
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    distinguished_name = models.TextField(blank=False, help_text=HELP_TEXT)
    obj = GenericForeignKey('content_type', 'object_id')
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.CharField(max_length=255)  # Try to ensure compatibility

    def touch(self):
        '''Update the updated_at time by saving the model'''
        self.save()

    def __unicode__(self):
        return u'LDAPSyncRecord({}, {})'.format(str(self.obj), self.distinguished_name[:35])

    class Meta:
        verbose_name = 'LDAP Sync Record'
        verbose_name_plural = 'LDAP Sync Records'
        unique_together = [('distinguished_name', 'content_type', 'object_id')]


class LDAPConnection(models.Model):
    '''Configuration that can be used to construct an ldap3 connection object'''
    user = models.CharField(max_length=255, blank=True, null=True)
    password = models.CharField(max_length=255, blank=True, null=True)
    auto_bind = models.CharField(max_length=128,
                                 null=True,
                                 blank=True,
                                 choices=[('AUTO_BIND_NONE', 'ldap3.AUTO_BIND_NONE'),
                                          ('AUTO_BIND_NO_TLS', 'ldap3.AUTO_BIND_NO_TLS'),
                                          ('AUTO_BIND_TLS_BEFORE_BIND', 'ldap3.AUTO_BIND_TLS_BEFORE_BIND'),
                                          ('AUTO_BIND_TLS_AFTER_BIND', 'ldap3.AUTO_BIND_TLS_AFTER_BIND')])
    version = models.PositiveIntegerField(blank=True, null=True)
    authentication = models.CharField(max_length=128,
                                      null=True,
                                      blank=True,
                                      choices=[('ANONYMOUS', 'ldap3.ANONYMOUS'),
                                               ('SIMPLE', 'ldap3.SIMPLE'),
                                               ('SASL', 'ldap3.SASL'),
                                               ('NTLM', 'ldap3.NTLM')])
    client_strategy = models.CharField(max_length=128,
                                       null=True,
                                       blank=True,
                                       choices=[('SYNC', 'ldap3.SYNC'),
                                                ('ASYNC', 'ldap3.ASYNC'),
                                                ('LDIF', 'ldap3.LDIF'),
                                                ('RESTARTABLE', 'ldap3.RESTARTABLE'),
                                                ('REUSABLE', 'ldap3.REUSABLE'),
                                                ('MOCK_SYNC', 'ldap3.MOCK_SYNC'),
                                                ('MOCK_ASYNC', 'ldap3.MOCK_ASYNC')])
    auto_referrals = models.BooleanField(null=True, blank=True)
    sasl_mechanism = models.CharField(max_length=128,
                                      null=True,
                                      blank=True,
                                      choices=[('EXTERNAL', 'ldap3.EXTERNAL'),
                                               ('DIGEST_MD5', 'ldap3.DIGEST_MD5'),
                                               ('KERBEROS', 'ldap3.KERBEROS'),
                                               ('GSSAPI', 'ldap3.GSSAPI')])
    read_only = models.BooleanField(null=True, blank=True)
    lazy = models.BooleanField(null=True, blank=True)
    check_names = models.BooleanField(null=True, blank=True)
    raise_exceptions = models.BooleanField(null=True, blank=True)
    pool_name = models.CharField(max_length=255, null=True, blank=True)
    pool_size = models.PositiveIntegerField(null=True, blank=True)
    pool_lifetime = models.PositiveIntegerField(null=True, blank=True)
    fast_decoder = models.BooleanField(null=True, blank=True)
    receive_timeout = models.PositiveIntegerField(null=True, blank=True)
    return_empty_attributes = models.BooleanField(null=True, blank=True)

    def to_dict(self):
        connection = {}
        for k in ['user', 'password', 'auto_bind', 'version', 'authentication',
                  'client_strategy', 'auto_referrals', 'sasl_mechanism', 'read_only',
                  'lazy', 'check_names', 'raise_exceptions', 'pool_name', 'pool_size',
                  'pool_lifetime', 'fast_decoder', 'receive_timeout', 'return_empty_attributes']:
            v = getattr(self, k)
            if v is not None:
                connection[k] = v
        pool = {}
        if self.pool is not None:
            for k in ['active', 'exhaust', 'pool_strategy']:
                v = getattr(self.pool, k)
                if v is not None:
                    pool[k] = v
        servers = []
        for server_object in self.servers.all():
            server = {}
            for k in ['host', 'port', 'use_ssl', 'get_info', 'mode', 'connect_timeout']:
                v = getattr(server_object, k)
                if v is not None:
                    server[k] = v
            server['allowed_referral_hosts'] = [(h.hostname, h.allowed) for h in server_object.allowed_referral_hosts.all()]
            servers.append(server)
        return {'connection': connection,
                'pool': pool,
                'servers': servers}

    def __unicode__(self):
        return u'LDAPConnection(pk={})'.format(self.pk)


class LDAPPool(models.Model):
    connection = models.OneToOneField('LDAPConnection', related_name='pool')
    active = models.BooleanField(null=True, blank=True)
    exhaust = models.BooleanField(null=True, blank=True)
    pool_strategy = models.CharField(max_length=128,
                                     null=True,
                                     blank=True,
                                     choices=[('FIRST', 'ldap3.FIRST'),
                                              ('ROUND_ROBIN', 'ldap3.ROUND_ROBIN'),
                                              ('RANDOM', 'ldap3.RANDOM')])

    def __unicode__(self):
        return u'LDAPPool(pk={})'.format(self.pk)


class LDAPServer(models.Model):
    connection = models.ForeignKey('LDAPConnection', related_name='servers')
    host = models.CharField(max_length=255)
    port = models.PositiveIntegerField(blank=True, null=True)
    use_ssl = models.BooleanField(blank=True, null=True)
    get_info = models.CharField(max_length=128,
                                blank=True,
                                null=True,
                                choices=[('GET_NO_INFO', 'ldap3.GET_NO_INFO'),
                                         ('GET_DSA_INFO', 'ldap3.GET_DSA_INFO'),
                                         ('GET_SCHEMA_INFO', 'ldap3.GET_SCHEMA_INFO'),
                                         ('GET_ALL_INFO', 'ldap3.GET_ALL_INFO')])
    mode = models.CharField(max_length=128,
                            blank=True,
                            null=True,
                            choices=[('IP_SYSTEM_DEFAULT', 'ldap3.IP_SYSTEM_DEFAULT'),
                                     ('IP_V4_ONLY', 'ldap3.IP_V4_ONLY'),
                                     ('IP_V6_ONLY', 'ldap3.IP_V6_ONLY'),
                                     ('IP_V4_PREFERRED', 'ldap3.IP_V4_PREFERRED'),
                                     ('IP_V6_PREFERRED', 'ldap3.IP_V6_PREFERRED')])
    connect_timeout = models.PositiveIntegerField(null=True, blank=True)

    def __unicode__(self):
        return u'LDAPServer(host={})'.format(self.host)


class LDAPReferralHost(models.Model):
    server = models.ForeignKey('LDAPServer', related_name='allowed_referral_hosts')
    hostname = models.CharField(max_length=255)
    allowed = models.BooleanField(default=True)

    def __unicode__(self):
        return u'LDAPReferralHost(hostname={})'.format(self.hostname)
