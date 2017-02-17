#!/usr/bin/env python

try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup

from ldap3_sync import __version__ as version

long_description = 'Please see the documentation at the `project page <https://github.com/PGower/django-ldap3-sync>`_ .'

packages = [
    'ldap3_sync',
    'ldap3_sync.management',
    'ldap3_sync.management.commands',
]

package_data = {
    '': ['LICENSE', 'README.md'],
}

# with open('README.md') as f:
#     readme = f.read()

setup(
    name='django-ldap3-sync',
    version=version,
    description='A Django application for synchronizing LDAP users, groups and group membership. (Forked from django-ldap-sync).',
    long_description=long_description,
    author='Paul Gower',
    author_email='p.gower@gmail.com',
    url='https://github.com/PGower/django-ldap3-sync',
    download_url='https://github.com/PGower/django-ldap3-sync/releases',
    package_dir={'ldap3-sync': 'ldap3-sync'},
    packages=packages,
    package_data=package_data,
    license='BSD',
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Environment :: Web Environment',
        'Programming Language :: Python',
        'Framework :: Django',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        'Operating System :: OS Independent',
        'Topic :: System :: Systems Administration :: Authentication/Directory',
        'Topic :: Software Development :: Libraries :: Python Modules',
    ],
    keywords=['django', 'ldap', 'active directory', 'synchronize', 'sync'],
    install_requires=['ldap3 >= 0.9.7.4', 'petname >= 1.12', 'petl', 'petl_ldap3', 'petl_django'],
)
