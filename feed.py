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
        return None

    for idx in range(len(feed_lists)):
        feeds = feed_lists[idx]
        for f in feeds:
            if key in [f.name, f.title, f.url]:
                return (f, idx)

    #raise ValueError("No feed found for {}".format(key))
    return None


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
        if get_feed(feed.title, feedsA):
            found.append(feed)

    for feed in found:
        feedsB.remove(feed)

def update_favorites(feeds, folder=None):
    """ Updates FAVORITES variable into settings.py """

    path = "settings.py"
    if folder:
        path = os.path.join(folder, path)

    if not os.path.exists(path):
        settings_content = """
#!/usr/bin/python3
# -*- coding: utf-8 -*-

from feed import Feed

FAVORITES = [ 
    {__FAVORITES}
]
"""
    else:
        with open(path, "r") as f:
            settings_content = f.read(-1)
            # Remove content of FAVORITES list
            search = re.search("\nFAVORITES\s*=\s\[[^]]*]",
                                       settings_content)
            favs_substring = settings_content[search.start()+1:search.end()]
            # Check if regex search return valid substring.
            try:
                compile(favs_substring, "favs_list", "exec")
            except SyntaxError:
                raise Exception("Abort writing of settings.py. Search for "
                                "FAVORITES list failed.")

            # Replace string of current favorites list with dummy.
            settings_content = settings_content[:search.start()+1] \
                    + "FAVORITES = [\n    {__FAVORITES}\n]" \
                    + settings_content[search.end():]

        # Fill in new feed list
        feed_strs = [str(feed) for feed in feeds]
        settings_content = settings_content.format(__FAVORITES=",\n    ".join(feed_strs) + ",\n")

    with open(path, "w") as f:
        f.write(settings_content)
