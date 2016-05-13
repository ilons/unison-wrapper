#!/usr/bin/python
# coding=utf-8
import sys
import shutil
import os
import pwd
import subprocess


# Exit codes:
# 0:     Script executed with no errors
# 1:     Unison: Some files were skipped, but all file transfers were successful.
# 2:     Unison: Non-fatal failures occurred during file transfer.
# 3:     Unison: A fatal error occurred, or the execution was interrupted.
# 11:    Could not determine console user
# 12:    User not allowed to run sync
# 13:    Sync target path does not exist
# 14:    Invalid Unison target config
# 15:    Could not find configuration file
# 16:    Insufficient permissions to modify file
# 99:    Unknown script error


class WrapperException(Exception):
    exit_code = 99

    def __init__(self, message, exit_code=None, *args):
        super(WrapperException, self).__init__(message, *args)
        if exit_code:
            self.exit_code = exit_code
        elif isinstance(self, UnknownRunningUserException):
            self.exit_code = 11
        elif isinstance(self, UserSyncNotAllowedException):
            self.exit_code = 12
        elif isinstance(self, MissingSyncTargetException):
            self.exit_code = 13
        elif isinstance(self, ConfigurationException):
            self.exit_code = 14
        elif isinstance(self, ConfigurationNotFoundException):
            self.exit_code = 15
        elif isinstance(self, InsufficientFilePermissions):
            self.exit_code = 16


class UnisonException(WrapperException):
    pass


class UnisonSyncException(UnisonException):
    pass


class UnknownRunningUserException(WrapperException):
    pass


class UserSyncNotAllowedException(WrapperException):
    pass


class MissingSyncTargetException(WrapperException):
    pass


class ConfigurationException(WrapperException):
    pass


class InvalidUnisonTargetException(ConfigurationException):
    pass


class ConfigurationNotFoundException(ConfigurationException):
    pass


class InsufficientFilePermissions(ConfigurationException):
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
    lstat = os.lstat("/dev/console")
    user_stat = (unicode(pwd.getpwuid(lstat.st_uid).pw_name), lstat.st_uid, lstat.st_gid)

    if user_stat[0] in ['', 'loginwindow', None, u'']:
        raise UnknownRunningUserException('Could not determine running user, got: {name} ({uid})'.format(
            name=user_stat[0],
            uid=user_stat[1],
        ))
    return user_stat


def unison_sync(user, target):
    unison_cmd = subprocess.check_output(['which', 'unison']).strip('\n')

    if not valid_sync_target(target):
        raise InvalidUnisonTargetException('Not a valid sync target: {}'.format(target))

    config_path = create_user_config(username=user, target=target)

    try:
        return subprocess.check_output([unison_cmd, target] + UNISON_EXTRA_ARGS, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as call_error:
        move_user_config(config_path=config_path, extension='failed')
        raise UnisonSyncException(
            message='Unison `{command}` returned error: \n{error}'.format(
                command=call_error.cmd,
                error=call_error.output
            ),
            exit_code=call_error.returncode,
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

    try:
        # First delete old files
        remove_old_user_config(config_path=config_path)

        # Open target config file and write merged config to it, replace {USER} with actual username
        with open(config_path, 'w') as user_config:
            for file_path in [shared_template_path, target_template_path]:
                with open(file_path, 'r') as template_config:
                    for config_line in template_config:
                        # noinspection PyUnresolvedReferences
                        if '{USER}' in config_line:
                            config_line = config_line.format(USER=username)
                        user_config.write(config_line)
    except IOError as io_error:
        if io_error.errno == 2:
            raise ConfigurationNotFoundException(
                'Could not find configuration file for target {}: {}'.format(target, io_error.filename)
            )
        elif io_error.errno == 13:
            raise InsufficientFilePermissions(
                'Not allowed to modify file for target {}: {}'.format(target, io_error.filename)
            )
        raise

    return config_path


def move_user_config(config_path, extension):
    # change extension on config file
    new_config_path = config_path.replace(
        '.{ext}'.format(ext=CONFIG_EXTENSION),
        '.{new_ext}'.format(new_ext=extension),
    )
    shutil.move(config_path, new_config_path)
    return new_config_path


def remove_old_user_config(config_path):
    base_path = os.path.split(config_path)
    for key in os.listdir(base_path[0]):
        if os.path.isfile(key) and key.endswith(os.path.extsep + CONFIG_EXTENSION):
            os.remove(key)


def main():
    user_name, user_id, user_gid = get_current_user_stat()

    if not valid_sync_user(uid=user_id, name=user_name):
        raise UserSyncNotAllowedException(
            'Sync should not run for user: {name} ({uid})'.format(name=user_name, uid=user_id)
        )

    # This should preferably be done based on the actual target in the configs written.
    sync_target = SYNC_TARGET_PATH.format(USER=user_name)
    if not os.path.isdir(sync_target):
        raise MissingSyncTargetException('Target sync directory does not exist: {}'.format(sync_target))

    for target in iter(TEMPLATE_CONFIG_TARGETS):
        print('Running sync for {}'.format(target))
        unison_sync(user=user_name, target=target)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        if not hasattr(e, 'exit_code'):
            e.exit_code = 99
        print(e)
        sys.exit(e.exit_code)
