#!/usr/bin/python3
# -*- coding: utf-8 -*-

# Import this file only in default_settings.py

import sys
import os

_CONFIG_PATH = None
_CONFIG_FILE = None

def get_config_folder():
    """ Return desired path depending of os.

    Config folder is used for:
        settings.py
        history.py
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

    except ImportError:
        pass

    try:
        from history import HISTORY
    except ImportError:
        HISTORY = []
    finally:
        main_globals["HISTORY"] = HISTORY

    # Replace 'default_settings' module
    # Note that here settings is a local variable and != main_globals["settings"]
    main_globals["settings"] = settings



