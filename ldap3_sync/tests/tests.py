# Unit Tests...
from django.test import TestCase

from ldap3_sync.utils import Synchronizer, DePagingLDAPSearch, LDAPConnectionFactory

import mock

import ldap3

from ldap3_sync.models import LDAPSyncRecord

from models import TestDjangoModel

from ldap3_sync.utils import NOTHING, SUSPEND, DELETE

from django.core.exceptions import ImproperlyConfigured

import os

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


class TestSynchronizer(TestCase):  # noqa
    def setUp(self):
        # Unconfigured Synchronizer
        self.uc_s = Synchronizer() 

    def test_ldap_objects_raises_notimplemented(self):
        self.assertRaises(NotImplementedError, lambda: self.uc_s.ldap_objects)

    def test_django_objects_raises_notimplemented(self):
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

    def test_add_unsaved_model(self):
        class A:
            pass
        fake_unsaved_model = A()
        self.uc_s.add_unsaved_model(fake_unsaved_model)
        self.assertEqual(len(self.uc_s.unsaved_models_v), 1)
        self.assertEqual([fake_unsaved_model], self.uc_s.unsaved_models_v)


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


class FakeLDAPConnectionFactory(LDAPConnectionFactory):
    def __init__(self, test_config):
        self.test_config = test_config
        super(FakeLDAPConnectionFactory, self).__init__()

    def _get_config(self):
        return self.test_config


class TestLDAPConnectionFactory(TestCase):
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

        # This is kind of wrong because it is testing the internal state of the ldap3 connection object
        # What I am really trying to test is that the values passed in are actually being set, ie the factory works
        self.assertEqual(c['connection']['user'], connection.user)
        self.assertEqual(c['connection']['password'], connection.password)
        self.assertEqual(c['connection']['auto_bind'], connection.auto_bind)
        self.assertEqual(c['connection']['version'], connection.version)
        self.assertEqual(c['connection']['authentication'], connection.authentication)
        self.assertEqual(c['connection']['client_strategy'], connection.strategy_type)
        self.assertEqual(c['connection']['auto_referrals'], connection.auto_referrals)
        self.assertEqual(c['connection']['sasl_mechanism'], connection.sasl_mechanism)
        self.assertEqual(c['connection']['read_only'], connection.read_only)
        self.assertEqual(c['connection']['lazy'], connection.lazy)
        self.assertEqual(c['connection']['check_names'], connection.check_names)
        self.assertEqual(c['connection']['raise_exceptions'], connection.raise_exceptions)
        self.assertEqual(c['connection']['pool_name'], connection.pool_name)
        self.assertEqual(c['connection']['pool_size'], connection.pool_size)
        self.assertEqual(c['connection']['pool_lifetime'], connection.pool_lifetime)
        self.assertEqual(c['connection']['fast_decoder'], connection.fast_decoder)
        self.assertEqual(c['connection']['receive_timeout'], connection.receive_timeout)
        self.assertEqual(c['connection']['return_empty_attributes'], connection.empty_attributes)

        server_pool = connection.server_pool
        self.assertEqual(c['pool']['active'], server_pool.active)
        self.assertEqual(c['pool']['pool_strategy'], server_pool.strategy)
        self.assertEqual(c['pool']['exhaust'], server_pool.exhaust)

        servers = server_pool.servers
        server_configs = dict([(s['host'], s) for s in c['servers']])
        for server in servers:
            config = server_configs[server.host]
            self.assertEqual(config['port'], server.port)
            self.assertEqual(config['use_ssl'], server.ssl)
            self.assertEqual(config['get_info'], server.get_info)
            self.assertEqual(config['mode'], server.mode)
            self.assertEqual(config['connect_timeout'], server.connect_timeout)









