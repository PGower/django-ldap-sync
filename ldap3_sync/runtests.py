#!/usr/bin/env python
import os
import sys

BASE_PATH = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE_PATH, '../'))
print sys.path

import django
from django.conf import settings
from django.test.utils import get_runner

if __name__ == "__main__":
    os.environ['DJANGO_SETTINGS_MODULE'] = 'tests.test_settings'
    django.setup()
    TestRunner = get_runner(settings)
    test_runner = TestRunner()
    failures = test_runner.run_tests(["tests"])
    sys.exit(bool(failures))
