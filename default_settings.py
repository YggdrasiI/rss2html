#!/usr/bin/python3
# -*- coding: utf-8 -*-

from feed import Feed

# Default settings
# Put changes of these variables into settings.py!

FAVORITES = [
    Feed("example", "http://www.deutschlandfunk.de/podcast-das-war-der-tag.803.de.podcast",
         "Example Feed (&lt;channel&gt;&lt;title&gt;-value, optional)"),
]

HOST = "localhost"  # "" allows access from everywhere....
PORT = 8888
GUI_LANG = "en" 

# User defined css-file.
#             Available: "dark.css"
CSS_STYLE = None

CACHE_EXPIRE_TIME_S = 600
MAX_FEED_BYTE_SIZE = 1E7
ALLOWED_FILE_EXTENSIONS = [".css", ".png", ".jpg", ".svg"]

# If <desciption> and <content:encoded>-field both set, use second entry for 
# 'detail page'
DETAIL_PAGE = True

# Show opening/close animation
DETAIL_PAGE_ANIMATED = False

# Limits on latest feed entries if > -1
CONTENT_MAX_ENTRIES = -1

# Some podcast feeds uses very long <content:encoded>-Tags
# This could cause issues during the rendering of the page (freezed browser
# window, high memory usage, etc …)
# This variable define a limit where the content of above tag will be ignored.
CONTENT_FULL_LEN_THRESH = 1E5

# ==========================================================
DOWNLOAD_DIR = "$HOME/Downloads"

ACTIONS = [
    {"title": "play in browser", "icon": None,
     "can_handle": None,
     "handler": None,
    },
    {"title": "download", "icon": None,
     "can_handle": "can_download",
     "handler": "download",
    }
]

# ==========================================================
# Helper function for proper loading of settings. Sketch for proper reading
# of settings:
#    import default_settings as settings
#    settings.load_config(globals())
#
from settings_helper import get_config_folder, load_config, get_settings_path
