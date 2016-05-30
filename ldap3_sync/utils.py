# Utility Classes / Functions for Synchronization
import logging

from django.conf import settings

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
            raise NotImplementedError
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
            raise NotImplementedError
        return self.attribute_map_v
    attribute_map = property(_attribute_map, 'The attribute map used to extract values from the ldap objects')

    def _django_object_model(self):
        '''Return the model for the django object that is going to be synchronized'''
        if self.django_object_model_v is None:
            raise NotImplementedError
        return self.django_object_model_v
    django_object_model = property(_django_object_model, 'The django object model used in this synchornization')

    def _django_object_model_name(self):
        return self.django_object_model.__name__
    django_object_model_name = property(_django_object_model_name, 'The name of the django object model')

    def _unique_name_field(self):
        '''Return the unique name field '''
        if self.unique_name_field_v is None:
            raise NotImplementedError
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

    def _removal_action(self):
        '''Return 1 of the existing 3 removal actions or return a callable that takes a set of django objects
        that need to be actioned'''
        if self.removal_action_v is None:
            raise NotImplementedError
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
    unsaved_models = property(_unsaved_models, 'A list object containing all of the unsaved django models created by the sync process')

    def add_unsaved_model(self, unsaved_model):
        self.unsaved_models_v.append(unsaved_model)

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

class DePagingLDAPSearch(object):
    '''Given an ldap connection object use it to de-page and return all results from a query. Uses pages in the background to
    overcome any server query limits.'''
    def __init__(self, connection, paged_size=400):
        self.connection = connection
        assert(paged_size > 1)
        self.paged_size = paged_size

    def search(self, search_base, search_filter, **kwargs):
        '''Perform a search and depage the results, takes the same arguments as the ldap3.Connection.search method'''
        if 'paged_size' in kwargs.keys():
            paged_size = kwargs['paged_size']
            del kwargs['paged_size']
        else:
            paged_size = self.paged_size

        if 'paged_cookie' in kwargs.keys():
            del kwargs['paged_cookie']

        self.connection.search(search_base=search_base, search_filter=search_filter, paged_size=paged_size, **kwargs)

        results = self.connection.response
        if len(self.connection.response) > self.paged_size:
            cookie = self.connection.result['controls']['1.2.840.113556.1.4.319']['value']['cookie']
            while cookie:
                self.connection.search(search_base=search_base, search_filter=search_filter, paged_size=paged_size, paged_cookie=cookie, **kwargs)
                results += self.connection.response
                cookie = self.connection.result['controls']['1.2.840.113556.1.4.319']['value']['cookie']
        return results


class LDAPConnectionFactory(object):
    def __init__(self):
        self.config = self._get_config()

    def _get_config(self):
        '''This needs to be reimplemented by the subclass. Get configuration from whichever store you are using
        and pass the configuration as a dictionary of key value pairs (as defined in the readme.md) to the connector
        factory'''
        raise NotImplementedError

    def _translate_string_to_constant(self, config, key):
        try:
            config[key] = getattr(ldap3, config[key])
        except KeyError:
            if key in config:
                del(config[key])

    def _get_servers(self):
        '''Return either a single LDAP3 server object or a ServerPool if multiple servers are defined'''
        servers = []
        if 'servers' not in self.config.keys():
            return None
        for server_config in self.config['servers']:
            try:
                host = server_config['host']
            except KeyError:
                raise ImproperlyConfigured('The host parameter is required for all server definitions')
            del server_config['host']

            self._translate_string_to_constant(server_config, 'get_info')
            self._translate_string_to_constant(server_config, 'mode')

            servers.append(ldap3.Server(host, **server_config))
        if len(servers) == 1:
            return servers[0]
        else:
            if 'pool' in self.config.keys():
                pool_config = self.config['pool']
                try:
                    pool_config['strategy'] = getattr(ldap3, pool_config['strategy'])
                except KeyError:
                    pass
                return ServerPool(servers, **pool_config)
            else:
                return ServerPool(servers)

    def get_connection(self):
        '''Use the config returned in _get_config and create a new LDAP connection'''
        connection_config = self.config['connection']
        servers = self._get_servers()
        if servers is None:
            if 'server' not in connection_config:
                raise ImproperlyConfigured('Either a set of servers must be defined or a URI / IP / Hostname must be passed in the connection definition')
        else:
            # Servers configured in the servers section overrides any servers configured in the connection
            connection_config['server'] = servers

        self._translate_string_to_constant(connection_config, 'auto_bind')
        self._translate_string_to_constant(connection_config, 'authentication')
        self._translate_string_to_constant(connection_config, 'client_strategy')
        self._translate_string_to_constant(connection_config, 'sasl_mechanism')
        
        return ldap3.Connection(**connection_config)


class DjangoLDAPConnectionFactory(LDAPConnectionFactory):
    def _get_config(self):
        # Expects config to be stored in a key called LDAP_CONFIG
        return getattr(settings, 'LDAP_CONFIG')


class YAMLLDAPConnectionFactory(LDAPConnectionFactory):
    def __init__(self, config_file):
        self.config_file = config_file
        super(YAMLLDAPConnectionFactory, self).__init__()

    def _get_config(self):
        import yaml
        with open(self.config_file, 'r') as f:
            config = yaml.load(f)
        return config


class UnableToApplyValueMapError(Exception):
    pass


class MissingLdapField(Exception):
    pass


class SyncError(Exception):
    pass


class MultipleLDAPResultsReturned(Exception):
    pass
