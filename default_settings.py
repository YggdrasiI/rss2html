#!/usr/bin/python3
# -*- coding: utf-8 -*-

from feed import Feed

# Default settings
# Put changes of these variables into settings.py!
HOST = "localhost"  # "" allows access from everywhere....
PORT = 8888
CACHE_EXPIRE_TIME_S = 600
MAX_FEED_BYTE_SIZE = 10E6
FAVORITES = [
    Feed("example", "http://www.deutschlandfunk.de/podcast-das-war-der-tag.803.de.podcast",
         "Example Feed (&lt;channel&gt;&lt;title&gt;-value, optional)"),
]

# Some podcast feeds uses very long <content:encoded>-Tags
# This could cause issues during the rendering of the page (freezed browser
# window, high memory usage, etc …)
# This variable define a limit where the content of above tag will be ignored.
CONTENT_FULL_LEN_THRESH = 100000
