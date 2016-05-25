# Utility Classes / Functions for Synchronization
import logging

from django.contrib.contenttypes.models import ContentType

from django.core.exceptions import ImproperlyConfigured

import ldap3

from ldap3_sync.models import LDAPSyncRecord

import petname

NOTHING = 'NOTHING'
SUSPEND = 'SUSPEND'
DELETE = 'DELETE'

logger = logging.getLogger(__name__)


class Synchronizer(object):
    def __init__(self,
                 ldap_objects=None,
                 django_objects=None,
                 attribute_map=None,
                 django_object_model=None,
                 unique_name_field=None,
                 exempt_unique_names=[],
                 removal_action=NOTHING,
                 bulk_create_chunk_size=50,
                 name=None,
                 **kwargs):
        self.ldap_objects_v = ldap_objects
        self.django_objects_v = django_objects
        self.attribute_map_v = attribute_map
        self.django_object_model_v = django_object_model
        self.unique_name_field_v = unique_name_field
        self.exempt_unique_names = exempt_unique_names
        self.removal_action_v = removal_action
        self.bulk_create_chunk_size = bulk_create_chunk_size

        self.uniquename_dn_map = {}

        self.name = petname.Generate(3, '_') if name is None else name

        self.unsaved_models_v = []

        self.updated_model_counter = 0
        self.created_model_counter = 0
        self.deleted_model_counter = 0
        self.processed_ldap_objects_counter = 0

        self.kwargs = kwargs

        # I want the synchronizer name in the logs so im going to fudge the name while retaining the heirarchy
        self.logger = logging.getLogger(__name__ + '.{}'.format(self.name))

    def _ldap_objects(self):
        '''Return the ldap objects that the sync method will work with. If
        self._ldap_objects is None and this method has not been implemented
        then raise NotImplemented'''
        if self.ldap_objects_v is None:
            raise NotImplemented
        return self.ldap_objects_v
    ldap_objects = property(_ldap_objects, 'Return the set of ldap objects which will be synced from')

    def _django_objects(self):
        '''Return the django objects that the sync method will work with. If
        self._django_objects is None and this method has not been implemented
        then raise NotImplemented
        Django objects is expected to be a dictionary mapping uniquenames to models'''
        if self.django_objects_v is None:
            raw_objects = self.get_django_objects(self.django_object_model)
            self.django_objects_v = dict([(getattr(ro, self.unique_name_field), ro) for ro in raw_objects])
        return self.django_objects_v
    django_objects = property(_django_objects, 'The set of django objects which will be synced against')

    def _attribute_map(self):
        '''Return the attribute map'''
        if self.attribute_map_v is None:
            raise NotImplemented
        return self.attribute_map_v
    attribute_map = property(_attribute_map, 'The attribute map used to extract values from the ldap objects')

    def _django_object_model(self):
        '''Return the model for the django object that is going to be synchronized'''
        if self.django_object_model_v is None:
            raise NotImplemented
        return self.django_object_model_v
    django_object_model = property(_django_object_model, 'The django object model used in this synchornization')

    def _django_object_model_name(self):
        return self.django_object_model.__name__
    django_object_model_name = property(_django_object_model_name, 'The name of the django object model')

    def _unique_name_field(self):
        '''Return the unique name field '''
        if self.unique_name_field_v is None:
            raise NotImplemented
        return self.unique_name_field_v
    unique_name_field = property(_unique_name_field, 'Return the unique name field used to match ldap and django objects')

    def _ldap_sync_model(self):
        '''Return the django model that will record ldap sync mappings. By default this will be LDAPSyncRecord'''
        return LDAPSyncRecord
    ldap_sync_model = property(_ldap_sync_model, 'Return the model used to store the object -> distinguished name mapping')

    # def _ldap_sync_related_name(self):
    #     '''Return the related name for the django model that will map to the ldap_sync_model'''
    #     if self.ldap_sync_related_name_v is None:
    #         raise NotImplemented
    #     return self.ldap_sync_related_name_v
    # ldap_sync_related_name = property(_ldap_sync_related_name, 'The related name that maps django objects to the ldap sync model')

    def exempt_unique_name(self, unique_name):
        '''Return true if this unique name should be exempt from sync'''
        if unique_name in self.exempt_unique_names:
            return True
        else:
            return False

    def _removal_action(self, unique_name):
        '''Return 1 of the existing 3 removal actions or return a callable that takes a set of django objects
        that need to be actioned'''
        if self.removal_action_v is None:
            raise NotImplemented
        return self.removal_action_v
    removal_action = property(_removal_action)

    def add_uniquename_dn_map(self, unique_name, distinguished_name):
        '''Add a uniquename -> dn mapping to the internal sync map'''
        self.uniquename_dn_map[unique_name] = distinguished_name

    def uniquename_in_map(self, unique_name):
        '''Return true if the uniquename exists in the map'''
        if unique_name in self.uniquename_dn_map.keys():
            return True
        else:
            return False

    def dn_in_map(self, distinguished_name):
        '''Return true if the distinguished name exists in the map'''
        if distinguished_name in self.uniquename_dn_map.values():
            return True
        else:
            return False

    def _unsaved_models(self):
        return self.unsaved_models_v
    unaved_models = property(_unsaved_models, 'A list object containing all of the unsaved django models created by the sync process')

    def add_unsaved_model(self, unsaved_model):
        self.unsaved_models.append(unsaved_model)

    def sync(self):
        '''A generic synchronizaation method for LDAP objects to Django Models'''
        for ldap_object in self.ldap_objects():
            if ldap_object.get('type') != 'searchResEntry':
                continue

            try:
                value_map = self.generate_value_map(self.attribute_map, ldap_object['attributes'])
            except MissingLdapField as e:
                self.logger.error('LDAP Object {ldap_object} is missing a field: {field_name}'.format(ldap_object=ldap_object['dn'], field_name=e))
                continue

            # Courtesy of github:andebor
            # Check to make sure that the value returned from the ldap store is not a list (multi valued element).
            # Usually DN is not but it seems some servers send it back this way
            if type(value_map[self.unique_name_field]) is list:
                unique_name = value_map[self.unique_name_field][0]
            else:
                unique_name = value_map[self.unique_name_field]
            distinguished_name = ldap_object['dn']

            self.add_uniquename_dn_map(unique_name, distinguished_name)

            try:
                django_object = self.django_objects[unique_name]
                if self.will_model_change(value_map, django_object):
                    self.apply_value_map(value_map, django_object)
                    django_object.save()
                    self.updated_model_counter += 1
                try:
                    content_type = ContentType.objects.get_for_model(self.django_object_model)
                    ldap_sync_record = self.ldap_sync_model.objects.get(content_type=content_type, object_id=django_object.pk)

                    if ldap_sync_record.distinguished_name != distinguished_name:
                        ldap_sync_record.distinguished_name = distinguished_name
                        ldap_sync_record.save()
                except self.ldap_sync_model.DoesNotExist:
                    self.ldap_sync_model(obj=django_object, distinguished_name=distinguished_name).save()
                del(self.django_objects[unique_name])
            except KeyError:
                django_object = self.django_object_model(**value_map)
                # if hasattr(django_object, 'set_unusable_password') and self.set_unusable_password:
                #     # only do this when its a user (or has this method) and the config says to do it
                #     django_object.set_unusable_password()
                self.add_unsaved_model(django_object)
        self.logger.debug('Bulk creating unsaved {}'.format(self.django_object_model_name))
        self.chunked_bulk_create(self.django_object_model, self.unsaved_models)
        # django_object_model.objects.bulk_create(self.unsaved_models)
        self.logger.debug('Retrieving ID\'s for the objects that were just created')

        filter_key = '{}__in'.format(self.unique_name_field)
        filter_value = [getattr(u, self.unique_name_field) for u in self.unsaved_models]
        just_saved_models = self.django_object_model.objects.filter(**{filter_key: filter_value}).all()
        just_saved_models = self.chunked_just_saved(self.django_object_model, filter_key, filter_value)
        self.logger.debug('Bulk creating ldap_sync models')
        new_ldap_sync_models = [self.ldap_sync_model(obj=u, distinguished_name=self.uniquename_dn_map[getattr(u, self.unique_name_field)]) for u in just_saved_models]
        self.chunked_bulk_create(self.ldap_sync_model, new_ldap_sync_models)

        msg = 'Updated {} existing {}'.format(self.updated_model_counter, self.django_object_model_name)
        self.logger.info(msg)

        msg = 'Created {} new {}'.format(len(self.unsaved_models), self.django_object_model_name)
        self.logger.info(msg)

        # Anything left in the existing_users dict is no longer in the ldap directory
        # These should be disabled.
        existing_unique_names = set(_unique_name for _unique_name in self.django_objects.keys())
        # existing_unique_names.difference_update(exempt_unique_names)
        existing_model_ids = [djo.id for djo in self.django_objects.values() if getattr(djo, self.unique_name_field) in existing_unique_names]

        # TODO: Removal action can return a callable
        if self.removal_action == NOTHING:
            self.logger.info('Removal action is set to NOTHING so the {} objects that would have been removed are being ignored.'.format(len(existing_unique_names)))
        elif self.removal_action == SUSPEND:
            if hasattr(self.django_object_model, 'is_active'):
                self.django_object_model.objects.in_bulk(existing_model_ids).update(is_active=False)
                self.logger.info('Suspended {} {}.'.format(len(existing_model_ids), self.django_object_model_name))
            else:
                self.logger.info('REMOVAL_ACTION is set to SUSPEND however {} do not have an is_active attribute. Effective action will be NOTHING for {}.'.format(self.django_object_model_name, len(existing_model_ids)))
        elif self.removal_action == DELETE:
            self.django_object_model.objects.filter(id__in=existing_model_ids).all().delete()
            self.logger.info('Deleted {} {}.'.format(len(existing_unique_names), self.django_object_model_name))

        self.logger.info("{} are synchronized".format(self.django_object_model_name))

    def will_model_change(self, value_map, user_model):
        # I think all the attrs are utf-8 strings, possibly need to coerce
        # local user values to strings?
        for model_attr, value in value_map.items():
            if not getattr(user_model, model_attr) == value:
                return True
        return False

    def chunked_bulk_create(self, django_model_object, unsaved_models, chunk_size=None):
        '''Create new models using bulk_create in batches of `chunk_size`.
        This is designed to overcome a query size limitation in some databases'''
        if chunk_size is None:
            chunk_size = self.bulk_create_chunk_size
        for i in range(0, len(unsaved_models), chunk_size):
            django_model_object.objects.bulk_create(unsaved_models[i:i + chunk_size])

    def chunked_just_saved(self, django_model_object, filter_key, unique_names, chunk_size=None):
        '''Get django_object_models in batches'''
        if chunk_size is None:
            chunk_size = self.bulk_create_chunk_size
        results = []
        for i in range(0, len(unique_names), chunk_size):
            results += django_model_object.objects.filter(**{filter_key: unique_names[i:i + chunk_size]})
        return results

    def apply_value_map(self, value_map, user_model):
        for k, v in value_map.items():
            try:
                setattr(user_model, k, v)
            except AttributeError:
                raise UnableToApplyValueMapError('User model {} does not have attribute {}'.format(user_model.__class__.__name__, k))
        return user_model

    def generate_value_map(self, attribute_map, ldap_attribute_values):
        '''Given an attribute map (dict with keys as ldap attrs and values as model attrs) generate a dictionary
           which maps model attribute keys to ldap values'''
        value_map = {}
        for ldap_attr, model_attr in attribute_map.items():
            try:
                value_map[model_attr] = ldap_attribute_values[ldap_attr]
            except KeyError:
                raise MissingLdapField(ldap_attr)
            # If we recieve a list / tuple for an LDAP attribute return only the first item.
            if type(value_map[model_attr]) is list or type(value_map[model_attr]) is tuple:
                try:
                    value_map[model_attr] = value_map[model_attr][0]
                except IndexError:
                    # This might be the wront way to do this. If we recieved a value but its empty then that seems like something we want to know.
                    value_map[model_attr] = None
        return value_map

    def get_django_objects(self, model):
        '''
        Given a Django model class get all of the current records that match.
        This is better than django's bulk methods and has no upper limit.
        '''
        model_name = model.__class__.__name__
        model_objects = [i for i in model.objects.all()]
        self.logger.debug('Found {} {} objects in DB'.format(len(model_objects), model_name))
        return model_objects


############################


class SmartLDAPSearcher:
    def __init__(self, ldap_config):
        self.ldap_config = ldap_config
        # Setup a few other config items
        self.page_size = self.ldap_config.get('page_size', 500)
        self.bind_user = self.ldap_config.get('bind_user', None)
        self.bind_password = self.ldap_config.get('bind_password', None)
        pooling_strategy = self.ldap_config.get('pooling_strategy', 'ROUND_ROBIN')
        if pooling_strategy not in ldap3.POOLING_STRATEGIES:
            raise ImproperlyConfigured('LDAP_CONFIG.pooling_strategy must be one of {}'.format(ldap3.POOLING_STRATEGIES))
        self.server_pool = ldap3.ServerPool(None, pooling_strategy)
        logger.debug('Created new LDAP Server Pool with pooling strategy: {}'.format(pooling_strategy))
        try:
            server_defns = self.ldap_config.get('servers')
        except AttributeError:
            raise ImproperlyConfigured('ldap_config.servers must be defined and must contain at least one server')
        for server_defn in server_defns:
            self.server_pool.add(self._defn_to_server(server_defn))

    def _defn_to_server(self, defn):
        '''Turn a settings file server definition into a ldap3 server object'''
        try:
            address = defn.get('address')
        except AttributeError:
            raise ImproperlyConfigured('Server definition must contain an address')
        port = defn.get('port', 389)
        use_ssl = defn.get('use_ssl', False)
        timeout = defn.get('timeout', 30)
        get_info = defn.get('get_schema', ldap3.SCHEMA)
        return ldap3.Server(address, port=port, use_ssl=use_ssl, connect_timeout=timeout, get_info=get_info)

    def get_connection(self):
        if not hasattr(self, '_connection'):
            self._connection = ldap3.Connection(self.server_pool, user=self.bind_user, password=self.bind_password, client_strategy=ldap3.SYNC, auto_bind=ldap3.AUTO_BIND_NO_TLS)
        return self._connection

    def search(self, base, filter, scope, attributes):
        '''Perform a paged search but return all of the results in one hit'''
        logger.debug('SmartLDAPSearcher.search called with base={}, filter={}, scope={} and attributes={}'.format(str(base), str(filter), str(scope), str(attributes)))
        connection = self.get_connection()
        connection.search(search_base=base, search_filter=filter, search_scope=scope, attributes=attributes, paged_size=self.page_size, paged_cookie=None)
        logger.debug('Connection.search.response is: {}'.format(connection.response))

        results = connection.response
        if len(connection.response) > self.page_size:
            cookie = connection.result['controls']['1.2.840.113556.1.4.319']['value']['cookie']
            while cookie:
                connection.search(search_base=base, search_filter=filter, search_scope=ldap3.SEARCH_SCOPE_WHOLE_SUBTREE, attributes=attributes, paged_size=self.page_size, paged_cookie=cookie)
                results += connection.response
                cookie = connection.result['controls']['1.2.840.113556.1.4.319']['value']['cookie']
        return results

    def get(self, dn, attributes=[]):
        '''Return the object referenced by the given dn or return None'''
        # break the dn down and get a base from it
        search_base = ','.join(dn.split(',')[1:])
        connection = self.get_connection()
        connection.search(search_base=search_base, search_filter='(distinguishedName={})'.format(dn), search_scope=ldap3.SEARCH_SCOPE_SINGLE_LEVEL, attributes=attributes)
        results = connection.response
        if len(results) > 1:
            raise MultipleLDAPResultsReturned()
        elif len(results) == 0:
            return None
        else:
            return results[0]


class UnableToApplyValueMapError(Exception):
    pass


class MissingLdapField(Exception):
    pass


class SyncError(Exception):
    pass


class MultipleLDAPResultsReturned(Exception):
    pass
