#!/usr/bin/python3
# -*- coding: utf-8 -*-
#
# Parse feed xml files into feed.context dict. 
# The context can be propagated into the html renderer.
#

import sys
import os.path
import re
import hashlib
from datetime import datetime
import locale
from xml.etree import ElementTree
from subprocess import Popen, PIPE

from urllib.parse import quote, unquote

import logging
logger = logging.getLogger(__name__)

from feed import Feed, bytes_str
import default_settings as settings  # Overriden in load_config()

XML_NAMESPACES = {'content': 'http://purl.org/rss/1.0/modules/content/',
                  'atom': 'http://www.w3.org/2005/AtomX',
                  'atom10': 'http://www.w3.org/2005/Atom',
                  'bitlove': 'http://bitlove.org',
                  'media': 'https://www.rssboard.org/media-rss',
                  'feedburner': 'http://rssnamespace.org/feedburner/ext/1.0',
                 }

ORIG_LOCALE = locale.getlocale()  # running user might be non-english
EN_LOCALE = ("en_US", "utf-8")

def parse_feed(feed, text):
    try:
        if isinstance(text, bytes):
            tree = ElementTree.XML(text.decode('utf-8'))
        else:
            tree = ElementTree.XML(text)
    except ElementTree.ParseError as e:
        logger.error("ParseError: '{}'".format(e))
        return False

    find_feed_keyword_values(feed, tree)

    feed.title = feed.context["title"]
    if feed.name == "":  # New feed got title as name
        feed.name = feed.context["title"]

    return True


def find_feed_keyword_values(feed, tree):

    feed.context = feed.context if feed.context else {}
    context = feed.context

    context["feed2"] = feed
    context.setdefault("title", "Undefined")
    context.setdefault("href", "")
    context.setdefault("feed_lang", "en")
    context.setdefault("source_xml_link", feed.url)

    def search_href():
        if (atom_node.attrib.get("rel") == "self" and
            atom_node.attrib.get("type") in ["application/rss+xml",
                                                 "application/xml"]
           ):
            context["source_xml_link"] = atom_node.attrib.get("href", "")
            context["title"] = atom_node.attrib.get(
                "title", context["title"])

            # Sanitize input which breaks html code
            # Disabled because urls are now normalized to unqoted form
            # context["href"] = quote(context["href"], safe=":/")
            # context["title"] = quote(context["title"], safe=":/")

            return True

    for atom_node in tree.findall('./channel/atom10:link', XML_NAMESPACES):
        if search_href(): break

    for atom_node in tree.findall('./channel/atom:link', XML_NAMESPACES):
        if search_href(): break

    # ATTENTION: 'if node:' evaluates to False even if node is a 'node instance'!
    # Check with 'if node is not None:'
    node = tree.find('./channel/title')
    if node is not None:
        context["title"] = node.text

    node = tree.find('./channel/link')
    if node is not None:
        context["source_link"] = node.text

    node = tree.find('./channel/language')
    if node is not None:
        context["feed_lang"] = node.text

    node = tree.find('./channel/description')
    context["subtitle"] = "Undefined" if node is None else node.text

    node = tree.find('./channel/image/url')
    image_url = "" if node is None else node.text

    node = tree.find('./channel/image/title')
    image_title = "" if node is None else node.text

    if image_url:
        context["image"] = {"url" : image_url,
                                "title": image_title}

    entries = []
    entries_len = 0  # To remove entry_content_full for long feeds.
    for item_node in tree.findall('./channel/item'):
        entry_id = len(entries)+1

        entry = {}
        node = item_node.find('./link')
        entry["url"] = "Undefined" if node is None else node.text

        node = item_node.find('./title')
        entry["title"] = "Undefined" if node is None else node.text

        node = item_node.find('./guid')
        entry["guid"] = (str(entry["url"].__hash__()) if node is None \
                         else node.text)

        node = item_node.find('./description')
        content_short = "" if node is None else node.text

        node = item_node.find('./content:encoded', XML_NAMESPACES)
        content_full  = "" if node is None else node.text

        if content_short == content_full:  # Remove duplicate info
            content_full = ""

        if content_short == "":  # Use full directly if <description> was empty
            content_short, content_full = content_full, ""

        if entries_len > settings.CONTENT_FULL_LEN_THRESH:
            content_full = ""

        if not settings.DETAIL_PAGE:
            content_full = ""

        context["extra_css_cls"] = ("in1_ani"
                                         if settings.DETAIL_PAGE_ANIMATED else
                                         "in1_no_ani")

        entry["content_short"] = content_short
        entry["content_full"] = content_full

        node = item_node.find('./pubDate')
        if node is not None:
            # entry["pubDate"] = parse_pubDate(node.text)
            entry["pubDate"] = node.text  # Converted later
        else:
            entry["pubDate"] = None

        entry["enclosures"] = find_enclosures(feed, item_node)

        entries.append(entry)
        entries_len += len(content_full)

    context["entries"] = entries
    context["entry_list_first_id"] = 0
    context["entry_list_size"] = settings.CONTENT_MAX_ENTRIES \
            if settings.CONTENT_MAX_ENTRIES > 0 else len(entries)
    return context


def find_enclosures(feed, item_node):
    enclosures = set()  # Set to avoid duplicates

    for e_node in item_node.findall('./enclosure'):
        e = __Enclosure(e_node)  # {}
        enclosures.add(e)

    # Other format for enclosures (with node other properties)
    for e_node in item_node.findall('./media:content', XML_NAMESPACES):
        e = __Enclosure(e_node, "media:content")  # {}
        enclosures.add(e)

    for e_group in item_node.findall('./media:group', XML_NAMESPACES):
        for e_node in e_group.findall('./media:content', XML_NAMESPACES):
            e = __Enclosure(e_node, "media:content")  # {}
            enclosures.add(e)

    # Extend enclosures by dict with actions
    for e in enclosures:
        add_enclosure_actions(feed, e)

    return list(enclosures)


def add_enclosure_actions(feed, e):
    # Add dict with possible actions for this media element
    # The hash is added to prevent change of url. (No user authentication...)

    url = e["enclosure_url"]
    e["actions"] = []

    # feeds opened by filename (?file=...) has no name
    # at this stage. Use title from xml file.
    name = feed.name if feed.name else feed.context.get("title", "")

    for (aname, action) in settings.ACTIONS.items():
        if action.get("check"):
            if not action["check"](feed, url, settings):
                continue

        url_hash = '{}'.format( hashlib.sha224(
            (settings.ACTION_SECRET + url + aname).encode('utf-8')
        ).hexdigest())
        # guid = e.get("enclosure_guid", e["enclosure_url"])

        # Quoting of feed and url at least for '#&?' chars.
        url_args = "a={action}&feed={feed}&url={url}&s={url_hash}".format(
                feed=quote(name),
                action=aname,
                url=quote(url),
                url_hash=url_hash)

        a = {
            "url": "{}?{}".format("/action", url_args),
            "title": action["title"],
            "icon": action["icon"],
            "name": aname,
        }


        e["actions"].append(a)


# ==========================================================


def find_installed_en_locale():
    # Find installed EN locale. en_US or en_GB in most cases
    try:
        (out, err) = Popen(['locale', '-a'], stdout=PIPE).communicate()
        avail_locales = out.decode('utf-8').split("\n")

        # Check for normal value
        en_locale = [l for l in avail_locales \
                     if l.split(".")[0] in ["en_US", "en_GB"]]
        if len(en_locale) > 0:
            # Select more exotic one
            en_locale.extend([l for l in avail_locales \
                              if l.startswith("en_")])

        # Prefer utf8
        _tmp = [l for l in en_locale if l.split(".")[-1] == "utf8"]
        if len(_tmp) > 0:
            en_locale = _tmp

        # Prefer _US
        _tmp = [l for l in en_locale if l.startswith("en_US")]
        if len(_tmp) > 0:
            en_locale = _tmp

        EN_LOCALE = en_locale[0].split(".")
    except Exception as e:
        logger.warning("No english locale detected. Error message was: '{}' \n"\
                        "\nParsing of date strings is easier with installed "\
                        "english locales".format(e))
        EN_LOCALE = ("en_US", ORIG_LOCALE[1])

    logger.info("Use {} for english date strings".format(".".join(EN_LOCALE)))

    # Set variable on module level
    sys.modules[__name__].EN_LOCALE = EN_LOCALE

def parse_pubDate(s, date_format=None):
    """
    Example input:
        <pubDate>Tue, 04 Dec 2018 06:48:30 +0000</pubDate>
        <pubDate>Fri, 15 Mar 2019 18:00:00 GMT</pubDate>
    """
    formats = [
        ("%a, %d %b %Y %H:%M:%S %z", s),
        ("%a, %d %b %Y %H:%M:%S %Z", s),
        ("%a, %d %b %Y %H:%M:%S", s[:s.rfind(" ")-len(s)]),
    ]

    if date_format is None:
        date_format="%d. %B %Y, %H:%M%p"

    ret = None
    for (f, s2) in formats:
        try:
            locale.setlocale(locale.LC_ALL, EN_LOCALE)
            dt = datetime.strptime(s2, f)

            # Without this line the locale is ignored...
            locale.setlocale(locale.LC_ALL, '')
            ret = dt.strftime(date_format)

            locale.resetlocale(locale.LC_ALL)
            break
        except locale.Error as e:
            logger.warn("Can not set locale '{}'. Error: '{}'.".\
                    format(str(EN_LOCALE), str(e)))
            dt = datetime.strptime(s2, f)
            ret = dt.strftime(date_format)
            break
        except ValueError:
            pass

    if ret:
        return ret

    # raise Exception("Can not parse pubDate '{}'".format(s))
    logger.warn("Can not parse pubDate '{}'.".format(s))
    return s


# Helper class for dict to filter out duplicates.
class __Enclosure(dict):
    def __hash__(self):
        return self.get("enclosure_url", "").__hash__()

    """ Currently not needed
    def __cmp__(self, b):
        if self.get("enclosure_url", -1) == b.get("enclosure_url"):
            return 0
        return super(self).__cmp__(b)
    """

    def __init__(self, e_node, e_node_name=None):
        try:
            url = e_node.attrib["url"]
            """# Escape arguments?!
            url2 = url.split("?", 1)
            if len(url2) > 1:
                url2[1] = urlencode(url2[1])

            url = "?".join(url2)
            """
            self["enclosure_url"] = url
        except (AttributeError, KeyError):
            self["enclosure_url"] = "Undefined"

        self["enclosure_filename"] = os.path.basename(self["enclosure_url"])

        try:  # param not included in media:content
            self["enclosure_guid"] = e_node.attrib["guid"]
        except (AttributeError, KeyError):
            self["enclosure_guid"] = str(self["enclosure_url"].__hash__())

        try:
            self["enclosure_type"] = e_node.attrib["type"]
        except (AttributeError, KeyError):
            self["enclosure_type"] = "Undefined"

        try:
            if e_node_name in ["media:content"]:
                lBytes = int(e_node.attrib["fileSize"])
            else:
                lBytes = int(e_node.attrib["length"])

            self["enclosure_length"] = bytes_str(lBytes)
        except (AttributeError, KeyError, ValueError):
            self["enclosure_length"] = "0"


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    settings.load_config(globals())
    settings.update_submodules(globals())

    if len(sys.argv) < 2:
        logger.error("No filename of xml feed file given.")
        sys.exit(-1)

    filename = sys.argv[1]
    feed = Feed("Test feed", "local file")
    text = ""
    with open(filename, 'r') as f:
        text = f.read(-1)


    parse_feed(feed, text)
