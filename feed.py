#!/usr/bin/python3
# -*- coding: utf-8 -*-

import os.path
import re

class Feed:
    def __init__(self, name, url, title=None):
        self.name = name
        self.url = url
        self.title = title

    def __repr__(self):
        return 'Feed("{name}", "{url}" {title})'.format(
            name=self.name,
            url=self.url,
            title=', "{}"'.format(self.title) if self.title else "",
        )


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


def save_history(feeds, folder=None):
    """ Writes feeds into history.py """

    path = "history.py"
    if folder:
        path = os.path.join(folder, path)

    print("Write history with {0} entries.".format(len(feeds)))
    with open(path, "w") as f:
        f.write("#!/usr/bin/python3\n")
        f.write("# -*- coding: utf-8 -*-\n\n")
        f.write("from feed import Feed\n")
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

def update_favorites(feeds, folder=None, path="favorites.py"):
    """ Updates FAVORITES variable into favorites.py
    
    Function do not alter other parts of given config file.
    (Note: Previous versions saves favarites directly in settings.py)
    """

    if folder:
        path = os.path.join(folder, path)

    if not os.path.exists(path):
        config_file_content = """
#!/usr/bin/python3
# -*- coding: utf-8 -*-

from feed import Feed

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

    print("Write settings file with {0} favorite entries.".format(len(feeds)))
    with open(path, "w") as f:
        f.write(config_file_content)


