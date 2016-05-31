# Unit Tests...
from django.test import TestCase
from ldap3_sync.utils import Synchronizer, DePagingLDAPSearch, LDAPConnectionFactory, DjangoLDAPConnectionFactory, YAMLLDAPConnectionFactory
import mock
import ldap3
import ldap3_sync
from ldap3_sync.models import LDAPSyncRecord
from models import TestDjangoModel
from django.conf import settings
from ldap3_sync.utils import NOTHING, SUSPEND, DELETE
from django.core.exceptions import ImproperlyConfigured
import os
import yaml

BASE_PATH = os.path.dirname(os.path.abspath(__file__))


def mock_ldap_connection():
    mock_ldap_server = ldap3.Server.from_definition('mock_server',
                                                    os.path.join(BASE_PATH, 'mock_ldap/server_info.json'),
                                                    os.path.join(BASE_PATH, 'mock_ldap/server_schema.json'))
    mock_ldap_connection = ldap3.Connection(mock_ldap_server,
                                            user='cn=my_user,ou=test,o=lab',
                                            password='my_password',
                                            client_strategy=ldap3.MOCK_SYNC,
                                            auto_bind=ldap3.AUTO_BIND_NO_TLS)
    mock_ldap_connection.strategy.entries_from_json(os.path.join(BASE_PATH, 'mock_ldap/server_entries.json'))
    return mock_ldap_connection


class TestUnconfiguredSynchronizer(TestCase):  # noqa
    def setUp(self):
        # Unconfigured Synchronizer
        self.uc_s = Synchronizer() 

    def test_ldap_objects_raises_notimplemented(self):
        self.assertRaises(NotImplementedError, lambda: self.uc_s.ldap_objects)

    def test_django_objects_raises_notimplemented(self):
        '''This will raise NotImplementedError due to the call to self.django_object_model, 
        if django_object_model is set, it will try to work around not having this data'''
        self.assertRaises(NotImplementedError, lambda: self.uc_s.django_objects)

    def test_attribute_map_raises_notimplemented(self):
        self.assertRaises(NotImplementedError, lambda: self.uc_s.attribute_map)

    def test_django_object_model_raises_notimplemented(self):
        self.assertRaises(NotImplementedError, lambda: self.uc_s.django_object_model)

    def test_django_object_model_name_raises_notimplemented(self):
        # When django_object_model is not defined then this will raise NotImplementedError
        self.assertRaises(NotImplementedError, lambda: self.uc_s.django_object_model_name)

    def test_unique_name_field_raises_notimplemented(self):
        self.assertRaises(NotImplementedError, lambda: self.uc_s.unique_name_field)

    def test_ldap_sync_model_returns_ldapsyncrecord(self):
        ldap_sync_model = self.uc_s.ldap_sync_model
        self.assertIs(ldap_sync_model, LDAPSyncRecord)

    def test_default_removal_action_is_nothing(self):
        removal_action = self.uc_s.removal_action
        self.assertEqual(removal_action, NOTHING)

    def test_unsaved_models_is_empty(self):
        self.assertEqual([], self.uc_s.unsaved_models)

    def test_removal_action_raises_notimplemented(self):
        '''When the removal action is not specified then it should return NOTHING'''
        self.assertEqual(self.uc_s.removal_action, NOTHING)

    def test_add_unsaved_model(self):
        class A:
            pass
        fake_unsaved_model = A()
        self.uc_s.add_unsaved_model(fake_unsaved_model)
        self.assertEqual(len(self.uc_s.unsaved_models_v), 1)
        self.assertEqual([fake_unsaved_model], self.uc_s.unsaved_models_v)


class TestConfiguredSynchronizer(TestCase):
    def setUp(self):
        # Configured Synchronizer
        connection = mock_ldap_connection()
        connection.bind()
        search_base = 'dc=example,dc=com'
        search_filter = '(objectClass=person)'
        depager = DePagingLDAPSearch(connection)
        self.ldap_objects = depager.search(search_base, search_filter, attributes=ldap3.ALL_ATTRIBUTES)

        self.unique_name_field = 'employeeID'

        model_data = [
            {'first_name': 'Bob', 'last_name': 'Brown', 'email': 'bbrown@example.org', 'employeeID': 123456},
            {'first_name': 'Rod', 'last_name': 'Stewart', 'email': 'rstewart@example.org', 'employeeID': 234567},
            {'first_name': 'Iggy', 'last_name': 'Pop', 'email': 'ipop@example.org', 'employeeID': 345678},
            {'first_name': 'Keith', 'last_name': 'Richards', 'email': 'krichard@example.org', 'employeeID': 456789},
            {'first_name': 'Bob', 'last_name': 'Marley', 'email': 'bmarley@example.org', 'employeeID': 4567890},
            {'first_name': 'James', 'last_name': 'Brown', 'email': 'jbrown@example.org', 'employeeID': 5678901},
            {'first_name': 'Tom', 'last_name': 'Jones', 'email': 'tjones@example.org', 'employeeID': 6789012},
            {'first_name': 'Otis', 'last_name': 'Redding', 'email': 'oredding@example.org', 'employeeID': 7890123},
        ]
        for md in model_data:
            tdm = TestDjangoModel(**md)
            tdm.save()
        self.django_objects = dict([(getattr(m, self.unique_name_field), m) for m in TestDjangoModel.objects.all()])

        self.attribute_map = {
            'givenName': 'first_name',
            'sn': 'last_name',
            'email': 'email',
            'employeeID': 'employeeID'
        }

        self.exempt_unique_names = [345678, 7890123]

        self.removal_action = SUSPEND

        self.bulk_create_chunk_size = 35

        self.c_s = Synchronizer(ldap_objects=self.ldap_objects,
                                django_objects=self.django_objects,
                                attribute_map=self.attribute_map,
                                django_object_model=TestDjangoModel,
                                unique_name_field=self.unique_name_field,
                                exempt_unique_names=self.exempt_unique_names,
                                removal_action=self.removal_action,
                                bulk_create_chunk_size=self.bulk_create_chunk_size)

    def test_ldap_objects_returns_value(self):
        self.assertEqual(self.c_s.ldap_objects, self.ldap_objects)

    def test_django_objects_returns_value(self):
        self.assertEqual(self.c_s.django_objects, self.django_objects)

    def test_attribute_map_returns_value(self):
        self.assertEqual(self.c_s.attribute_map, self.attribute_map)

    def test_django_object_model_return_value(self):
        self.assertEqual(self.c_s.django_object_model, TestDjangoModel)

    def test_unique_name_field_return_value(self):
        self.assertEqual(self.c_s.unique_name_field, self.unique_name_field)

    def test_django_object_model_name_return_value(self):
        self.assertEqual(self.c_s.django_object_model_name, TestDjangoModel.__name__)

    def test_exempt_unique_names_return_value(self):
        self.assertEqual(self.c_s.exempt_unique_names, self.exempt_unique_names)

    def test_removal_action_return_value(self):
        self.assertEqual(self.c_s.removal_action, self.removal_action)

    def test_bulk_create_chunk_size_return_value(self):
        self.assertEqual(self.c_s.bulk_create_chunk_size, self.bulk_create_chunk_size)

    def test_django_objects_returns_all_when_no_explicit_objects_passed(self):
        '''When no django objects are passed in, use the django_object_model to extract all models'''
        s = Synchronizer(ldap_objects=self.ldap_objects,
                         attribute_map=self.attribute_map,
                         django_object_model=TestDjangoModel,
                         unique_name_field=self.unique_name_field,
                         exempt_unique_names=self.exempt_unique_names,
                         removal_action=self.removal_action,
                         bulk_create_chunk_size=self.bulk_create_chunk_size)
        expected_value = dict([(getattr(m, self.unique_name_field), m) for m in TestDjangoModel.objects.all()])
        self.assertEqual(s.django_objects, expected_value)

    def test_django_objects_returns_all_when_queryset_passed(self):
        s = Synchronizer(ldap_objects=self.ldap_objects,
                         django_objects=TestDjangoModel.objects.filter(first_name__icontains='e').all(),
                         attribute_map=self.attribute_map,
                         django_object_model=TestDjangoModel,
                         unique_name_field=self.unique_name_field,
                         exempt_unique_names=self.exempt_unique_names,
                         removal_action=self.removal_action,
                         bulk_create_chunk_size=self.bulk_create_chunk_size)
        expected_value = dict([(getattr(m, self.unique_name_field), m) for m in TestDjangoModel.objects.filter(first_name__icontains='e').all()])
        self.assertEqual(s.django_objects, expected_value)

    def test_exempt_unique_names(self):
        self.assertTrue(self.c_s.exempt_unique_name(self.exempt_unique_names[0]))
        self.assertFalse(self.c_s.exempt_unique_name('NOTEXEMPT'))
        self.assertFalse(self.c_s.exempt_unique_name(0000000))

    def test_uniquename_dn_map(self):
        self.c_s.add_uniquename_dn_map('unique_name1', 'distinguished_name1')
        self.c_s.add_uniquename_dn_map('unique_name2', 'distinguished_name2')
        self.c_s.add_uniquename_dn_map('unique_name3', 'distinguished_name3')
        self.assertTrue(self.c_s.uniquename_in_map('unique_name1'))
        self.assertFalse(self.c_s.uniquename_in_map('unique_name4'))
        self.assertTrue(self.c_s.dn_in_map('distinguished_name1'))
        self.assertFalse(self.c_s.dn_in_map('distinguished_name4'))

    def test_will_model_change(self):
        model_data = {'first_name': 'Bob', 'last_name': 'Brown', 'email': 'bbrown@example.org', 'employeeID': 123456}
        model = TestDjangoModel(**model_data)
        self.assertFalse(self.c_s.will_model_change({'first_name': 'Bob', 'last_name': 'Brown', 'email': 'bbrown@example.org', 'employeeID': 123456}, model))
        self.assertFalse(self.c_s.will_model_change({'first_name': u'Bob', 'last_name': u'Brown', 'email': u'bbrown@example.org', 'employeeID': 123456}, model))
        self.assertTrue(self.c_s.will_model_change({'first_name': 'bob', 'last_name': u'brown', 'email': u'BBROWN@example.org', 'employeeID': 123456}, model))
        self.assertTrue(self.c_s.will_model_change({'first_name': 'Daniel', 'last_name': u'Radcliff', 'email': u'dradcliff@example.org', 'employeeID': 123456}, model))


class TestSearchDePager(TestCase):
    def setUp(self):
        self.connection = mock_ldap_connection()
        self.connection.bind()
        self.search_base = 'dc=example,dc=com'
        self.search_filter = '(objectClass=person)'

    def test_when_page_size_is_lt_1(self):
        self.assertRaises(AssertionError, lambda: DePagingLDAPSearch(self.connection, paged_size=0))
        self.assertRaises(AssertionError, lambda: DePagingLDAPSearch(self.connection, paged_size=-10))

    def test_search_big_page(self):
        depager = DePagingLDAPSearch(self.connection, paged_size=500)
        results = depager.search(self.search_base, self.search_filter, attributes=ldap3.ALL_ATTRIBUTES)
        self.assertEqual(len(results), 14)

    def test_search_small_page(self):
        depager = DePagingLDAPSearch(self.connection, paged_size=5)
        results = depager.search(self.search_base, self.search_filter, attributes=ldap3.ALL_ATTRIBUTES)
        self.assertEqual(len(results), 14)
        # This is currently broken because the mock ldap server does not support paging

    def test_remove_paged_cookie(self):
        depager = DePagingLDAPSearch(self.connection, paged_size=500)
        results = depager.search(self.search_base, self.search_filter, attributes=ldap3.ALL_ATTRIBUTES, paged_cookie='THIS_IS_NOT_A_REAL_COOKIE')
        self.assertEqual(len(results), 14)

    def test_search_paged_size(self):
        depager = DePagingLDAPSearch(self.connection)
        results = depager.search(self.search_base, self.search_filter, attributes=ldap3.ALL_ATTRIBUTES, paged_size=500)
        self.assertEqual(len(results), 14)


class FakeLDAPConnectionFactory(LDAPConnectionFactory):
    def __init__(self, test_config):
        self.test_config = test_config
        super(FakeLDAPConnectionFactory, self).__init__()

    def _get_config(self):
        return self.test_config


class LDAPConnectionFactoryTester(object):
    def run_all_of_the_tests(self, config, connection):
        # This is kind of wrong because it is testing the internal state of the ldap3 connection object
        # What I am really trying to test is that the values passed in are actually being set, ie the factory works
        self.assertEqual(config['connection']['user'], connection.user)
        self.assertEqual(config['connection']['password'], connection.password)
        self.assertEqual(config['connection']['auto_bind'], connection.auto_bind)
        self.assertEqual(config['connection']['version'], connection.version)
        self.assertEqual(config['connection']['authentication'], connection.authentication)
        self.assertEqual(config['connection']['client_strategy'], connection.strategy_type)
        self.assertEqual(config['connection']['auto_referrals'], connection.auto_referrals)
        self.assertEqual(config['connection']['sasl_mechanism'], connection.sasl_mechanism)
        self.assertEqual(config['connection']['read_only'], connection.read_only)
        self.assertEqual(config['connection']['lazy'], connection.lazy)
        self.assertEqual(config['connection']['check_names'], connection.check_names)
        self.assertEqual(config['connection']['raise_exceptions'], connection.raise_exceptions)
        self.assertEqual(config['connection']['pool_name'], connection.pool_name)
        self.assertEqual(config['connection']['pool_size'], connection.pool_size)
        self.assertEqual(config['connection']['pool_lifetime'], connection.pool_lifetime)
        self.assertEqual(config['connection']['fast_decoder'], connection.fast_decoder)
        self.assertEqual(config['connection']['receive_timeout'], connection.receive_timeout)
        self.assertEqual(config['connection']['return_empty_attributes'], connection.empty_attributes)

        server_pool = connection.server_pool
        self.assertEqual(config['pool']['active'], server_pool.active)
        self.assertEqual(config['pool']['pool_strategy'], server_pool.strategy)
        self.assertEqual(config['pool']['exhaust'], server_pool.exhaust)

        servers = server_pool.servers
        server_configs = dict([(s['host'], s) for s in config['servers']])
        for server in servers:
            sconfig = server_configs[server.host]
            self.assertEqual(sconfig['port'], server.port)
            self.assertEqual(sconfig['use_ssl'], server.ssl)
            self.assertEqual(sconfig['get_info'], server.get_info)
            self.assertEqual(sconfig['mode'], server.mode)
            self.assertEqual(sconfig['connect_timeout'], server.connect_timeout)


class TestLDAPConnectionFactory(TestCase, LDAPConnectionFactoryTester):
    def test_minimal_config(self):
        c = {
            'servers': [
                {
                    'host': 'testdc.example.org',
                }
            ],
        }
        factory = FakeLDAPConnectionFactory(test_config=c)
        connection = factory.get_connection()
        self.assertEqual(connection.server.host, 'testdc.example.org')

    def test_broken_config(self):
        c = {
            'connection': {
                'user': 'cn=admin,dc=example,dc=com',
                'password': 'SecretPassword'
            }
        }
        factory = FakeLDAPConnectionFactory(test_config=c)
        with self.assertRaises(ImproperlyConfigured):
            factory.get_connection()

    def test_full_config(self):
        c = {
            'servers': [
                {
                    'host': 'testdc1.example.org',
                    'port': 123,
                    'use_ssl': True,
                    'allowed_referral_hosts': [('testdc2.example.org', True)],
                    'get_info': 'ALL',
                    'mode': 'IP_SYSTEM_DEFAULT',
                    'connect_timeout': 60
                },
                {
                    'host': 'testdc2.example.org',
                    'port': 345,
                    'use_ssl': False,
                    'allowed_referral_hosts': [('testdc1.example.org', False)],
                    'get_info': 'OFFLINE_AD_2012_R2',
                    'mode': 'IP_V4_PREFERRED',
                    'connect_timeout': 120
                }
            ],
            'pool': {
                'active': True,
                'exhaust': True,
                'pool_strategy': 'RANDOM',
            },
            'connection': {
                'user': 'cn=adminuser,dc=example,dc=com',
                'password': 'secret',
                'auto_bind': 'AUTO_BIND_NO_TLS',
                'version': 3,
                'authentication': 'SIMPLE',
                'client_strategy': 'SYNC',
                'auto_referrals': True,
                'sasl_mechanism': 'EXTERNAL',
                'read_only': True,
                'lazy': True,
                'check_names': True,
                'raise_exceptions': False,
                'pool_name': 'Test Pool',
                'pool_size': 10,
                'pool_lifetime': 60,
                'fast_decoder': True,
                'receive_timeout': 15,
                'return_empty_attributes': False
            }
        }
        factory = FakeLDAPConnectionFactory(test_config=c)
        connection = factory.get_connection()

        self.run_all_of_the_tests(c, connection)

    def test_get_config(self):
        with self.assertRaises(NotImplementedError):
            a = LDAPConnectionFactory()


class TestDjangoConnectionFactory(TestCase, LDAPConnectionFactoryTester):
    def test_django_connection_factory(self):
        factory = DjangoLDAPConnectionFactory()
        connection = factory.get_connection()

        config = getattr(settings, 'LDAP_CONFIG')

        self.run_all_of_the_tests(config, connection)


class TestYAMLConnectionFactory(TestCase, LDAPConnectionFactoryTester):
    def test_yaml_connection_factory_from_string(self):
        '''Passing a string file path to the YAML connection factory'''
        factory = YAMLLDAPConnectionFactory(config_file=os.path.join(BASE_PATH, 'ldap_connection.yml'))
        connection = factory.get_connection()

        self.run_all_of_the_tests(factory.config, connection)

    def test_yaml_connection_factory_from_file(self):
        with open(os.path.join(BASE_PATH, 'ldap_connection.yml')) as f:
            factory = YAMLLDAPConnectionFactory(config_file=f)
        connection = factory.get_connection()

        self.run_all_of_the_tests(factory.config, connection)


class TestSynchronization(TestCase):
    def setUp(self):
        # Configured Synchronizer
        connection = mock_ldap_connection()
        connection.bind()
        search_base = 'dc=example,dc=com'
        search_filter = '(objectClass=person)'
        depager = DePagingLDAPSearch(connection)
        self.ldap_objects = depager.search(search_base, search_filter, attributes=ldap3.ALL_ATTRIBUTES)

        self.unique_name_field = 'employeeID'

        model_data = [
            {'first_name': 'Bob', 'last_name': 'Brown', 'email': 'bbrown@example.org', 'employeeID': 123456},
            {'first_name': 'Rod', 'last_name': 'Stewart', 'email': 'rstewart@example.org', 'employeeID': 234567},
            {'first_name': 'Iggy', 'last_name': 'Pop', 'email': 'ipop@example.org', 'employeeID': 345678},
            {'first_name': 'Keith', 'last_name': 'Richards', 'email': 'krichard@example.org', 'employeeID': 456789},
            {'first_name': 'Bob', 'last_name': 'Marley', 'email': 'bmarley@example.org', 'employeeID': 4567890},
            {'first_name': 'James', 'last_name': 'Brown', 'email': 'jbrown@example.org', 'employeeID': 5678901},
            {'first_name': 'Tom', 'last_name': 'Jones', 'email': 'tjones@example.org', 'employeeID': 6789012},
            {'first_name': 'Otis', 'last_name': 'Redding', 'email': 'oredding@example.org', 'employeeID': 7890123},
        ]
        for md in model_data:
            tdm = TestDjangoModel(**md)
            tdm.save()
        self.django_objects = dict([(getattr(m, self.unique_name_field), m) for m in TestDjangoModel.objects.all()])

        self.attribute_map = {
            'givenName': 'first_name',
            'sn': 'last_name',
            'email': 'email',
            'employeeID': 'employeeID'
        }

        self.exempt_unique_names = [345678, 7890123]

        self.removal_action = SUSPEND

        self.bulk_create_chunk_size = 35

        self.s = Synchronizer(ldap_objects=self.ldap_objects,
                              django_objects=self.django_objects,
                              attribute_map=self.attribute_map,
                              django_object_model=TestDjangoModel,
                              unique_name_field=self.unique_name_field,
                              exempt_unique_names=self.exempt_unique_names,
                              removal_action=self.removal_action,
                              bulk_create_chunk_size=self.bulk_create_chunk_size)

    def test_synchorinzation(self):
        self.s.sync()

