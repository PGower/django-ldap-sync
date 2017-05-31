"""django-ldap3-sync utility classes including the main synchornizer."""
import petl
from petl_ldap3 import fromldap
from petl_django import fromdjango
import logging

try:
    from StringIO import StringIO
except ImportError:
    from io import StringIO

from django.utils.module_loading import import_string
from datetime import datetime
from .models import LDAPSyncJob, LDAPSyncJobLog

from django.conf import settings


class Synchronizer(object):
    """A base synchornizer class."""
    def __init__(self, sync_job, logger):
        self.sync_job = sync_job
        self.logger = logger

    def setup(self):
        pass

    def synchronize(self):
        raise NotImplemented

    def teardown(self):
        pass

    def build_queryset(self):
        """Build a queryset using the target_django_model and LdapSyncQuerysetFilter data."""
        model_class = self.sync_job.target_django_model.model_class()
        filters = [(i.predicate, i.value) for i in self.sync_job.filters.all()]
        if len(filters) > 0:
            return model_class.objects.filter(**dict(filters)).all()
        else:
            return model_class.objects.all()

    def build_attribute_map_for_ldap(self):
        """Build a dictionary of attribute name pairs mapping from django to ldap names."""
        return dict([(i.model_attribute_name, i.ldap_attribute_name) for i in self.sync_job.attributes.all()])

    def build_attribute_map_for_django(self):
        """Build a dictionary of attribute name pairs mapping from ldap to django names."""
        return dict([(i.ldap_attribute_name, i.model_attribute_name) for i in self.sync_job.attributes.all()])


class PETLSynchronizer(Synchronizer):
    """A Synchronizer class that uses the PETL library for data manipulation and takes an LDAPSyncJob as a configuration item."""

    @property
    def data_for_create(self):
        if not hasattr(self, '_data_for_create'):
            self._data_for_create = petl.antijoin(self.ldap_data, self.django_data,
                                                  lkey=self.sync_job.ldap_key_attribute,
                                                  rkey=self.sync_job.django_key_attribute)
        return self._data_for_create

    @property
    def data_for_update(self):
        if not hasattr(self, '_data_for_update'):
            self._data_for_update = petl.antijoin(self.ldap_data, self.data_for_create,
                                                  key=self.sync_job.ldap_key_attribute)
        return self._data_for_update

    @property
    def data_for_delete(self):
        if not hasattr(self, '_data_for_delete'):
            self._data_for_delete = petl.antijoin(self.django_data, self.ldap_data,
                                                  lkey=self.sync_job.django_key_attribute,
                                                  rkey=self.sync_job.ldap_key_attribute)
        return self._data_for_delete

    def creation_stage(self):
        """The Creation Stage of the synchonization process."""
        self.logger.debug('Begin generating data for new model creation.')
        try:
            data_for_create = self.data_for_create
        except BaseException as e:
            self.logger.exception('Unable to generate data for new model creation.')
            raise e
        else:
            self.logger.info('Generated data for new model creation.')
            self.logger.debug('{} new models need to be created.'.format(data_for_create.nrows()))

        try:
            self.logger.debug('Renaming LDAP attributes based on the defined attribute map to match the Django attributes.')
            data_for_create = data_for_create.rename(self.build_attribute_map_for_django())
        except BaseException as e:
            self.logger.exception('Unable to rename new model data.')
            raise e

        self.logger.info('Beginning to create new models.')
        new_models_created = 0
        new_models_failed = 0
        for i in data_for_create.dicts():
            # If I do this one at a time it is slower but lets me catch errors etc.
            try:
                self.logger.info('Attempting to create new {}.'.format(self.model_class))
                self.logger.debug('Using model data: {}'.format(str(i)))
                new_model = self.model_class(**i)
                new_model.save()
            except BaseException:
                self.logger.exception('Unable to create new {}.'.format(self.model_class))
                new_models_failed += 1
            else:
                self.logger.debug('Successfully created new {}.'.format(self.model_class))
                new_models_created += 1
        self.logger.debug('Successfully created {} new models.'.format(new_models_created))
        self.logger.debug('Failed creating {} new models.'.format(new_models_failed))

    def update_stage(self):
        """Update Stage of the Synchonization process."""
        self.logger.debug('Begin generating data for existing model updates.')
        try:
            # generate updates. This is the data that exists in both stores and needs to be evaluated for update elligibility.
            # update data should be any ldap data that is not in create. Delete entries will not exist in ldap data.
            data_for_update = self.data_for_update
        except BaseException as e:
            self.logger.exception('Unable to generate data for updates.')
            raise e
        else:
            self.logger.info('Generated data for existing model updates.')
            self.logger.debug('{} candidate models for update.')

        try:
            self.logger.debug('Renaming LDAP attributes based on the defined attribute map to match the Django attributes.')
            data_for_update = data_for_update.rename(self.build_attribute_map_for_django())
        except BaseException as e:
            self.logger.exception('Unable to rename existing model update data.')
            raise e

        self.logger.info('Beginning to evaluate models for update.')
        updates_applied = 0
        updates_skipped = 0
        updates_failed = 0

        header = data_for_update.header()
        key_attribute = self.sync_job.django_key_attribute

        for i in data_for_update.dicts():
            try:
                key_attribute_value = i[key_attribute]
                existing_model = self.model_class.objects.get(**{key_attribute: key_attribute_value})
                has_updates = False
                for h in header:
                    if i[h] != getattr(existing_model, h, None):
                        setattr(existing_model, h, i[h])
                        has_updates = True
                if has_updates is True:
                    existing_model.save()
                    updates_applied += 1
                    self.logger.debug('Successfully applied updates to model with key attribute value: {}'.format(key_attribute_value))
                else:
                    updates_skipped += 1
                    self.logger.debug('Skipped applying updates to model with key attribute value: {}'.format(key_attribute_value))
            except BaseException:
                self.logger.exception('Unable to apply updates to model with key attribute value: {}'.format(key_attribute_value))
                updates_failed += 1
        self.logger.debug('Successfully applied {} updates.'.format(updates_applied))
        self.logger.debug('Skipped applying {} updates.'.format(updates_skipped))
        self.logger.debug('Failed to apply {} updates.'.format(updates_failed))

    def delete_stage(self):
        """Delete Stage of the Synchonization process."""
        self.logger.debug('Begin generating data for deletion candidates.')

        data_for_delete = self.data_for_delete
        key_attribute = self.sync_job.django_key_attribute

        if self.sync_job.delete_action == 'DELETE':
            delete_action = lambda r: r.delete()  # noqa
        elif self.sync_job.delete_action == 'FUNCTION':
            try:
                delete_action = import_string(self.sync_job.delete_function)
            except ImportError:
                self.logger.exception('Unable to import the configured delete function: {}'.format(self.sync_job.delete_function))

        successful_deletes = 0
        failed_deletes = 0

        for i in data_for_delete.dicts():
            key_attribute_value = i[key_attribute]
            existing_model = self.model_class.objects.get(**{key_attribute: key_attribute_value})
            try:
                delete_action(existing_model)
            except BaseException:
                self.logger.exception('Unable to delete model with key attribute value: {}'.format(key_attribute_value))
                failed_deletes += 1
            else:
                self.logger.debug('Successfully deleted model with key attribute value: {}'.format(key_attribute_value))
                successful_deletes += 1
        self.logger.debug('Successfully deleted {} models.'.format(successful_deletes))
        self.logger.debug('Failed to delete {} models.'.format(failed_deletes))

    def synchronize(self):
        """Perform a synchronization of ldap objects to django models as defined in a LDAPSyncJob."""
        self.logger.info('Begin Synchronization for LDAPSyncJob: {}'.format(self.sync_job.name))

        # Rehydrate the ldap_connection object from the stored configuration
        try:
            self.logger.debug('Rehydrating ldap3.Connection')
            ldap_connection = self.sync_job.ldap_connection.hydrate()
        except BaseException:
            self.logger.exception('Unable to rehydrate the ldap3.Connection.')
            return
        else:
            self.logger.info('Successfully rehydrated ldap3.Connection')
            self.logger.debug('Rehydrated ldap3.Connection: {}'.format(str(ldap_connection)))

        ldap_attributes = set([a.ldap_attribute_name for a in self.sync_job.attributes.all()])
        self.logger.debug('LDAP Attributes to be retrieved: {}'.format(','.join(ldap_attributes)))

        # Search for LDAP objects and return
        try:
            self.logger.debug('Starting to retrieve LDAP entries using ldap3.Connection: {}'.format(str(ldap_connection)))
            self.ldap_data = fromldap(ldap_connection,
                                      self.sync_job.base_ou,
                                      self.sync_job.search_filter,
                                      attributes=ldap_attributes,
                                      scope=self.sync_job.search_scope)
        except BaseException:
            self.logger.exception('Unable to retrieve LDAP entries.')
            return
        else:
            self.logger.info('Successfully Retrieved LDAP data')
            self.logger.debug('Retrieved {} LDAP entries.'.format(self.ldap_data.nrows()))
            self.logger.debug('LDAP headers retrieved: {}'.format(str(self.ldap_data.header())))

        django_attributes = set([i.model_attribute_name for i in self.sync_job.attributes.all()])
        self.logger.debug('Django model attributes to be retrieved: {}'.format(','.join(django_attributes)))

        # collect all of the django models matching the search.
        try:
            self.logger.debug('Starting to retrieve Django models.')
            self.model_class = self.sync_job.target_django_model.model_class()
            self.logger.debug('Using Django Model: {}'.format(self.model_class))
            qs = self.build_queryset()
            self.logger.debug('Using QuerySet: {}'.format(str(qs.query)))

            self.django_data = fromdjango(self.model_class, qs, fields=django_attributes)
        except BaseException:
            self.logger.exception('Unable to retrieve Django models.')
            return
        else:
            self.logger.info('Successfully retrieved Django models.')
            self.logger.debug('Retrieved {} Django models.'.format(self.django_data.nrows()))
            self.logger.debug('Django headers retrieved: {}'.format(str(self.django_data.header())))

        # ==== Create New Models ====
        if self.sync_job.do_create is True:
            try:
                self.creation_stage()
            except BaseException:
                self.logger.exception('Creation Stage Failed. Badly.')
            else:
                self.logger.debug('Creation Stage Finished Succesfully.')
        else:
            self.logger.info('Skipping the Creation Stage.')

        # ==== Update Existing Models ====
        if self.sync_job.do_update is True:
            try:
                self.update_stage()
            except BaseException:
                self.logger.exception('Update Stage Failed. Badly.')
            else:
                self.logger.debug('Update Stage Finished Succesfully.')
        else:
            self.logger.info('Skipping the Update Stage.')

        # ==== Delete Models that do not exist in the LDAP Data ====
        if self.sync_job.do_delete is True:
            try:
                self.delete_stage()
            except BaseException:
                self.logger.exception('Delete Stage Failed. Badly.')
            else:
                self.logger.debug('Delete Stage Finished Succesfully.')
        else:
            self.logger.info('Skipping the Delete Stage.')


class SyncRunner(object):
    """Base abstract sync runner class."""
    def __init__(self, sync_job):
        self.sync_job = sync_job

    def run(self):
        self.logger = self.setup_logging()

        synchronizer_class = import_string(self.sync_job.synchronizer_class)
        synchronizer_instance = synchronizer_class(self.sync_job, self.logger)

        synchronizer_instance.setup()
        synchronizer_instance.synchronize()
        synchronizer_instance.teardown()

        self.teardown_logging()

    def setup_logging(self):
        raise NotImplemented

    def teardown_logging(self):
        raise NotImplemented


class CLISyncRunner(SyncRunner):
    """CLI Runner class. Takes a name instead of a LDAPSyncJob model."""
    def setup_logging(self):
        """Setup a logger that sends everything to the console."""
        logger = logging.getLogger('LDAPSyncJob: {}'.format(self.sync_job.name))
        logger.setLevel(self.sync_job.logging_level)

        console_handler = logging.StreamHandler()
        console_handler.setLevel(self.sync_job.logging_level)

        formatter = logging.Formatter('%(asctime)s:%(name)s:%(levelname)s:: %(message)s')
        console_handler.setFormatter(formatter)

        logger.addHandler(console_handler)

        return logger

    def teardown_logging(self):
        """Perform any teardown actions for the logging system."""
        pass

# https://stackoverflow.com/questions/9534245/python-logging-to-stringio-handler

class BackgroundSyncRunner(SyncRunner):
    """Background runner class."""
    def setup_logging(self):
        """log everything to a variable and store the contents in a LDAPSyncJobLog."""
        self.start = datetime.now()

        self.stream = StringIO()
        self.handler = logging.StreamHandler(self.stream)

        self.formatter = logging.Formatter('%(asctime)s:%(name)s:%(levelname)s:: %(message)s')
        self.handler.setFormatter(self.formatter)

        self.log = logging.getLogger(f'LDAPSyncJob: {self.sync_job.name}')
        self.log.setLevel(self.sync_job.logging_level)

        for handler in self.log.handlers:
            self.log.removeHandler(handler)
        self.log.addHandler(self.handler)        

        return self.log

    def teardown_logging(self):
        end = datetime.now()

        self.handler.flush()
        logging_data = self.stream.getvalue()

        self.stream.truncate(0)
        self.stream.seek(0)

        successful = getattr(self, 'successful', False)

        LDAPSyncJobLog.store_log(self.sync_job, logging_data, self.start, end, successful)

