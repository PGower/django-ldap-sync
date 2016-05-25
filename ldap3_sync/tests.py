# Unit Tests...
from django.test import TestCase

from ldap3_sync.utils import Synchronizer

import mock


class TestSynchronizer_ldap_objects(TestCase):  # noqa
    def test_ldap_objects_raises_notimplemented(self):
        s = Synchronizer()
        self.assertRaises(NotImplemented, s.ldap_objects)
