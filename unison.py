#!/usr/bin/python
# coding=utf-8
import sys

import os
import pwd
import subprocess


class UnisonException(Exception):
    def __init__(self, message, exit_code, *args):
        super(UnisonException, self).__init__(message, *args)
        self.exit_code = exit_code


class UnisonSyncException(UnisonException):
    pass


class ConfigurationException(Exception):
    pass


class InvalidSyncTargetException(ConfigurationException):
    pass


# Absolute configuration path
# {USER} will be replaced with username for currently logged in user
USER_CONFIG_PATH = os.path.sep + os.path.join('Users', '{USER}', 'Library', 'Application Support', 'Unison')
TEMPLATE_CONFIG_PATH = os.path.sep + os.path.join('Library', 'TT', 'Config', 'Unison')

# Override config for testing purpose
# noinspection PyRedeclaration
# TEMPLATE_CONFIG_PATH = os.path.join('TT', 'Config', 'Unison')

# Extra arguments to pass to Unison
UNISON_EXTRA_ARGS = ['-silent']

# Non-fatal exit codes from unison that the script should ignore
IGNORED_EXIT_CODES = [
    # 0  # successful synchronization; everything is up-to-date now.
    1,  # some files were skipped, but all file transfers were successful.
    2,  # non-fatal failures occurred during file transfer.
    # 3  # a fatal error occurred, or the execution was interrupted.
]

TEMPLATE_EXTENSION = 'prfconfig'
CONFIG_EXTENSION = 'prf'

# Unison sync targets, this is the name of the config file without extension
TEMPLATE_CONFIG_TARGETS = [
    'Dokument',
    'Skrivbord',
    'Bibliotek',
]
TEMPLATE_TARGETS_PATH = 'Targets'
TEMPLATE_SHARED_CONFIG = 'Common'

# Lowest numerical ID on the system that sync should be run for
LOWEST_ALLOWED_USER_ID = 501
# Explicit list of users not to run sync for
PROHIBITED_SYNC_USERS = ['root']


def get_current_user_stat():
    return os.lstat("/dev/console")


def unison_sync(user, target):
    unison_cmd = subprocess.check_output(['which', 'unison']).strip('\n')

    if not valid_sync_target(target):
        raise InvalidSyncTargetException('Not a valid sync target: {}'.format(target))

    create_user_config(username=user, target=target)

    try:
        output = subprocess.check_output([unison_cmd, target] + UNISON_EXTRA_ARGS, stderr=subprocess.STDOUT)
        return output
    except subprocess.CalledProcessError, e:
        print(e)
        raise UnisonSyncException(message=e.message, exit_code=e.returncode)


def valid_sync_target(target):
    return target in TEMPLATE_CONFIG_TARGETS


def valid_sync_user(user_id):
    user_name = pwd.getpwuid(user_id)
    if user_id >= LOWEST_ALLOWED_USER_ID and user_name not in PROHIBITED_SYNC_USERS:
        return True
    return False


def create_user_config(username, target):
    config_base_path = USER_CONFIG_PATH.format(USER=username)
    config_path = os.path.join(
        config_base_path,
        '{name}.{ext}'.format(name=target, ext=CONFIG_EXTENSION),
    )

    # Shared template config for all targets
    shared_template_path = os.path.join(
        TEMPLATE_CONFIG_PATH,
        '{name}.{ext}'.format(name=TEMPLATE_SHARED_CONFIG, ext=TEMPLATE_EXTENSION),
    )
    # Target specific template config
    target_template_path = os.path.join(
        TEMPLATE_CONFIG_PATH,
        TEMPLATE_TARGETS_PATH,
        '{name}.{ext}'.format(name=target, ext=TEMPLATE_EXTENSION),
    )

    # Automatically create config path
    if not os.path.exists(config_base_path):
        os.mkdir(config_base_path, 0755)

    # Open target config file and write merged config to it, replace {USER} with actual username
    with open(config_path, 'w') as user_config:
        for file_path in [shared_template_path, target_template_path]:
            with open(file_path, 'r') as template_config:
                for template_line in template_config:
                    user_config.write(template_line.format(USER=username))

    return config_path

def main():
    user_stat = get_current_user_stat()
    user_id = user_stat.st_uid
    user_name = pwd.getpwuid(user_id).pw_name

    if not valid_sync_user(user_id):
        print('Sync should not run for user: {user} ({id})'.format(user=user_name, id=user_id))
        sys.exit(0)

    # Still no check that sync target directory actually exists
    # This should be performed for each target, on both root's.

    for target in iter(TEMPLATE_CONFIG_TARGETS):
        try:
            unison_sync(user=user_name, target=target)
        except UnisonException as e:
            if e.exit_code not in IGNORED_EXIT_CODES:
                print('Unison exited with error {code}, aborting sync'.format(code=e.exit_code))
                sys.exit(e.exit_code)
            pass

if __name__ == "__main__":
    main()

