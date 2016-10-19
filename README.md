#django-ldap3-sync
django-ldap3-sync is a fork of [django-ldap-sync](https://github.com/jbittel/django-ldap-sync) originally created by Jason Bittel.
django-ldap3-sync introduces the following features:

 - Uses the [ldap3 library](https://github.com/cannatag/ldap3) for ldap communication. ldap3 is pure python and python 3 compatible.
 - Can synchronize group membership directly out of the LDAP directory.
 - Can manage deletion of groups / users in the directory by suspending or deleting those objects in Django.
 - Will update existing Django users groups if information changes in the directory.
 - Paged LDAP searches
 - LDAP Server Pools

django-ldap3-sync provides a Django management command that synchronizes LDAP
users and groups from an authoritative server. It performs a one-way
synchronization that creates and/or updates the local Django users and groups. It can also optionally delete or suspend users or groups that are no longer present in the directory.

This synchronization is performed each time the management command is run and
can be fired manually on demand, via an automatic cron script or as a periodic
`Celery` task.

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

4. Configure the required `settings`.

5. Run the synchronization management command::

      `manage.py syncldap`

For more information on configuration see the documentation below.


----------

##Configuration
**User Synchronization Configuration Items**

***LDAP_SYNC_USER_FILTER***  
Default: `(objectClass=user)`  
The filter used to retrieve users from the directory. Must be in standard LDAP filter syntax as per [RFC2254](http://www.ietf.org/rfc/rfc2254.txt?number=2254)

***LDAP_SYNC_USER_BASE***  
Default: The value of `LDAP_SYNC_BASE`  
The distinguished name of the container to base the search for users in.

***LDAP_SYNC_USER_ATTRIBUTES***  
Default: **No Default -- Required Item**  
A dictionary of key value pairs where the keys are the names of ldap fields and the values are the names of corresponding django model fields. New users will be created with these fields populated and existing users will have these fields updated. *This dictionary must map the Django User model username field to an LDAP object field.*

***LDAP_SYNC_USER_DEFAULT_ATTRIBUTES***
Default: `{}`  
A dictionary of default values for the given user attributes --keys are attributes. If a certain user does not have an attribute, use the one defined in this dictionary.

***LDAP_SYNC_USER_EXEMPT_FROM_SYNC***  
Default: `[]`  
A list of usernames corresponding to Django users who should be excluded from the sync. Useful for Administrative users who do not have a corresponding user in the directory.

***LDAP_SYNC_USER_REMOVAL_ACTION***  
Default: `NOTHING`  
The action to take when a user no longer exists in the directory. Possible values are `NOTHING`, `SUSPEND` and `DELETE`. Note that the `SUSPEND` option uses the Django user models is_active field and sets it to False.

***LDAP_SYNC_USER_SET_UNUSABLE_PASSWORD***  
Default: `True`  
If true this uses the django method set_unusable_password on all newly created users. Useful where django authentication will not be used.

***LDAP_SYNC_USERS***  
Default: `True`  
Controls whether users should be synchronized from the directory.

**Group Synchronization Configuration Items**  

***LDAP_SYNC_GROUP_FILTER***  
Default: `(objectClass=group)`  
The filter used to retrieve groups from the directory. Must be in standard LDAP filter syntax as per [RFC2254](http://www.ietf.org/rfc/rfc2254.txt?number=2254)

***LDAP_SYNC_GROUP_BASE***  
Default: The value of `LDAP_SYNC_BASE`  
The distinguished name of the container to base the search for groups in.

***LDAP_SYNC_GROUP_ATTRIBUTES***  
Default: **No Default -- Required Item**  
A dictionary of key value pairs where the keys are the names of LDAP fields and the values are the names of corresponding Django model fields. New groups will be created with these fields populated and existing users will have these fields updated.

***LDAP_SYNC_GROUP_DEFAULT_ATTRIBUTES***
Default: `{}`  
A dictionary of default values for the given group attributes --keys are attributes. If a certain group does not have an attribute, use the one defined in this dictionary.

***LDAP_SYNC_GROUP_REMOVAL_ACTION***  
Default: `NOTHING`  
The action to take when a group no longer exists in the directory. Possible values are `NOTHING` and `DELETE`.

***LDAP_SYNC_GROUP_EXEMPT_FROM_SYNC***  
Default: `[]`  
A list of group names of Django groups that should be excluded from the sync.

***LDAP_SYNC_GROUPS***  
Default: `True`  
Controls wether groups should be synchronized.

**Membership Synchronization Configuration Items**  

***LDAP_SYNC_GROUP_MEMBERSHIP***  
Default: `True`  
Controls wether groups will be synchronized from the directory.

***LDAP_SYNC_GROUP_MEMBERSHIP_FILTER***  
Default: `(&(objectClass=group)(member={user_dn}))`  
The filter used to retrieve the groups that a user belongs to. `{user_dn}` will be replaced with the distinguished name of the user.

**LDAP Server Options**  

***LDAP_CONFIG***  
Default: **No Default -- Required Item**  
Configuration item used to configure the server pool. `LDAP_CONFIG` can contain the following keys:

 - **page_size**  
	Default: `500`  
	The page size for searches using this server pool.  
 - **bind_user**  
    Default: `None`  
    The distinguished name of the user to bind to the directory with.  
 - **bind_password**  
   Default: `None`  
   The password of the user to bind to the directory with.  
 - **pooling_strategy**  
   Default: `ROUND_ROBIN`  
   The strategy to use when the pool contains multiple servers. See ldap3 documentation at      https://ldap3.readthedocs.org/en/latest/servers.html#server-pool for more information. Can be   `FIRST`, `ROUND_ROBIN` or `RANDOM`.  
 - **servers**  
Default: `None`  
A list of dictionaries each one containing configuration information for a server. Possible server configuration keys are:  
	 - **address**  
		Default: **No Default -- Required Item**  
		Either the IP address or FQDN of the directory server.  
	 - **use_ssl**  
		Default: `False`  
		Use SSL with this conntection.  
	 - **port**  
	   Default: `389`  
	   The port to use with this server.  
	 - **timeout**  
		Default: `30`  
		Connection timeout with this server.  
	 - **get_schema**  
		Default: `SCHEMA`  
	Determines which schema information to retrieve from the server. At a minimum this should be SCHEMA so that values retrieved from the directory are coerced to proper python types.  


servers:
    - host: 'string' - Required
      port: int
      use_ssl: Bool
      allowed_referral_hosts: list of tuples (see LDAP3 docs)
      get_info: constants from ldap3 package
      mode: constants from ldap3 package
      tls: this needs more thought
      formater: dict
      connect_timeout: int
pool:
    active: boolean / number
    exhaust: boolean / number
    strategy: constants from ldap3 package

connection:
    server: will be provided
    user: string
    password: string
    auto_bind: constants from ldap3 package
    version: int
    authentication: constants from ldap3 package
    client_strategy: constants
    auto_referrals: boolean
    sasl_mechanism: constants
    sasl_credential: an object
    collect_usage: ???
    read_only: boolean
    lazy: boolean
    check_names: boolean
    raise_exceptions: boolean
    pool_name: string
    pool_size: int
    pool_lifetime: int
    fast_decoder: boolean
    recieve_timeout: int
    return_empty_attributes: boolean




