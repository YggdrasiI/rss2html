#!/usr/bin/python3
# -*- coding: utf-8 -*-

# Import this file only in default_settings.py

import sys
import os
from importlib import import_module
from glob import glob

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
            os.mkdir(config_dir)
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
                            "favorites_{}.py".format(user))


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
        # settings = main_globals.get("settings")
        pass

    load_default_favs(main_globals)


def load_default_favs(main_globals):
    # Read FAVORITES from favorites.py and HISTORY from history.py
    # Use as fallback values from settings.py.
    config_dir = get_config_folder()
    if config_dir not in sys.path:
        sys.path.insert(0, config_dir)

    settings = main_globals.get("settings")

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

    if not hasattr(main_globals.get("settings"), "USER_FAVORITES"):
        main_globals.get("settings").USER_FAVORITES = {}

    prefix = "favorites_"
    suffix = ".py"
    user_favs = glob(os.path.join(
        config_dir, "{}*{}".format(prefix, suffix)))
    for f in user_favs:
        user_module_name = os.path.basename(f)[:-len(suffix)]
        username = user_module_name[len(prefix):]
        try:
            user_fav_module = import_module(user_module_name)
            if hasattr(user_fav_module, "FAVORITES"):
                main_globals.get("settings").USER_FAVORITES[
                    username] = user_fav_module.FAVORITES

        except ImportError as e:
            print("Import of '{}' failed: {}".format(f, e))

    # Same for histories
    if not hasattr(main_globals.get("settings"), "USER_HISTORY"):
        main_globals.get("settings").USER_HISTORY = {
            "default": [] }

    prefix = "history_"
    suffix = ".py"
    user_hists = glob(os.path.join(
        config_dir, "{}*{}".format(prefix, suffix)))
    for h in user_hists:
        user_module_name = os.path.basename(h)[:-len(suffix)]
        username = user_module_name[len(prefix):]
        try:
            user_hist_module = import_module(user_module_name)
            if hasattr(user_hist_module, "HISTORY"):
                main_globals.get("settings").USER_HISTORY[
                    username] = user_hist_module.HISTORY

        except ImportError as e:
            print("Import of '{}' failed: {}".format(h, e))


