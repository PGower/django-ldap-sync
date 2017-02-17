from django.contrib import admin
from django.utils.module_loading import import_string

from ldap3_sync.models import (LDAPConnection,
                               LDAPPool,
                               LDAPServer,
                               LDAPReferralHost,
                               LDAPSyncJob,
                               LDAPSyncAttributeMap,
                               LDAPSyncDjangoQuerysetFilter,
                               LDAPSyncJobLog)


class LDAPConnectionAdmin(admin.ModelAdmin):
    class Meta:
        model = LDAPConnection


class LDAPPoolAdmin(admin.ModelAdmin):
    class Meta:
        model = LDAPPool


class LDAPServerAdmin(admin.ModelAdmin):
    class Meta:
        model = LDAPServer


class LDAPReferralHostAdmin(admin.ModelAdmin):
    class Meta:
        model = LDAPReferralHost


class LDAPSyncAttributeMapAdmin(admin.TabularInline):
    model = LDAPSyncAttributeMap


class LDAPSyncDjangoQuerysetFilterAdmin(admin.TabularInline):
    model = LDAPSyncDjangoQuerysetFilter


class LDAPSyncJobAdmin(admin.ModelAdmin):
    inlines = [LDAPSyncAttributeMapAdmin, LDAPSyncDjangoQuerysetFilterAdmin]
    list_display = ['name', 'get_django_model_name', 'get_synchronizer_class_name', 'get_ldap_servers', 'do_create', 'do_update', 'do_delete']

    def get_django_model_name(self, obj):
        c = obj.target_django_model.model_class()
        return c.__name__
    get_django_model_name.short_description = 'Django Model'

    def get_synchronizer_class_name(self, obj):
        c = import_string(obj.synchronizer_class)
        return c.__name__
    get_synchronizer_class_name.short_description = 'Synchronizer Class'

    def get_ldap_servers(self, obj):
        return ','.join(i.host for i in obj.ldap_connection.pool.servers.all())
    get_ldap_servers.short_description = 'LDAP Servers'


    class Meta:
        model = LDAPSyncJob


class LDAPSyncJobLogAdmin(admin.ModelAdmin):
    list_display = ['sync_job', 'started_at', 'ended_at', 'successful']
    class Meta:
        model = LDAPSyncJobLog


admin.site.register(LDAPConnection, LDAPConnectionAdmin)
admin.site.register(LDAPPool, LDAPPoolAdmin)
admin.site.register(LDAPServer, LDAPServerAdmin)
admin.site.register(LDAPReferralHost, LDAPReferralHostAdmin)
admin.site.register(LDAPSyncJob, LDAPSyncJobAdmin)
admin.site.register(LDAPSyncJobLog, LDAPSyncJobLogAdmin)
