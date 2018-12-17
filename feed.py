#!/usr/bin/python3
# -*- coding: utf-8 -*-

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


def get_feed(key, feeds, hist_feeds=None):
    """ Search feed in list of Feeds-objects. """
    if key == "":
        return None

    for f in feeds:
        if key in [f.name, f.title, f.url]:
            return f

    if hist_feeds:
        return get_feed(key, hist_feeds)

    #raise ValueError("No feed found for {}".format(key))
    return None


def save_history(feeds):
    """ Writes feeds into feed_history.py """

    print("Write history with {0} entries.".format(len(feeds)))
    with open("feed_history.py", "w") as f:
        f.write("#!/usr/bin/python3\n")
        f.write("# -*- coding: utf-8 -*-\n\n")
        f.write("from feed import Feed\n")
        f.write("FEED_HISTORY = [\n")
        for feed in feeds:
            f.write("  {},\n".format(feed))
        f.write("]\n")


def clear_history(feedsA, feedsB):
    """ Remove feeds from feedsB if similar entry found in feedsA. """
    found = []
    for feed in feedsB:
        if get_feed(feed.title, feedsA):
            found.append(feed)

    for feed in found:
        feedsB.remove(feed)
