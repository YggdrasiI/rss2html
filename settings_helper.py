#!/usr/bin/python3
# -*- coding: utf-8 -*-

# Import this file only in default_settings.py

import sys
import os
from importlib import import_module
from types import ModuleType
from glob import glob
from random import randint

from session import LoginType
from validators import validate_favorites, ValidatorException

import logging
logger = logging.getLogger(__name__)

_CONFIG_PATH = None
_CONFIG_FILE = None

def get_config_folder():
    """ Return desired path depending of os.

    Config folder is used for:
        settings.py
        favorites.py
        history.py
        favorites_{username}.py
        history_{username}.py
    """

    if _CONFIG_PATH:
        return _CONFIG_PATH

    if os.uname()[0].lower().startswith("win"):
        root_dir = os.getenv('APPDATA')
    else:
        root_dir = os.getenv('XDK_CONFIG_HOME')
        if not root_dir:
            root_dir = os.path.join(os.getenv('HOME'), '.config')

    config_dir = os.path.join(root_dir, "rss2html")

    if not os.path.isdir(config_dir):
        try:
            os.makedirs(config_dir)  # os.mkdir(config_dir)
        except:
            config_dir = "."

    globals()["_CONFIG_PATH"] = config_dir
    globals()["_CONFIG_FILE"] = os.path.join(_CONFIG_PATH, "settings.py")
    return config_dir


def get_settings_path():
    if _CONFIG_FILE:
        return _CONFIG_FILE

    get_config_folder()
    return _CONFIG_FILE


def get_favorites_path(user=None):
    return os.path.join(get_config_folder(),
                        get_favorites_filename(user))



def get_history_path(user=None):
    return os.path.join(get_config_folder(),
                        get_history_filename(user))


def get_favorites_filename(user=None):
    if user:
        return "favorites_{}.py".format(user)
    else:
        return "favorites.py"


def get_history_filename(user=None):
    if user:
        return "history_{}.py".format(user)
    else:
        return "history.py"



def load_config(main_globals):
    config_dir = get_config_folder()
    logger.info("Load config from {}".format(config_dir))

    if config_dir not in sys.path:
        sys.path.insert(0, config_dir)

    try:
        import settings

        # If settings.py not contains a variable name
        # add the default value from default_settings
        vars_set = vars(settings)
        vars_default_set = vars(sys.modules["default_settings"])
        for s in vars_default_set.keys():
            if not s.startswith("__"):
                vars_set[s] = vars_set.get(s, vars_default_set[s])

        # Replace 'default_settings' module
        # Note that here settings is a local variable
        # and != main_globals["settings"]
        main_globals["settings"] = settings
    except ImportError:
        logger.warn("No 'settings.py' found. Loading default values.")
        import default_settings as settings
        pass

    # Generate secret token if none is given
    if settings.ACTION_SECRET is None:
        settings.ACTION_SECRET = str(randint(0, 1E15))
        logger.warn("settings.ACTION_SECRET not defined. Using random value.")

    # Check LOGIN_TYPE and convert to Enum
    try:
        settings._LOGIN_TYPE = LoginType(settings.LOGIN_TYPE)
    except ValueError:
        logger.warn("Invalid value ({}) for settings.LOGIN_TYPE. "
                    "Valid values are: {}. Fallback on None.".format(
                        settings.LOGIN_TYPE,
                        ", ".join(['"{}"'.format(v.value) if v.value else "None"
                                   for (k,v) in LoginType.__members__.items()])
                    ))
        settings.LOGIN_TYPE = None
        settings._LOGIN_TYPE = LoginType(None)

    load_default_favs(main_globals)

def load_default_favs(main_globals):
    # Read FAVORITES from favorites.py and HISTORY from history.py
    # Use as fallback values from settings.py.
    config_dir = get_config_folder()
    if config_dir not in sys.path:
        sys.path.insert(0, config_dir)

    settings = main_globals.get("settings")

    # 0. Validate files
    for module_name in ["favorites", "history"]:
        try:
            validate_favorites(module_name)
        except ValidatorException as e:
            logger.info("Validation of '{}' failed!\n" \
                    "\tError: {}".format(module_name,e))
            settings.FAVORITES = []
            settings.HISTORY = []
            return

    # 1. favorites
    try:
        from favorites import FAVORITES
    except ImportError:
        FAVORITES = settings.FAVORITES if \
                hasattr(settings, "FAVORITES") else []
    finally:
        settings.FAVORITES = FAVORITES

    # 2. history
    try:
        from history import HISTORY
    except ImportError:
        HISTORY = []
    finally:
        settings.HISTORY = HISTORY


def load_users(main_globals):
    config_dir = get_config_folder()
    if config_dir not in sys.path:
        sys.path.insert(0, config_dir)

    def _update(filename, prefix, suffix, attrname, feed_dict):

        user_module_name = os.path.basename(filename)[:-len(suffix)]
        username = user_module_name[len(prefix):]

        # Validate that module has expected content
        try:
            validate_favorites(user_module_name)
        except ValidatorException as e:
            logger.info("Validation of '{}' failed!\n" \
                    "\tError: {}".format(f,e))

        # Unload module if file was already read
        try:
            del sys.modules[user_module_name]
        except KeyError:
            pass

        try:
            user_fav_module = import_module(user_module_name)
            if hasattr(user_fav_module, attrname):
                feed_dict[username] = getattr(user_fav_module, attrname)

        except ImportError as e:
            logger.warn("Import of '{}' failed: {}".format(filename, e))

    # 1. Favs
    if not hasattr(main_globals.get("settings"), "USER_FAVORITES"):
        main_globals.get("settings").USER_FAVORITES = {}  # {"default": [] }

    prefix = "favorites_"
    suffix = ".py"
    user_favs = glob(os.path.join(
        config_dir, "{}*{}".format(prefix, suffix)))
    for f in user_favs:
        _update(f, prefix, suffix, "FAVORITES",
                main_globals.get("settings").USER_FAVORITES)

    # 2. Same for histories
    if not hasattr(main_globals.get("settings"), "USER_HISTORY"):
        main_globals.get("settings").USER_HISTORY = {}  # {"default": [] }

    prefix = "history_"
    suffix = ".py"
    user_hists = glob(os.path.join(
        config_dir, "{}*{}".format(prefix, suffix)))
    for h in user_hists:
        _update(h, prefix, suffix, "HISTORY",
                main_globals.get("settings").USER_HISTORY)


def update_submodules(main_globals):
    # Use main_globals-settings submodule in all other
    # submodules, too.
    #
    # Useful in modules with following statement:
    # import default_settings as settings

    settings = main_globals["settings"]
    modules_done = []  # To omit infinite loops due recursion

    def _r(m):
        if m in modules_done:
            return

        modules_done.append(m)
        if hasattr(m, "__dict__"):
            if "settings" in m.__dict__:
                if isinstance(m.settings, ModuleType):
                    logger.debug("Replace settings module in '{}'".\
                                 format(m.__name__))
                    m.settings = settings
                else:
                    logger.warn("Found variable named 'settings' in module" \
                                "'{}'. This name should ne be used.".\
                                 format(m.__name__))

            for s in m.__dict__.values():
                if isinstance(s, ModuleType):
                    _r(s)

    for v in main_globals.values():
        if isinstance(v, ModuleType):
            _r(v)


# Generator for flat list over all (loaded) feeds.
# settings-arg is a little bit clumsy...
def all_feeds(settings, *extra_feed_lists):
    def _foo(*lists):
        for l in lists:
            for feed in l:
                yield feed

    return _foo(
            settings.FAVORITES, settings.HISTORY,
            *settings.USER_FAVORITES.values(),
            *settings.USER_HISTORY.values(),
            *extra_feed_lists)
