# Unit Tests...
from django.test import TestCase

from ldap3_sync.utils import Synchronizer

import mock

from ldap3_sync.models import LDAPSyncRecord

from models import TestDjangoModel

from ldap3_sync.utils import NOTHING, SUSPEND, DELETE

from ldap3 import Server, Connection


class TestSynchronizer(TestCase):  # noqa
    def setUp(self):
        # Setup a mock LDAP server for testing purposes
        self.mock_ldap_server = Server.from_definition('mock_server', 'mock_ldap/server_info.json', 'mock_ldap/server_schema.json')
        self.mock_ldap_connection = Connection(server, user='cn=my_user,ou=test,o=lab', password='my_password', client_strategy=ldap3.MOCK_SYNC)
        self.mock_ldap_connection.strategy.entries_from_json('mock_ldap/server_entries.json')

        # Unconfigured Synchronizer
        self.uc_s = Synchronizer() 

        # Configured Synchronizer
        ldap_objects = 
        self.c_s = Synchronizer()

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







class TestSmartLDAPSearcher(TestCase):
    # Remeber that LDAP3 has a mocking strategy
    pass
