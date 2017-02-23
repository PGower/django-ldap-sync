#django-ldap3-sync
django-ldap3-sync is a Django app for synchornizing LDAP objects to Django models.
V1.0.0 is an almost complete rewrite which removes the focus on using management commands to sync data and stores all configuration in models.
More documentation and a celery task for automation are incoming.

##Quickstart
1. Install the application::

      `pip install django-ldap3-sync`

2. Append it to the installed apps::

      ```
      INSTALLED_APPS = (
          # ...
          'ldap3_sync',
      )
      ```

3. Run `python manage.py migrate` in the django project directory.

4. Configure the LDAP servers and at least one LDAPSyncJob in the Django Admin interface.

5. Run the synchronization management command with the name of the created LDAPSyncJob::

      `manage.py syncldap name.of.syncjob`
