from django.contrib import admin

from ldap3_sync.models import LDAPSyncRecord

# Only providing these so that if something odd happens
# They can be deleted from the admin interface


# class LDAPUserAdmin(admin.ModelAdmin):
#     model = LDAPUser
#     ordering = ['obj__username']
#     fields = ['distinguished_name']
#     search_fields = ['obj__username', 'obj__first_name',
#                      'obj__last_name', 'distinguished_name']


# class LDAPGroupAdmin(admin.ModelAdmin):
#     model = LDAPGroup
#     ordering = ['obj__name']
#     fields = ['distinguished_name']
#     search_fields = ['obj__name', 'distinguished_name']


admin.site.register(LDAPSyncRecord)
