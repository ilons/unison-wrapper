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


class DataCollectionException(Exception):
    pass


class ConfigurationException(Exception):
    pass


class ConfigurationNotFoundException(ConfigurationException):
    pass


class InvalidUnisonTargetException(ConfigurationException):
    pass


# Absolute configuration path
# {USER} will be replaced with username for currently logged in user
USER_CONFIG_PATH = os.path.sep + os.path.join('Users', '{USER}', 'Library', 'Application Support', 'Unison')
TEMPLATE_CONFIG_PATH = os.path.sep + os.path.join('Library', 'TT', 'Config', 'Unison')

# Target sync directory, this directory must exists.
SYNC_TARGET_PATH = os.path.sep + os.path.join('Volumes', '{USER}')

# Override config for testing purpose
# noinspection PyRedeclaration
# TEMPLATE_CONFIG_PATH = os.path.join('TT', 'Config', 'Unison')

# Extra arguments to pass to Unison
UNISON_EXTRA_ARGS = [
    '-silent',
]

# Exit codes:
# 0:     Script executed with no errors
# 1 - 3: Unison exit codes
# 11:    User not allowed to run sync
# 12:    Sync target path does not exist
# 13:    Invalid Unison target config
# 14:    Could not find configuration file

# Non-fatal exit codes from unison that the script should ignore
IGNORED_EXIT_CODES = [
    # 0   # successful synchronization; everything is up-to-date now.
    # 1,  # some files were skipped, but all file transfers were successful.
    # 2,  # non-fatal failures occurred during file transfer.
    # 3   # a fatal error occurred, or the execution was interrupted.
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
PROHIBITED_SYNC_USERS = [
    'root',
]


def get_current_user_stat():
    try:
        # Try to use PyObjC's SystemConfiguration module if available
        # This module are able to get us the proper console user, even when running as a hook
        # noinspection PyUnresolvedReferences
        import SystemConfiguration
        user_stat = SystemConfiguration.SCDynamicStoreCopyConsoleUser(None, None, None) or (None, None, None)
    except ImportError:
        lstat = os.lstat("/dev/console")
        user_stat = (unicode(pwd.getpwuid(lstat.st_uid).pw_name), lstat.st_uid, lstat.st_gid)

    if user_stat[0] in ['', 'loginwindow', None, u'']:
        raise DataCollectionException('Could not get currently running user, got: {name} ({uid})'.format(
            name=user_stat[0],
            uid=user_stat[1],
        ))
    return user_stat


def unison_sync(user, target):
    unison_cmd = subprocess.check_output(['which', 'unison']).strip('\n')

    if not valid_sync_target(target):
        raise InvalidUnisonTargetException('Not a valid sync target: {}'.format(target))

    try:
        config_path = create_user_config(username=user, target=target)
        print('Created config: {path}'.format(path=config_path))
    except IOError as e:
        if e.errno == 2:
            raise ConfigurationNotFoundException(
                'Could not find configuration file for target {}: {}'.format(target, e.filename)
            )
        raise e

    try:
        return subprocess.check_output([unison_cmd, target] + UNISON_EXTRA_ARGS, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        raise UnisonSyncException(
            message='Unison `{command}` returned error: \n{error}'.format(command=e.cmd, error=e.output),
            exit_code=e.returncode,
        )


def valid_sync_target(target):
    return target in TEMPLATE_CONFIG_TARGETS


def valid_sync_user(uid, name):
    if uid < LOWEST_ALLOWED_USER_ID:
        return False
    elif name in PROHIBITED_SYNC_USERS:
        return False
    return True


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
                for config_line in template_config:
                    if '{USER}' in config_line:
                        config_line = config_line.format(USER=username)
                    user_config.write(config_line)

    return config_path


def main():
    user_name, user_id, user_gid = get_current_user_stat()

    if not valid_sync_user(uid=user_id, name=user_name):
        print('Sync should not run for user: {user} ({id})'.format(user=user_name, id=user_id))
        sys.exit(11)

    # This should preferably be done based on the actual target in the configs written.
    sync_target = SYNC_TARGET_PATH.format(USER=user_name)
    if not os.path.isdir(sync_target):
        print('Target sync directory does not exist: {}'.format(sync_target))
        sys.exit(12)

    for target in iter(TEMPLATE_CONFIG_TARGETS):
        try:
            print('Running sync for {}'.format(target))
            unison_sync(user=user_name, target=target)
        except UnisonException as e:
            if e.exit_code not in IGNORED_EXIT_CODES:
                print('Unison exited with error {code}, aborting sync:\n{msg}'.format(code=e.exit_code, msg=e.message))
                sys.exit(e.exit_code)
            pass
        except InvalidUnisonTargetException:
            print('Did not provide a valid Unison target config: {}'.format(target))
            sys.exit(13)
        except ConfigurationException as e:
            print(e.message)
            sys.exit(14)

if __name__ == "__main__":
    main()

