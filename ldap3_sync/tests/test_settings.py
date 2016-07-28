# Settings for Testing

import os

# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEBUG = True

SECRET_KEY = 'fake-key'
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'ldap3_sync',
    'tests',
]

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': os.path.join(BASE_DIR, 'db.sqlite3'),
    }
}

# Trying to keep config similar to the base django settings.
LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_L10N = True

USE_TZ = True


LDAP_CONFIG = {
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


LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'file': {
            'level': 'DEBUG',
            'class': 'logging.FileHandler',
            'filename': os.path.join(BASE_DIR, 'tests/test.log'),
        },
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['file'],
            'level': 'DEBUG',
            'propagate': True,
        },
    },
}