#!/usr/bin/python3
# -*- coding: utf-8 -*-
#
# Parse feed xml files into feed.context dict. 
# The context can be propagated into the html renderer.
#

import os.path
import re
import hashlib
from datetime import datetime
import locale
from xml.etree import ElementTree
from subprocess import Popen, PIPE

import logging
logger = logging.getLogger(__name__)

import default_settings as settings  # Overriden in load_config()

XML_NAMESPACES = {'content': 'http://purl.org/rss/1.0/modules/content/',
                  'atom': 'http://www.w3.org/2005/AtomX',
                  'atom10': 'http://www.w3.org/2005/Atom',
                  'bitlove': 'http://bitlove.org',
                 }

ORIG_LOCALE = locale.getlocale()  # running user might be non-english
EN_LOCALE = ("en_US", "utf-8")


def parse_feed(feed, text):
    tree = ElementTree.XML(text)

    feed.context = find_feed_keyword_values(feed, tree)

    feed.title = feed.context["title"]
    if feed.name == "":  # New feed got title as name
        feed.name = feed.context["title"]


def find_feed_keyword_values(feed, tree):

    context = feed.context if feed.context else {}

    context.setdefault("title", "Undefined")
    context.setdefault("href", "")
    context.setdefault("feed_lang", "en")

    def search_href():
        if (atom_node.attrib.get("rel") == "self" and
            atom_node.attrib.get("type") in ["application/rss+xml",
                                                 "application/xml"]
           ):
            context["href"] = atom_node.attrib.get("href", "")
            context["title"] = atom_node.attrib.get(
                "title", context["title"])
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
        if settings.CONTENT_MAX_ENTRIES >= 0:
            if entry_id > settings.CONTENT_MAX_ENTRIES and False:
                break

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
    return context


def find_enclosures(feed, item_node):
    enclosures = []
    for e_node in item_node.findall('./enclosure'):
        e = {}
        try:
            url = e_node.attrib["url"]
            """# Escape arguments?!
            url2 = url.split("?", 1)
            if len(url2) > 1:
                url2[1] = urlencode(url2[1])

            url = "?".join(url2)
            """
            e["enclosure_url"] = url
        except (AttributeError, KeyError):
            e["enclosure_url"] = "Undefined"

        e["enclosure_filename"] = os.path.basename(e["enclosure_url"])

        try:
            e["enclosure_guid"] = e_node.attrib["guid"]
        except (AttributeError, KeyError):
            e["enclosure_guid"] = str(e["enclosure_url"].__hash__())

        try:
            e["enclosure_type"] = e_node.attrib["type"]
        except (AttributeError, KeyError):
            e["enclosure_type"] = "Undefined"

        try:
            lBytes = int(e_node.attrib["length"])
            if lBytes >= 1E9:
                l = "{:.4} GB".format(lBytes/1E9)
            elif lBytes >= 1E6:
                l = "{:.4} MB".format(lBytes/1E6)
            elif lBytes >= 1E3:
                l = "{:.4} kB".format(lBytes/1E3)
            else:
                l = "{} B".format(lBytes)

            e["enclosure_length"] = l
        except (AttributeError, KeyError, ValueError):
            e["enclosure_length"] = "0"

        # Extend by dict with actions
        add_enclosure_actions(feed, e)

        enclosures.append(e)

    return enclosures


def add_enclosure_actions(feed, e):
    # Add dict with possible actions for this media element
    # The hash is added to prevent change of url. (No user authentication...)

    url = e["enclosure_url"]
    e["actions"] = []

    for (aname, action) in settings.ACTIONS.items():
        if action.get("check"):
            if not action["check"](feed, url, settings):
                continue

        url_hash = '{}'.format( hashlib.sha224(
            (settings.ACTION_SECRET + url + aname).encode('utf-8')
        ).hexdigest())
        # guid = e.get("enclosure_guid", e["enclosure_url"])

        a = {
            "url": "/action?a={action}&feed={feed}&url={url}" \
            "&s={url_hash}".format(
                feed=feed.name,
                action=aname,
                url=url,
                url_hash=url_hash),
            "title": action["title"],
            "icon": action["icon"],
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
            logger.warn("Can not set locale: %s" % str(e))
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


