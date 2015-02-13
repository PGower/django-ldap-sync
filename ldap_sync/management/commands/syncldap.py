import logging

from ldap3 import (Connection,
                   Server,
                   ServerPool,
                   ANONYMOUS,
                   SIMPLE,
                   SYNC,
                   ASYNC,
                   POOLING_STRATEGY_FIRST,
                   POOLING_STRATEGY_ROUND_ROBIN,
                   POOLING_STRATEGY_RANDOM)
from ldap3.core.exceptions import LDAPExceptionError, LDAPCommunicationError

from django.conf import settings
from django.core.management.base import NoArgsCommand
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ImproperlyConfigured
from django.db import IntegrityError, DataError
from ldap_sync.models import LDAPUser, LDAPGroup


logger = logging.getLogger(__name__)


class Command(NoArgsCommand):
    help = "Synchronize users and groups from an authoritative LDAP server"

    def handle_noargs(self, **options):
        ldap_users = self.get_ldap_users()
        if ldap_users:
            self.sync_ldap_users(ldap_users)

        ldap_groups = self.get_ldap_groups()
        if ldap_groups:
            self.sync_ldap_groups(ldap_groups)

    def get_ldap_users(self):
        """
        Retrieve user data from target LDAP server.
        """
        user_filter = getattr(settings, 'LDAP_SYNC_USER_FILTER', None)
        if not user_filter:
            msg = "LDAP_SYNC_USER_FILTER not configured, skipping user sync"
            logger.info(msg)
            return None

        user_base = getattr(settings, 'LDAP_SYNC_USER_BASE', None)
        if user_base is None:
            # See if there is a LDAP_SYNC_BASE instead and use that
            global_base = getattr(settings, 'LDAP_SYNC_BASE', None)
            if global_base is None:
                error_msg = ("Either LDAP_SYNC_USER_BASE or LDAP_SYNC_BASE must be specified in your Django "
                             "settings file")
                raise ImproperlyConfigured(error_msg)
            else:
                user_base = global_base

        attributes = getattr(settings, 'LDAP_SYNC_USER_ATTRIBUTES', None)
        if not attributes:
            error_msg = ("LDAP_SYNC_USER_ATTRIBUTES must be specified in "
                         "your Django settings file")
            raise ImproperlyConfigured(error_msg)
        user_attributes = attributes.keys()

        users = self.ldap_search(user_filter, user_attributes, user_base)
        msg = "Retrieved {} LDAP users".format(len(users))
        logger.debug(msg)
        return users

    def sync_ldap_users(self, ldap_users):
        """
        Synchronize users with local user database.
        """
        model = get_user_model()
        username_field = getattr(model, 'USERNAME_FIELD', 'username')
        attributes = getattr(settings, 'LDAP_SYNC_USER_ATTRIBUTES', None)

        # Do this first
        if username_field not in attributes.values():
            error_msg = ("LDAP_SYNC_USER_ATTRIBUTES must contain the "
                         "username field '%s'" % username_field)
            raise ImproperlyConfigured(error_msg)

        # simulates django in_bulk but works with larger sets of objects
        existing_users = dict([(getattr(u, username_field), u)
                              for u in model.objects.all()])
        msg = 'Found {} existing django users'.format(len(existing_users))
        logger.info(msg)
        logger.debug('Existing django users: {}'.format(existing_users.keys()))

        unsaved_users = []
        username_cname_map = {}

        updated_users_count = 0

        for cname, attrs in ldap_users:
            # In some cases with AD, attrs is a list instead of a
            # dict; these are not valid users, so skip them
            try:
                items = attrs.items()
            except AttributeError:
                continue

            # Extract user attributes from LDAP response
            user_attr = {}
            for name, attr in items:
                user_attr[attributes[name]] = attr[0].decode('utf-8')

            try:
                username = user_attr[username_field]
                username = username.lower()
                user_attr[username_field] = username
            except KeyError:
                logger.warning("User is missing a required attribute '%s'" %
                               username_field)
                continue

            username_cname_map[username] = cname

            if username in existing_users:
                this_local_user = existing_users[username]
                if self.will_object_change(user_attr, this_local_user):
                    this_updated_local_user = self.apply_updated_attrs(user_attr, this_local_user)
                    this_updated_local_user.save()
                    updated_users_count += 1
                # Regardless of whether the user is updated or not, remove from existing users
                del(existing_users[username])
            else:
                new_user = model(**user_attr)
                # When a new user is created make their password unusable. This should cover everyone.
                new_user.set_unusable_password()
                unsaved_users.append(new_user)
        model.objects.bulk_create(unsaved_users)
        
        msg = 'Updated {} existing django users'.format(updated_users_count)
        self.stdout.write(msg)
        logger.info(msg)

        msg = 'Created {} new django users'.format(len(unsaved_users))
        self.stdout.write(msg)
        logger.info(msg)

        # Anything left in the existing_users dict is no longer in the ldap directory
        # These should be disabled.
        exempt_users = getattr(settings, 'LDAP_SYNC_USER_EXEMPT_FROM_REMOVAL', [])
        removal_action = getattr(settings, 'LDAP_SYNC_USER_REMOVAL_ACTION', 'nothing')

        existing_user_ids = set([getattr(i, username_field) for i in existing_users.values()])
        existing_user_ids.difference_update(exempt_users)

        if removal_action != 'nothing' and len(existing_users) > 0:
            if removal_action == 'disable':
                model.objects.filter(username__in=existing_user_ids).update(is_active=False)
                msg = 'Disabling {} django users'.format(len(existing_user_ids))
                logger.info(msg)
                self.stdout.write(msg)
                logger.debug('Disabling django users: {}'.format(existing_user_ids))
            if removal_action == 'delete':
                # There are going to be issues here if there are more than 999 exiting user ids
                model.objects.filter(username__in=existing_user_ids).delete()
                msg = 'Deleting {} django users'.format(len(existing_user_ids))
                logger.info(msg)
                self.stdout.write(msg)
                logger.debug('Deleting django users: {}'.format(existing_user_ids))
        else:
            if len(existing_user_ids) > 0:
                msg = '{} django users no longer exist in the LDAP store but are being ignored as LDAP_SYNC_USER_REMOVAL_ACTION = \'nothing\''.format(len(existing_user_ids))
                self.stdout.write(msg)
                logger.warn(msg)

        # Update LDAPUser objects, create new LDAPUser records where neccessary and update existing where changed
        unsaved_ldap_users = []
        current_users = model.objects.all().iterator()
        for current_user in current_users:
            try:
                cname = username_cname_map[current_user.username]
            except KeyError:
                continue

            try:
                ldap_user = current_user.ldap_sync_user
            except LDAPUser.DoesNotExist:
                new_ldap_user = LDAPUser(user=current_user, distinguishedName=cname)
                unsaved_ldap_users.append(new_ldap_user)
                continue

            if not ldap_user.distinguishedName == cname:
                ldap_user.distinguishedName = cname
                ldap_user.save()
        LDAPUser.objects.bulk_create(unsaved_ldap_users)

        logger.info("Users are synchronized")
        self.stdout.write('Users are synchronized')


    def get_ldap_groups(self):
        """
        Retrieve groups from target LDAP server.
        """
        group_filter = getattr(settings, 'LDAP_SYNC_GROUP_FILTER', None)
        if not group_filter:
            msg = "LDAP_SYNC_GROUP_FILTER not configured, skipping group sync"
            logger.info(msg)
            return None

        group_base = getattr(settings, 'LDAP_SYNC_GROUP_BASE', None)
        if not group_base:
            global_base = getattr(settings, 'LDAP_SYNC_BASE', None)
            if global_base is None:                
                error_msg = ("Either LDAP_SYNC_GROUP_BASE or LDAP_SYNC_BASE must be specified in your Django "
                             "settings file")
                raise ImproperlyConfigured(error_msg)
            else:
                group_base = global_base

        attributes = getattr(settings, 'LDAP_SYNC_GROUP_ATTRIBUTES', None)
        if not attributes:
            error_msg = ("LDAP_SYNC_GROUP_ATTRIBUTES must be specified in "
                         "your Django settings file")
            raise ImproperlyConfigured(error_msg)
        group_attributes = attributes.keys()

        sync_membership = getattr(settings, 'LDAP_SYNC_GROUP_MEMBERSHIP', False)
        if sync_membership:
            group_attributes.append('member')

        groups = self.ldap_search(group_filter, group_attributes, group_base)
        msg = "Retrieved %d groups" % len(groups)
        logger.debug(msg)
        self.stdout.write(msg)
        return groups

    # def get_ldap_group_membership(self, group_cname):
    #     '''
    #     Retrieve a list of users who are members of the given group.
    #     '''
    #     group_base = getattr(settings, 'LDAP_SYNC_GROUP_BASE', None)
    #     if not group_base:
    #         error_msg = ("LDAP_SYNC_GROUP_BASE must be specified in your Django "
    #                      "settings file")
    #         raise ImproperlyConfigured(error_msg)

    #     membership_attributes = ['member']
    #     members = self.ldap_search()

    def sync_ldap_groups(self, ldap_groups):
        """
        Synchronize LDAP groups with local group database.
        """
        existing_groups = dict([(i.name, i) for i in Group.objects.all()])

        attributes = getattr(settings, 'LDAP_SYNC_GROUP_ATTRIBUTES', None)
        groupname_field = 'name'

        if groupname_field not in attributes.values():
            error_msg = ("LDAP_SYNC_GROUP_ATTRIBUTES must contain the "
                         "group name field '%s'" % groupname_field)
            raise ImproperlyConfigured(error_msg)

        unsaved_groups = []

        groupname_cname_map = {}
        groupname_members_map = {}

        updated_groups_count = 0

        for cname, attrs in ldap_groups:
            try:
                group_membership = attrs['member']
                del(attrs['member'])
            except KeyError:
                pass

            # In some cases with AD, attrs is a list instead of a
            # dict; these are not valid groups, so skip them
            try:
                items = attrs.items()
            except AttributeError:
                continue

            # Extract user data from LDAP response
            group_attr = {}
            for name, attr in items:
                group_attr[attributes[name]] = attr[0].decode('utf-8')

            try:
                groupname = group_attr[groupname_field]
                groupname = groupname.lower()
                group_attr[groupname_field] = groupname
            except KeyError:
                logger.warning("Group is missing a required attribute '%s'" %
                               groupname_field)
                continue

            groupname_cname_map[groupname] = cname
            groupname_members_map[groupname] = group_membership

            if groupname in existing_groups:
                this_local_group = existing_groups[groupname]
                if self.will_object_change(group_attr, this_local_group):
                    this_updated_local_group = self.apply_updated_attrs(group_attr, this_local_group)
                    this_updated_local_group.save()
                    updated_groups_count += 1
                del(existing_groups[groupname])
            else:
                new_group = Group(**group_attr)
                unsaved_groups.append(new_group)
        Group.objects.bulk_create(unsaved_groups)

        msg = 'Updated {} existing django groups'.format(updated_groups_count)
        self.stdout.write(msg)
        logger.info(msg)

        msg = 'Created {} new django groups'.format(len(unsaved_groups))
        self.stdout.write(msg)
        logger.info(msg)

        exempt_groups = getattr(settings, 'LDAP_SYNC_GROUP_EXEMPT_FROM_REMOVAL', [])

        orphaned_group_names = set([i.name for i in existing_groups.values()])
        orphaned_group_names.difference_update(exempt_groups)

        Group.objects.filter(name__in=orphaned_group_names).delete()

        if len(orphaned_group_names) > 0:
            msg = '{} django groups no longer exist in the LDAP store and have been deleted'.format(len(orphaned_group_names))
            logger.info(msg)
            self.stdout.write(msg)

        # Update LDAPUser objects, create new LDAPUser records where neccessary and update existing where changed
        unsaved_ldap_groups = []
        current_groups = Group.objects.all().iterator()
        for current_group in current_groups:
            try:
                cname = groupname_cname_map[current_group.name]
            except KeyError:
                continue

            try:
                ldap_group = current_group.ldap_sync_group
            except LDAPGroup.DoesNotExist:
                new_ldap_group = LDAPGroup(group=current_group, distinguishedName=cname)
                unsaved_ldap_groups.append(new_ldap_group)
                continue

            if not ldap_group.distinguishedName == cname:
                ldap_group.distinguishedName = cname
                ldap_group.save()
        LDAPGroup.objects.bulk_create(unsaved_ldap_groups)

        msg = "Groups are synchronized"
        logger.info(msg)
        self.stdout.write(msg)

        sync_membership = getattr(settings, 'LDAP_SYNC_GROUP_MEMBERSHIP', False)
        if sync_membership:
            msg = 'Synchronizing Group Membership'
            logger.info(msg)
            self.stdout.write(msg)

            current_groups = Group.objects.all().iterator()
            for current_group in current_groups:
                try:
                    ldap_group = current_group.ldap_sync_group
                except LDAPGroup.DoesNotExist:
                    # No matching LDAPGroup, just continue and ignore
                    msg = 'Skipping {} because a matching LDAPGroup cannot be found'.format(current_group)
                    logger.info(msg)
                    self.stdout.write(msg)
                    continue

                try:
                    ldap_membership = groupname_members_map[current_group.name]
                except KeyError:
                    # No membership results, continue and ignore
                    msg = 'Skipping {} because no membership can be found for it'.format(current_group)
                    logger.info(msg)
                    self.stdout.write(msg)
                    continue

                msg = 'Synchronizing membership for {}'.format(current_group)
                logger.info(msg)
                self.stdout.write(msg)
                # Get ldap_users who should be in this group
                ldap_users = LDAPUser.objects.filter(distinguishedName__in=ldap_membership).all()
                # Apply to the auth group
                auth_users = [l.user for l in ldap_users]
                # This removes old users as well as setting new ones
                current_group.user_set = auth_users

            msg = 'Finished Synchronizing Group Membership'
            logger.info(msg)
            self.stdout.write(msg)

    def ldap_search(self, filter, attributes, base):
        """
        Query the configured LDAP server with the provided search
        filter and attribute list. Returns a list of the results
        returned.
        """
        uri = getattr(settings, 'LDAP_SYNC_URI', None)
        if not uri:
            error_msg = ("LDAP_SYNC_URI must be specified in your Django "
                         "settings file")
            raise ImproperlyConfigured(error_msg)

        bind_user = getattr(settings, 'LDAP_SYNC_BIND_USER', None)
        if not bind_user:
            error_msg = ("LDAP_SYNC_BIND_USER must be specified in your "
                         "Django settings file")
            raise ImproperlyConfigured(error_msg)

        bind_pass = getattr(settings, 'LDAP_SYNC_BIND_PASS', None)
        if not bind_pass:
            error_msg = ("LDAP_SYNC_BIND_PASS must be specified in your "
                         "Django settings file")
            raise ImproperlyConfigured(error_msg)

        # base = getattr(settings, 'LDAP_SYNC_BASE', None)
        # if not base:
        #     error_msg = ("LDAP_SYNC_BASE must be specified in your Django "
        #                  "settings file")
        #     raise ImproperlyConfigured(error_msg)

        ldap.set_option(ldap.OPT_REFERRALS, 0)
        l = PagedLDAPObject(uri)
        l.protocol_version = 3
        try:
            l.simple_bind_s(bind_user, bind_pass)
        except ldap.LDAPError as e:
            logger.error("Error connecting to LDAP server %s" % uri)
            raise e

        results = l.paged_search_ext_s(base,
                                       ldap.SCOPE_SUBTREE,
                                       filter,
                                       attrlist=attributes,
                                       serverctrls=None)
        l.unbind_s()
        return results

    def will_object_change(self, ldap_attrs, local_object):
        '''
        Return true if the data in the ldap_user would change the data stored
        in the local_object, otherwise false.
        '''
        # I think all the attrs are utf-8 strings, possibly need to coerce
        # local user values to strings?
        for key, value in ldap_attrs.items():
            if not getattr(local_object, key) == value:
                return True
        return False

    def apply_updated_attrs(self, ldap_attrs, local_user):
        for key, value in ldap_attrs.items():
            setattr(local_user, key, value)
        return local_user

    def extract_attributes(self, ldap_object, ldap_attrs):
        object_attrs = {}
        for name, attr in 
                    user_attr = {}
            for name, attr in items:
                user_attr[attributes[name]] = attr[0].decode('utf-8')


class SmartLDAPSearcher:
    def __init__(self):
        server_defs = getattr(settings, 'LDAP_SERVERS', None)
        if server_defs is None:
            raise ImproperlyConfigured('LDAP_SERVERS must be defined in the django settings file')
        pooling_strategy = getattr(server_defs, 'POOLING_STRATEGY', 'ROUND_ROBIN')
        pooling_strategy = self._strategy_to_constant(pooling_strategy)
        self.server_pool = ServerPool(None, pooling_strategy)
        

    def _strategy_to_constant(self, strategy):
        if strategy.lower() == 'round_robin':
            return POOLING_STRATEGY_ROUND_ROBIN
        elif strategy.lower() == 'first':
            return POOLING_STRATEGY_FIRST
        elif strategy.lower() == 'random':
            return POOLING_STRATEGY_RANDOM
        else:
            raise ImproperlyConfigured('Invalid pooling strategy passed {}, stratey can be one of RANDOM, ROUND_ROBIN, FIRST')




class PagedResultsSearchObject:
    """
    Taken from the python-ldap paged_search_ext_s.py demo, showing how to use
    the paged results control: https://bitbucket.org/jaraco/python-ldap/
    """
    page_size = getattr(settings, 'LDAP_SYNC_PAGE_SIZE', 100)

    def paged_search_ext_s(self, base, scope, filterstr='(objectClass=*)',
                           attrlist=None, attrsonly=0, serverctrls=None,
                           clientctrls=None, timeout=-1, sizelimit=0):
        """
        Behaves exactly like LDAPObject.search_ext_s() but internally uses the
        simple paged results control to retrieve search results in chunks.
        """
        req_ctrl = SimplePagedResultsControl(True, size=self.page_size,
                                             cookie='')

        # Send first search request
        msgid = self.search_ext(base, ldap.SCOPE_SUBTREE, filterstr,
                                attrlist=attrlist,
                                serverctrls=(serverctrls or []) + [req_ctrl])
        results = []

        while True:
            rtype, rdata, rmsgid, rctrls = self.result3(msgid)
            results.extend(rdata)
            # Extract the simple paged results response control
            pctrls = [c for c in rctrls if c.controlType ==
                      SimplePagedResultsControl.controlType]

            if pctrls:
                if pctrls[0].cookie:
                    # Copy cookie from response control to request control
                    req_ctrl.cookie = pctrls[0].cookie
                    msgid = self.search_ext(base, ldap.SCOPE_SUBTREE,
                                            filterstr, attrlist=attrlist,
                                            serverctrls=(serverctrls or []) +
                                            [req_ctrl])
                else:
                    break

        return results


class PagedLDAPObject(LDAPObject, PagedResultsSearchObject):
    pass
