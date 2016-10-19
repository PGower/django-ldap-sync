import logging

from django.conf import settings

from django.contrib.auth import get_user_model

from django.contrib.auth.models import Group

from django.contrib.contenttypes.models import ContentType

from django.core.exceptions import ImproperlyConfigured

from django.core.management.base import BaseCommand, CommandError

import ldap3

from ldap3.utils.conv import escape_bytes

from ldap_sync.utils import DePagingLDAPSearch, DjangoLDAPConnectionFactory, Synchronizer

from ldap_sync.models import LDAPSyncRecord

# from django.db import connection


logger = logging.getLogger(__name__)

NOTHING = 'NOTHING'
SUSPEND = 'SUSPEND'
DELETE = 'DELETE'

USER_REMOVAL_OPTIONS = (NOTHING, SUSPEND, DELETE)
GROUP_REMOVAL_OPTIONS = (NOTHING, DELETE)

DEFAULTS = {
    'LDAP_SYNC_BULK_CREATE_CHECK_SIZE': 50,
    'LDAP_SYNC_USER_FILTER': '(objectClass=user)',
    'LDAP_SYNC_USER_EXEMPT_FROM_SYNC': [],
    'LDAP_SYNC_USER_REMOVAL_ACTION': NOTHING,
    'USERNAME_FIELD': 'username',
    'LDAP_SYNC_USER_SET_UNUSABLE_PASSWORD': True,
    'LDAP_SYNC_USER_DEFAULT_ATTRIBUTES': {},
    'LDAP_SYNC_USERS': True,
    'LDAP_SYNC_GROUP_FILTER': '(objectClass=group)',
    'LDAP_SYNC_GROUP_REMOVAL_ACTION': NOTHING,
    'LDAP_SYNC_GROUP_EXEMPT_FROM_SYNC': [],
    'LDAP_SYNC_GROUP_DEFAULT_ATTRIBUTES': {},
    'LDAP_SYNC_GROUPS': True,
    'LDAP_SYNC_GROUP_MEMBERSHIP': True,
    'LDAP_SYNC_GROUP_MEMBERSHIP_FILTER': '(&(objectClass=group)(member={user_dn}))'
}


class Command(BaseCommand):
    help = "Synchronize users, groups and group membership from an LDAP server"

    def handle(self, *args, **options):
        if args:
            raise CommandError("Command doesn't accept any arguments")

        self.connection_factory = DjangoLDAPConnectionFactory()

        self.load_settings()
        if self.sync_users:
            self.sync_ldap_users()
        if self.sync_groups:
            self.sync_ldap_groups()
        if self.sync_membership:
            self.sync_group_membership()

    def get_ldap_users(self):
        """
        Retrieve user data from target LDAP server.
        """
        logging.debug('Retrieving Users from LDAP')
        connection = self.connection_factory.get_connection()
        depager = DePagingLDAPSearch(connection)
        users = depager.search(self.user_base, self.user_filter, search_scope=ldap3.SEARCH_SCOPE_WHOLE_SUBTREE, attributes=self.user_ldap_attribute_names)
        logger.info("Retrieved {} LDAP users".format(len(users)))
        return users

    def sync_ldap_users(self):
        """
        Synchronize users with local user database.
        """
        ldap_users = self.get_ldap_users()
        django_users = self.get_django_users()

        s = Synchronizer(ldap_objects=ldap_users,
                         django_objects=django_users,
                         attribute_map=self.user_attribute_map,
                         django_object_model=self.user_model,
                         unique_name_field='username',
                         exempt_unique_names=self.exempt_usernames,
                         removal_action=self.user_removal_action)
        s.sync()

    def get_ldap_groups(self):
        """
        Retrieve groups from target LDAP server.
        """
        logger.debug('Retrieving Groups from LDAP')
        connection = self.connection_factory.get_connection()
        depager = DePagingLDAPSearch(connection)
        return depager.search(self.group_base, self.group_filter, search_scope=ldap3.SEARCH_SCOPE_WHOLE_SUBTREE, attributes=self.group_ldap_attribute_names)

    def sync_ldap_groups(self):
        """
        Synchronize LDAP groups with local group database.
        """
        ldap_groups = self.get_ldap_groups()
        django_groups = self.get_django_groups()

        s = Synchronizer(ldap_objects=ldap_groups,
                         django_objects=django_groups,
                         attribute_map=self.group_attribute_map,
                         django_object_model=Group,
                         unique_name_field='name',
                         exempt_unique_names=self.exempt_groupnames,
                         removal_action=self.group_removal_action)
        s.sync()

    def get_ldap_group_membership(self, user_dn):
        """Retrieve django group ids that this user DN is a member of."""
        if not hasattr(self, '_group_cache'):
            content_type = ContentType.objects.get_for_model(Group)
            r = LDAPSyncRecord.objects.filter(content_type=content_type).all().values_list('distinguished_name', 'obj')
            self._group_cache = dict(r)
        logger.debug('Retrieving groups that {} is a member of'.format(user_dn))
        connection = self.connection_factory.get_connection()
        depager = DePagingLDAPSearch(connection)
        ldap_groups = depager.search(self.group_base, self.group_membership_filter.format(user_dn=escape_bytes(user_dn)), search_scope=ldap3.SEARCH_SCOPE_WHOLE_SUBTREE, attributes=None)
        return (self._group_cache.get(i['dn']) for i in ldap_groups if i.get('dn'))

    def sync_group_membership(self):
        '''
        Synchornize group membership with the directory. Only synchronize groups that have a related LDAPGroup object.
        '''
        django_users = self.get_django_users()
        for username, django_user in django_users.items():
            try:
                content_type = ContentType.objects.get_for_model(django_user)
                ldap_record = LDAPSyncRecord.objects.get(content_type=content_type, object_id=django_user.pk)
                user_dn = ldap_record.distinguished_name
            except LDAPSyncRecord.DoesNotExist:
                logger.warning('Django user with {} = {} does not have a distinguishedName associated'.format(self.username_field, getattr(django_user, self.username_field)))
                continue

            user_in = set(django_user.groups.values_list('pk', flat=True))
            django_groups = set(self.get_ldap_group_membership(user_dn))
            if user_in != django_groups:
                django_user.groups = django_groups
                django_user.save()
                self.stdout.write('{} added to {} groups'.format(username, len(django_groups)))
            else:
                self.stdout.write('{} group membership unchanged'.format(username))

    def get_django_users(self):
        '''
        Return a dictionary of all existing users where the key is the username and the value is the user object.
        '''
        return dict([(getattr(u, self.username_field), u) for u in self.get_django_objects(self.user_model) if getattr(u, self.username_field) not in self.exempt_usernames])

    def get_django_groups(self):
        '''
        Return a dictionary of all existing groups where the key is the group name and the value is the group object.
        DO NOT return any groups whose name in in the LDAP_SYNC_GROUP_EXEMPT_FROM_SYNC collection.
        '''
        return dict([(g.name, g) for g in self.get_django_objects(Group) if g.name not in self.exempt_groupnames])

    def load_settings(self):
        '''
        Get all of the required settings to perform a sync and check them for sanity.
        '''
        self.bulk_create_chunk_size = getattr(settings, 'LDAP_SYNC_BULK_CREATE_CHECK_SIZE', DEFAULTS['LDAP_SYNC_BULK_CREATE_CHECK_SIZE'])

        # User sync settings
        self.user_filter = getattr(settings, 'LDAP_SYNC_USER_FILTER', DEFAULTS['LDAP_SYNC_USER_FILTER'])

        try:
            self.user_base = getattr(settings, 'LDAP_SYNC_USER_BASE')
        except AttributeError:
            try:
                self.user_base = getattr(settings, 'LDAP_SYNC_BASE')
            except AttributeError:
                raise ImproperlyConfigured('Either LDAP_SYNC_USER_BASE or LDAP_SYNC_BASE are required. Neither were found.')

        try:
            self.user_attribute_map = getattr(settings, 'LDAP_SYNC_USER_ATTRIBUTES')
        except AttributeError:
            raise ImproperlyConfigured('LDAP_SYNC_USER_ATTRIBUTES is a required setting')
        self.user_ldap_attribute_names = list(self.user_attribute_map.keys())
        self.user_model_attribute_names = self.user_attribute_map.values()

        self.exempt_usernames = getattr(settings, 'LDAP_SYNC_USER_EXEMPT_FROM_SYNC', DEFAULTS['LDAP_SYNC_USER_EXEMPT_FROM_SYNC'])
        if callable(self.exempt_usernames):
            self.exempt_usernames = self.exempt_usernames()

        self.user_removal_action = getattr(settings, 'LDAP_SYNC_USER_REMOVAL_ACTION', DEFAULTS['LDAP_SYNC_USER_REMOVAL_ACTION'])
        if self.user_removal_action not in USER_REMOVAL_OPTIONS:
            raise ImproperlyConfigured('LDAP_SYNC_USER_REMOVAL_ACTION must be one of {}'.format(USER_REMOVAL_OPTIONS))

        self.user_model = get_user_model()
        self.username_field = getattr(self.user_model, 'USERNAME_FIELD', DEFAULTS['USERNAME_FIELD'])

        self.set_unusable_password = getattr(settings, 'LDAP_SYNC_USER_SET_UNUSABLE_PASSWORD', DEFAULTS['LDAP_SYNC_USER_SET_UNUSABLE_PASSWORD'])

        self.user_default_attributes = getattr(settings, 'LDAP_SYNC_USER_DEFAULT_ATTRIBUTES', DEFAULTS['LDAP_SYNC_USER_DEFAULT_ATTRIBUTES'])

        self.sync_users = getattr(settings, 'LDAP_SYNC_USERS', DEFAULTS['LDAP_SYNC_USERS'])

        # Check to make sure we have assigned a value to the username field
        if self.username_field not in self.user_model_attribute_names:
            raise ImproperlyConfigured("LDAP_SYNC_USER_ATTRIBUTES must contain the username field '%s'" % self.username_field)

        # Group sync settings
        self.group_filter = getattr(settings, 'LDAP_SYNC_GROUP_FILTER', DEFAULTS['LDAP_SYNC_GROUP_FILTER'])

        try:
            self.group_base = getattr(settings, 'LDAP_SYNC_GROUP_BASE')
        except AttributeError:
            try:
                self.group_base = getattr(settings, 'LDAP_SYNC_BASE')
            except AttributeError:
                    raise ImproperlyConfigured('Either LDAP_SYNC_GROUP_BASE or LDAP_SYNC_BASE are required. Neither were found.')

        try:
            self.group_attribute_map = getattr(settings, 'LDAP_SYNC_GROUP_ATTRIBUTES')
        except AttributeError:
            raise ImproperlyConfigured('LDAP_SYNC_GROUP_ATTRIBUTES is a required setting')
        self.group_ldap_attribute_names = list(self.group_attribute_map.keys())
        self.group_model_attribute_names = self.group_attribute_map.values()

        self.group_removal_action = getattr(settings, 'LDAP_SYNC_GROUP_REMOVAL_ACTION', DEFAULTS['LDAP_SYNC_GROUP_REMOVAL_ACTION'])
        if self.group_removal_action not in GROUP_REMOVAL_OPTIONS:
            raise ImproperlyConfigured('LDAP_SYNC_GROUP_REMOVAL_ACTION must be one of {}'.format(GROUP_REMOVAL_OPTIONS))

        self.exempt_groupnames = getattr(settings, 'LDAP_SYNC_GROUP_EXEMPT_FROM_SYNC', DEFAULTS['LDAP_SYNC_GROUP_EXEMPT_FROM_SYNC'])
        if callable(self.exempt_groupnames):
            self.exempt_groupnames = self.exempt_groupnames()

        self.group_default_attributes = getattr(settings, 'LDAP_SYNC_GROUP_DEFAULT_ATTRIBUTES', DEFAULTS['LDAP_SYNC_GROUP_DEFAULT_ATTRIBUTES'])

        self.sync_groups = getattr(settings, 'LDAP_SYNC_GROUPS', DEFAULTS['LDAP_SYNC_GROUPS'])

        self.sync_membership = getattr(settings, 'LDAP_SYNC_GROUP_MEMBERSHIP', DEFAULTS['LDAP_SYNC_GROUP_MEMBERSHIP'])

        self.group_membership_filter = getattr(settings, 'LDAP_SYNC_GROUP_MEMBERSHIP_FILTER', DEFAULTS['LDAP_SYNC_GROUP_MEMBERSHIP_FILTER'])
