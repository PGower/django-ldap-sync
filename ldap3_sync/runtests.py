#!/usr/bin/env python
import os
import sys

from coverage import Coverage

import django
from django.conf import settings
from django.test.utils import get_runner


BASE_PATH = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE_PATH, '../'))

if __name__ == "__main__":
    os.environ['DJANGO_SETTINGS_MODULE'] = 'tests.test_settings'
    django.setup()
    TestRunner = get_runner(settings)
    test_runner = TestRunner()
    cov = Coverage(config_file=os.path.join(BASE_PATH, 'tests/.coveragerc'),
                   source=[BASE_PATH],
                   omit=[os.path.join(BASE_PATH, 'tests/*')])
    cov.start()
    failures = test_runner.run_tests(["tests"])
    cov.stop()
    cov.html_report(directory=os.path.join(BASE_PATH, 'tests/coverage_report/'))
    sys.exit(bool(failures))
