#!/usr/bin/python3
# -*- coding: utf-8 -*-

import os.path
import re
from urllib.parse import unquote

# For storage
from hashlib import sha1

import logging
logger = logging.getLogger(__name__)

class Feed:
    def __init__(self, name, url, title=None, uid=None):
        self.name = name         # For url pattern /?feed=name
        self.url = unquote(url)  # Normalize into unquoted form
        self.title = title       # Title given by RSS or None
        self._uid = uid           # Unique id generated from above data
        self.items = []
        self.context = {}

    def __repr__(self):
        def escape_str(s):
            return s.replace('\\','\\\\').replace('"', '\\"')

        return 'Feed("{name}", "{url}"{title}{uid})'.format(
            name=escape_str(self.name),
            url=escape_str(self.url),
            title=', title="{}"'.format(escape_str(self.title)) if self.title else "",
            uid=', uid="{}"'.format(self._uid) if self._uid else "",
        )


    def cache_name(self):
        # Return assoziated cache filename
        return self.get_uid()

    def get_uid(self):
        if not self._uid:
            self.gen_uid()

        return self._uid

    def gen_uid(self):
        # Generate id for this feed. Should only be called once for
        # each feed. (The url of a feed can change in the future.)
        #
        # Prefer url as basis and use name, title as fallback
        candidates = [self.url, self.name, self.title]
        for c in candidates:
            if c:
                self._uid = gen_hash(c)
                return

'''
    def add_items(self, items):
        for item in items:
            self.items.append(item)

    def get_item(self, guid=None, relative_id=None):
        if guid:
            for item in self.items:
                if item.guid == guid:
                    return item

        if relative_id:
            try:
                item = self.items[relative_id]
                return item
            except IndexError:
                pass

        return None

    def has_items(self):
        return (len(self.items) > 0)

    def init_from_xml(self, text):
        pass


class Item:
    def __init__(self, enclosures=None, guid=None):
        self.enclosures = enclosures
        self.guid = guid

    def add_enclosures(self, enclosures):
        for enclosure in enclosures:
            self.items.append(enclosure)

    def has_enclosures(self):
        return (len(self.enclosures) > 0)

    def get_enclosure(self, guid=None, url=None):
        match = [e for e in self.enclosures if (e.guid == guid or \
                                        e.url == url)]
        try:
            return match[0]
        except IndexError:
            pass

        return None

class Enclosure:
    def __init__(self, url, guid=None):
        self.url = url
        self.guid = guid if guid else self.url
'''

def get_feed(key, *feed_lists):  # hist_feeds=None):
    """ Search feed in list(s) of Feed-objects.

    Return tuple (feed, list_found_index)
    """
    if key == "":
        return (None, -1)

    for idx in range(len(feed_lists)):
        feeds = feed_lists[idx]
        for f in feeds:
            if key in [f.name, f.title, f.url]:
                return (f, idx)

    #raise ValueError("No feed found for {}".format(key))
    return (None, -1)


def save_history(feeds, folder="", filename="history.py"):
    """ Writes feeds into history.py (or explict given filename)"""

    path = os.path.join(folder, filename)

    logger.debug("Write history file '{1}' with {0} entries.".format(
        len(feeds), filename))
    with open(path, "w") as f:
        f.write("#!/usr/bin/python3\n")
        f.write("# -*- coding: utf-8 -*-\n\n")
        f.write("from rss2html.feed import Feed\n")
        f.write("HISTORY = [\n")
        for feed in feeds:
            f.write("    {},\n".format(feed))
        f.write("]\n")


def clear_history(feedsA, feedsB):
    """ Remove feeds from feedsB if similar entry found in feedsA. """
    found = []
    for feed in feedsB:
        if get_feed(feed.title, feedsA)[0]:
            found.append(feed)

    for feed in found:
        feedsB.remove(feed)


def update_favorites(feeds, folder="", filename="favorites.py"):
    """ Updates FAVORITES variable into favorites.py (or explict given filename)

    Function do not alter other parts of given config file.
    (Note: Previous versions saves favorites directly in settings.py)
    """

    path = os.path.join(folder, filename)

    if not os.path.exists(path):
        config_file_content = """
#!/usr/bin/python3
# -*- coding: utf-8 -*-

from rss2html.feed import Feed

FAVORITES = [
    {__FAVORITES}
]
"""
    else:
        with open(path, "r") as f:
            config_file_content = f.read(-1)
            # Remove content of FAVORITES list
            search = re.search("\nFAVORITES\s*=\s\[[^]]*]",
                                       config_file_content)
            favs_substring = config_file_content[search.start()+1:search.end()]
            # Check if regex search return valid substring.
            try:
                compile(favs_substring, "favs_list", "exec")
            except SyntaxError:
                raise Exception("Abort writing of '{path}'. Search for " \
                                "FAVORITES list failed.".format(path=path))

            # Replace string of current favorites list with dummy.
            config_file_content = config_file_content[:search.start()+1] \
                    + "FAVORITES = [\n    {__FAVORITES}\n]" \
                    + config_file_content[search.end():]

    # Fill in new feed list
    feed_strs = [str(feed) for feed in feeds]
    config_file_content = config_file_content.format(
        __FAVORITES=",\n    ".join(feed_strs) \
        + ",\n" if len(feed_strs) else "")

    logger.debug("Write favorites file '{1}' with {0} entries.".format(
        len(feeds), filename))
    with open(path, "w") as f:
        f.write(config_file_content)


# Format length of file for humans
def bytes_str(lBytes):
    if lBytes >= 1E9:
        l = "{:.4} GB".format(lBytes/1E9)
    elif lBytes >= 1E6:
        l = "{:.4} MB".format(lBytes/1E6)
    elif lBytes >= 1E3:
        l = "{:.4} kB".format(lBytes/1E3)
    else:
        l = "{} B".format(lBytes)
    return l


def gen_hash(s):
    # Note: Avoid str.__hash__(). It's salted.

    if isinstance(s, str):
        s = s.encode('utf-8')

    sha = sha1(s)
    return sha.hexdigest()[:16]