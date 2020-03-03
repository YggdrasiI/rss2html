#!/usr/bin/python3
# -*- coding: utf-8 -*-

from gettext import gettext as _

from feed import Feed
import actions

# Default settings
# Put overrides of these variables into settings.py!

HOST = "localhost"  # "" allows access from everywhere....
PORT = 8888
SSL = True          # HTTPS

GUI_LANG = "en"

# ==========================================================
DOWNLOAD_DIR = "$HOME/Downloads"

# ==========================================================
# LOGIN_TYPE
#
# Possible values:
#                  None: Do not use session cookies.
#         "single_user": Auto-login every user as "default"
#                        Attention, in this case, everyone can
#                        trigger all actions, defined below.
#                        Use None if you do not want this.
#               "users": Use USER-dict, below.
#                 "pam": Allow login for every account on this
#                        machine. Do NOT use this without SSL!
LOGIN_TYPE = None

# User list, used for LOGIN_TYPE == "list"
USERS = {
    "example_user1": {"password": ""},
    "example_user2": {"hash":  # sha1-hash
                      "da39a3ee5e6b4b0d3255bfef95601890afd80709"},
}

# ==========================================================
# Logging level of each component can be controlled in 'logging.conf'
# Set LOGLEVEL variable to overwrite level globally.
LOGLEVEL = "DEBUG"

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

# Default css-file.
#             Available: "default.css", "dark.css"
#
# User can override this value by the cookie 'style_css'
CSS_STYLE = None  # None => default.css

# ==========================================================
ACTION_SECRET = None  # None => Random value at each start.

## Actions for media files in feeds.
"""
If you want define more actions add following to your
local setttings.py:

from default_settings import ACTIONS

def can_action_name(url, settings):
    return True

def action_name(url, settings):
    return True

ACTIONS.update({
    "my_action" : {
        # Action for this url
        "handler": lambda url: print(url),
        # True if your action should be possible for this url
        "check": lambda url: return True,
        "title": "Description",
        "icon": "icons/gnome_download.png",
    },
})
"""

ACTIONS = {
    "download" : {
        "handler": actions.download_with_wget,
        "check": actions.can_download,
        "title": _('Download file'),
        "icon": "icons/gnome_download.png",
    },
    "play" : {
        "handler": actions.play_with_mimeopen,
        "check": actions.can_play,
        "title": _('Play file with external program'),
        "icon": "icons/gnome_multimedia.png",
    },
}

# Default favorites.
# Will copied if users logs in first time and will
# be displayd if user is not logged in.
#
# Update 'favorites.py' to override this value.
FAVORITES = [
    Feed("example",
         "http://www.deutschlandfunk.de/" \
         "podcast-das-war-der-tag.803.de.podcast.xml",
         "Example Feed"),
]

# New approach distinct between users.
USER_FAVORITES = {
    "default": FAVORITES,  # username in LoginFreeSession-case
}

# ==========================================================
# Helper function for proper loading of settings. Sketch for proper reading
# of settings:
#    import default_settings as settings
#    settings.load_config(globals())
#
from settings_helper import get_config_folder, \
        load_config, load_default_favs, load_users, \
        get_favorites_filename, get_history_filename, \
        get_settings_path, get_favorites_path
