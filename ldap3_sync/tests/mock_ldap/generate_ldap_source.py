import os
import sys

from ldap3 import ALL, ALL_ATTRIBUTES, Connection, Server

BASE_PATH = os.path.dirname(os.path.abspath(__file__))

sys.path.append(BASE_PATH)

from secrets import REAL_SERVER, REAL_USER, REAL_PASSWORD, BASE_OU # noqa


if __name__ == '__main__':
    # Retrieve server info and schema from a real server
    server = Server(REAL_SERVER, get_info=ALL)
    connection = Connection(server, REAL_USER, REAL_PASSWORD, auto_bind=True)

    # Store server info and schema to json files
    server.info.to_file(os.path.join(BASE_PATH, 'server_info.json'))
    server.schema.to_file(os.path.join(BASE_PATH, 'server_schema.json'))

    # Read entries from a portion of the DIT from real server and store them in a json file
    if connection.search(BASE_OU, '(objectclass=*)', attributes=ALL_ATTRIBUTES):
        json = connection.response_to_json(raw=True, checked_attributes=False)
        with open(os.path.join(BASE_PATH, 'server_entries.json'), 'w') as f:
            f.write(json)

    # Close the connection to the real server
    connection.unbind()
