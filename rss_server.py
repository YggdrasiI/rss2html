#!/usr/bin/python3
# -*- coding: utf-8 -*-

import sys
import os.path
from datetime import datetime
from xml.etree import ElementTree

from urllib.parse import urlparse, parse_qs, quote
from threading import Thread
import http.server
import hashlib
import socket
import socketserver
from io import BytesIO
import locale
from subprocess import Popen, PIPE
from time import sleep
from random import randint
from warnings import warn
# from importlib import reload
import ssl

from gettext import gettext as _
# from jina2.utils import unicode_urlencode as urlencode

from feed import Feed, get_feed, save_history, clear_history, update_favorites

import templates
import default_settings as settings  # Overriden in load_config()
import icon_searcher
import cached_requests

from session import LoginFreeSession, ExplicitSession, PamSession

import logging
import logging.config
logger = None

SESSION_TYPES = {
    None: LoginFreeSession,
    "single_user": LoginFreeSession,
    "users": ExplicitSession,
    "pam": PamSession,
}

CSS_STYLES = {
    "default.css": _("Default theme"),
    "dark.css": _("Dark theme"),
}

XML_NAMESPACES = {'content': 'http://purl.org/rss/1.0/modules/content/',
                  'atom': 'http://www.w3.org/2005/AtomX',
                  'atom10': 'http://www.w3.org/2005/Atom',
                 }

ORIG_LOCALE = locale.getlocale()  # running user might be non-english
EN_LOCALE = ("en_US", "utf-8")

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

def check_process_already_running():
    # TODO
    return False


def daemon_double_fork():
    # To avoid zombie processes
    pid = os.fork()
    if pid == 0:
        pid2 = os.fork()
        if pid2 == 0:
            # Omit outputs
            nullsink = open(os.devnull, 'w')
            sys.stdout = nullsink
            sys.stderr = nullsink
            return True  # Continue with second child process
        else:
            os._exit(0)  # Quit first child process
    else:
        # Wait on first child process
        os.waitpid(pid, 0)

    return False


def parse_pubDate(s):
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

    ret = None
    for (f, s2) in formats:
        try:
            locale.setlocale(locale.LC_ALL, EN_LOCALE)
            dt = datetime.strptime(s2, f)

            # Without this line the locale is ignored...
            locale.setlocale(locale.LC_ALL, '')
            ret = dt.strftime("%d. %B %Y, %H:%M%p")

            locale.resetlocale(locale.LC_ALL)
            break
        except locale.Error as e:
            logger.warn("Can not set locale: %s" % str(e))
            dt = datetime.strptime(s2, f)
            ret = dt.strftime("%d. %B %Y, %H:%M%p")
            break
        except ValueError:
            pass

    if ret:
        return ret

    raise Exception("Can not parse '{}'".format(s))


def load_xml(filename):
    with open(filename, 'rt') as f:
        text = f.read(-1)
        return text

    return None



def find_feed_keyword_values(tree, context=None):

    context = context if context else {}

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
            entry["last_update"] = parse_pubDate(node.text)
        else:
            entry["last_update"] = "Undefined date"

        entry["enclosures"] = find_enclosures(item_node)

        entries.append(entry)
        entries_len += len(content_full)

    context["entries"] = entries
    return context


def find_enclosures(item_node):
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
        add_enclosure_actions(e)

        enclosures.append(e)

    return enclosures

def add_enclosure_actions(e):
    # Add dict with possible actions for this media element
    # The hash is added to prevent change of url. (No user authentication...)

    url = e["enclosure_url"]
    url_hash = '{}'.format( hashlib.sha224(
        (settings.ACTION_SECRET + url).encode('utf-8')).hexdigest())
    e["actions"] = []

    for (aname, action) in settings.ACTIONS.items():
        if action.get("check"):
            if not action["check"](url, settings):
                continue

        a = {
            "url": "/action?a={}&s={}&url={}".format(
                aname,
                url_hash, url),
            "title": action["title"],
            "icon": action["icon"],
        }
        e["actions"].append(a)



def genMyHTTPServer():
# The definition of the MyTCPServer class is wrapped
# because settings module only maps to the right module
# at runtime (after load_config() call).
# Before it maps on default_settings.

    if hasattr(http.server, "ThreadingHTTPServer"):
        ServerClass = http.server.ThreadingHTTPServer
    else:
        ServerClass = socketserver.TCPServer

    class _MyHTTPServer(ServerClass):
        logger.info("Use language {}".format(settings.GUI_LANG))
        html_renderer = templates.HtmlRenderer(settings.GUI_LANG,
                                               settings.CSS_STYLE)

        # Required for IPv6 hostname
        address_family = socket.AF_INET6 if ":" in settings.HOST \
                else socket.AF_INET

        def __init__(self, *largs, **kwargs):
            super().__init__(*largs, **kwargs)
            self.html_renderer.extra_context["login_type"] = \
                    settings.LOGIN_TYPE

        def server_bind(self):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket.bind(self.server_address)

    return _MyHTTPServer


class MyHandler(http.server.SimpleHTTPRequestHandler):
    server_version = "RSS_Server/0.1"

    # Note: ETag ignored for 1.0, but protcol version 1.1
    # requires header 'Content-Lenght' for all requests. Otherwise,
    # the browsers will wait forever for more data...
    #
    # ETag in FF still ignored
    ## protocol_version = "HTTP/1.1"
    directory="rss_server-page"  # for Python 3.4

    def __init__(self, *largs, **kwargs):
        Session = SESSION_TYPES.get(settings.LOGIN_TYPE, ExplicitSession)
        self.session = Session(self, settings.ACTION_SECRET)

        # Flag to send session cookies without login form.
        # The header info will send for visit of index- or feed-page.
        self.save_session = False
        self.context = {}

        super().__init__(*largs, **kwargs)  # for Python 3.4
        # super().__init__(*largs, directory="rss_server-page", **kwargs)

    def get_favorites(self):
        session_user = self.session.get_logged_in("user")
        return settings.USER_FAVORITES.get(session_user,
                                           settings.FAVORITES)

    def get_history(self):
        session_user = self.session.get_logged_in("user")
        return settings.USER_HISTORY.get(session_user,
                                         settings.HISTORY)

    def do_add_favs(self, add_favs):
        session_user = self.session.get_logged_in("user")
        favs = self.get_favorites()
        hist = self.get_history()
        for feed_key in add_favs:
            # Check for feed with this name
            (feed, _) = get_feed(feed_key, hist)
            if feed:
                try:
                    hist.remove(feed)
                except ValueError:
                    logging.debug("Removing of feed '{}' from history" \
                                  "failed.".format(feed))

            (feed, _) = get_feed(feed_key, favs)
            if not feed:  # Add if not already in FAVORITES
                favs.append(feed)

        update_favorites(favs, settings.get_config_folder(),
                         settings.get_favorites_filename(session_user))
        save_history(hist, settings.get_config_folder(),
                     settings.get_history_filename(session_user))


    def do_rm_feed(self, to_rm):
        session_user = self.session.get_logged_in("user")
        favs = self.get_favorites()
        hist = self.get_history()
        for feed_key in to_rm:
            (feed, idx) = get_feed(feed_key, favs, hist)

            if idx == 0:
                try:
                    favs.remove(feed)
                    update_favorites(
                        favs, settings.get_config_folder(),
                        settings.get_favorites_filename(session_user))
                except ValueError:
                    pass

            if idx == 1:
                try:
                    hist.remove(feed)
                    save_history(
                        hist, settings.get_config_folder(),
                        settings.get_history_filename(session_user))
                except ValueError:
                    pass

    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        content = self.rfile.read(content_length).decode('utf-8')
        query_components = parse_qs(content)

        if self.path == "/login" or \
           "login" in query_components.get("form_id"):
            return self.handle_login(query_components)

        if self.path == "/logout" or \
           "logout" in query_components.get("form_id"):
            return self.handle_logout(query_components)

        msg = 'Post values: {}'.format(str(query_components))
        return self.show_msg(msg)


    def do_GET(self):

        self.session.load()
        self.save_session = False  # To send session headers without login form.

        if settings.LOGIN_TYPE == "single_user" and \
           not self.session.get("user"):
            logger.debug("Generate new ID for default user!")
            # Login as "default" user and trigger send of headers
            if self.session.init(user="default"):
                # return self.session_redirect(self.path)
                self.save_session = True

        session_user = self.session.get_logged_in("user")

        # User CSS-Style can overwrite server value
        user_css_style = self.session.get("css_style")
        if user_css_style and user_css_style in CSS_STYLES:
            self.context["user_css_style"] = user_css_style

        query_components = parse_qs(urlparse(self.path).query)
        feed_feched = False
        error_msg = None
        show_index = False
        feed_key = query_components.get("feed", [None])[-1]  # key, url or feed title
        filepath = query_components.get("file")  # From 'open with' dialog
        bUseCache = query_components.get("cache", ["1"])[-1] != "0"
        url_update = query_components.get("url_update", ["0"])[-1] != "0"
        add_favs = query_components.get("add_fav", [])
        to_rm = query_components.get("rm", [])
        etag = None

        # entryid=0: Newest entry of feed. Thus, id not stable due feed updates
        try:
            entryid = int(query_components.get("entry", )[-1])
        except:
            entryid = None


        if add_favs:
            show_index = True
            self.do_add_favs(add_favs)

        if to_rm:
            show_index = True
            self.do_rm_feed(to_rm)


        if self.path == "/quit":
            ret = self.show_msg(_("Quit"))

            def __delayed_shutdown():
                sleep(1.0)
                self.server.shutdown()

            t = Thread(target=__delayed_shutdown)
            t.daemon = True
            t.start()
            return ret

        elif self.path == "/reload":
            self.reload_favs()
            return self.session_redirect('/')
        elif self.path.startswith("/login?"):
            return self.handle_login(query_components)
        elif self.path == "/login":
            return self.show_login()
        elif self.path ==  "/logout":
            return self.handle_logout(query_components)
        elif self.path.startswith("/change_style"):
            self.handle_change_css_style(query_components)
            return self.session_redirect('/')
            # return self.write_index()
        elif self.path.startswith("/action"):
            try:
                ret = self.handle_action(query_components)
            except Exception as e:
                error_msg = str(e)
            else:
                return ret

        elif feed_key:
            try:
                feed = get_feed(feed_key,
                                self.get_favorites(),
                                self.get_history())[0]
                feed_url = feed.url if feed else feed_key

                res = None
                (text, code) = cached_requests.fetch_file(settings, feed_url, bUseCache)

                if text is None:
                    error_msg = _('No feed found for this URI arguments.')
                    return self.show_msg(error_msg, True)

                etag = '"{}"'.format(
                    hashlib.sha1((text if text is not None \
                                 else "").encode('utf-8')).hexdigest())
                logger.debug("Eval ETag '{}'".format(etag))
                logger.debug("Browser ETag '{}'".format(self.headers.get("If-None-Match", "")))
                logger.debug("Received headers:\n{}".format(self.headers))

                # If feed is unchanged and tags match return nothing, but 304.
                if code == 304 and self.headers.get("If-None-Match", "") == etag:
                    self.send_response(304)
                    self.send_header('ETag', etag)
                    self.send_header('Cache-Control', "public, max-age=10, ")
                            # "must-revalidate, post-check=0, pre-check=0")
                    self.send_header('Vary', "ETag, User-Agent")
                    self.end_headers()
                    return None

                tree = ElementTree.XML(text)

                res = find_feed_keyword_values(tree)

                # Update cache and history
                if not feed:
                    feed_title = res["title"]
                    # Add this (new) url to feed history.
                    hist = self.get_history()
                    hist.append(
                        Feed(feed_title, feed_url, feed_title))
                    save_history(hist, settings.get_config_folder(),
                                 settings.get_history_filename(session_user))

                # Warn if feed url might changes
                parsed_feed_url = res["href"]
                if not url_update and parsed_feed_url and parsed_feed_url != feed_url:
                    res.setdefault("warnings", []).append({
                        "title": "Warning",
                        "msg": """Feed url difference detected. It might
                        be useful to <a href="/?{ARGS}&url_update=1">update</a> \
                        the stored url.<br /> \
                        Url in config/history file: {OLD_URL}<br /> \
                        Url in feed xml file: {NEW_URL}
                        """.format(OLD_URL=feed_url,
                                   NEW_URL=parsed_feed_url,
                                   ARGS="feed=" + quote(str(feed_key)),
                                  )
                    })

                #res["nocache_link"] = "/?feed={}&cache=0".format(feed_key)
                res["nocache_link"] = feed_key
                res["session_user"] = session_user

                # Replace stored url, if newer value is given.
                if feed and url_update and res["href"]:
                    feed_url = feed.url
                    feed.url = res["href"]
                    feed.title = res.get("title", feed.title)
                    self.save_feed_change(feed)

                if entryid:
                    html = "TODO"
                else:
                    context = {}
                    context.update(self.context)
                    context.update(res)
                    html = self.server.html_renderer.run(
                        "feed.html", context)

            except ValueError as e:
                error_msg = str(e)
            except:
                raise
            else:
                feed_feched = True

        elif filepath:
            # No cache read in this variant
            try:
                feed_filepath = filepath[-1]
                logger.debug("Read " + feed_filepath)

                try:
                    text = load_xml(feed_filepath)
                    tree = ElementTree.XML(text)
                except FileNotFoundError:
                    error_msg = _("Feed XML document '{}' does not " \
                                  "exists.".format(feed_filepath))
                    return self.show_msg(error_msg, True)
                except ElementTree.ParseError:
                    error_msg = _("Parsing of feed XML document '{}' " \
                                  "failed.".format(feed_filepath))
                    return self.show_msg(error_msg, True)
                except:
                    error_msg = _("Loading of feed XML document '{}' " \
                                  "failed.".format(feed_filepath))
                    return self.show_msg(error_msg, True)

                res = find_feed_keyword_values(tree)
                res["nocache_link"] = res["title"]
                res["session_user"] = session_user

                # Update cache and history
                feed = get_feed(res["title"],
                                self.get_favorites(),
                                self.get_history())[0]
                if feed:
                    # Currently, the feed title is an unique key.
                    # Replace feed url if extracted href field
                    # indicates a newer url for a feed with this title.
                    parsed_feed_url = res["href"]
                    if parsed_feed_url and parsed_feed_url != feed.url:
                        feed.url = parsed_feed_url
                        self.save_feed_change(feed)

                else:
                    feed_title = res["title"]
                    feed = Feed(feed_title,
                                res.get("href", ""),
                                feed_title)
                    # Add this (new) feed to history.
                    # Try to extract feed url from xml data because it is not
                    # given directly!
                    hist = self.get_history()
                    hist.append(feed)
                    save_history(hist, settings.get_config_folder(),
                                 settings.get_history_filename(session_user))

                cached_requests.update_cache(feed.title, res, {})
                context = {}
                context.update(self.context)
                context.update(res)
                html = self.server.html_renderer.run("feed.html", context)

            except ValueError as e:
                error_msg = str(e)
            except:
                raise
            else:
                feed_feched = True

        if error_msg:
            return self.show_msg(error_msg, True)
        elif feed_feched:
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.send_header('Cache-Control', "public, max-age=10, ")
            if etag:
                logger.debug("Add ETag '{}'".format(etag))
                self.send_header('ETag', etag)
                self.send_header('Vary', "ETag, User-Agent")

            if self.save_session:
                self.session.save()

            output = BytesIO()
            output.write(html.encode('utf-8'))
            output.seek(0, os.SEEK_END)
            self.send_header('Content-Length', output.tell())
            self.end_headers()

            self.wfile.write(output.getvalue())

        elif self.path.startswith("/icons/system/"):
            image = icon_searcher.get_cached_file(self.path)
            if not image:
                return self.send_error(404)

            self.send_response(200)
            if self.path.endswith(".svg"):
                # text/xml would be wrong and FF won't display embedded svg
                self.send_header('Content-type', 'image/svg+xml')
            else:
                self.send_header('Content-type', 'image')

            self.send_header('Cache-Control', "public, max-age=86000, ")
            # self.send_header('last-modified', self.date_time_string())
            self.send_header('Last-Modified', "Wed, 21 Oct 2019 07:28:00 GMT")
            self.send_header('Vary', "User-Agent")
            # TODO: Image not cached :-(

            output = BytesIO()
            output.write(image)
            output.seek(0, os.SEEK_END)
            self.send_header('Content-Length', output.tell())
            self.end_headers()

            self.wfile.write(output.getvalue())

        elif self.path == "/" or show_index:
            # self.session.load(self)
            return self.write_index()
        elif os.path.splitext(urlparse(self.path).path)[1] in \
                settings.ALLOWED_FILE_EXTENSIONS:
            self.path = self.directory + "/" + self.path  # for Python 3.4
            ret =  super().do_GET()
        else:
            print(self.path)
            # return super().do_GET()
            return self.send_error(404)

    def write_index(self):
        session_user = self.session.get_logged_in("user")
        user = self.session.get("user")

        self.context.update({
            "host": self.headers.get("HOST", ""),
            "protocol": "https://" if settings.SSL else "http://",
            "session_user": session_user,
            "user": user,
            "CONFIG_FILE": settings.get_settings_path(),
            "FAVORITES_FILE": settings.get_favorites_path(user),
            "favorites": self.get_favorites(),
            "history": self.get_history(),
            "css_styles": CSS_STYLES,
        })

        logger.debug("Recived headers:\n{}".format(self.headers))
        html = self.server.html_renderer.run("index.html", self.context)

        output = BytesIO()
        output.write(html.encode('utf-8'))
        output.seek(0, os.SEEK_END)  # As reminder…

        # Etag
        etag = '"{}"'.format( hashlib.sha1(output.getvalue()).hexdigest())

        browser_etag = self.headers.get("If-None-Match", "")
        if etag == browser_etag and not self.save_session:
            self.send_response(304)
            self.send_header('ETag', etag)
            # self.send_header('Cache-Control', "public, max-age=10, ")
            self.send_header('Cache-Control', "public, max-age=0, ")
                            # "must-revalidate, post-check=0, pre-check=0")
            self.send_header('Content-Location', "/index.html")
            self.send_header('Vary', "ETag, User-Agent")
            # self.send_header('Expires', "Wed, 21 Oct 2021 07:28:00 GMT")
            self.end_headers()
            return None

        self.send_response(200)

        # Preparation for 304 replys....
        # Note that this currently only works with Chromium, but not FF
        #
        # Regarding to
        # https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/304
        # Following headers are required in the 200-response
        # Cache-Control, Content-Location, Date (is already included),
        # ETag, Expires (overwritten by max-age, but still required?!)
        # and Vary.
        self.send_header('ETag', etag)
        self.send_header('Cache-Control', "public, max-age=10, ")
                        # "must-revalidate, post-check=0, pre-check=0")
        self.send_header('Content-Location', "/index.html")
        self.send_header('Vary', "ETag, User-Agent")
        # self.send_header('Expires', "Wed, 21 Oct 2021 07:28:00 GMT")  # Won't help in FF
        # self.send_header('Last-Modified', "Wed, 21 Oct 2019 07:28:00 GMT")  # Won't help in FF

        if self.save_session:
            self.session.save()

        # Other headers
        self.send_header('Content-Length', output.tell())
        self.send_header('Content-type', 'text/html')
        self.end_headers()

        self.wfile.write(output.getvalue())

    def show_msg(self, msg, error=False):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')

        self.context.update({
            "msg": msg,
        })

        self.context["session_user"] = self.session.get_logged_in("user")

        output = BytesIO()
        if error:
            self.context["msg_type"] = _("Error")
            html = self.server.html_renderer.run("message.html", self.context)
        else:
            self.context["msg_type"] = _("Debug Info")
            html = self.server.html_renderer.run("message.html", self.context)

        output.write(html.encode('utf-8'))
        output.seek(0, os.SEEK_END)
        self.send_header('Content-Length', output.tell())
        self.end_headers()

        self.wfile.write(output.getvalue())

    def show_login(self, user=None, msg=None, error=False):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')

        output = BytesIO()

        if user is None:
            user = self.session.get("user")

        self.context.update({"user": user,
               "msg": msg})

        self.context["session_user"] = self.session.get_logged_in("user")
        self.context["user"] = self.session.get("user")

        if error:
            self.context["msg_type"] = _("Error")
        else:
            self.context["msg_type"] = _("Info")

        html = self.server.html_renderer.run("login.html", self.context)

        output.write(html.encode('utf-8'))
        output.seek(0, os.SEEK_END)
        self.send_header('Content-Length', output.tell())
        self.end_headers()

        self.wfile.write(output.getvalue())

    def save_feed_change(self, feed):
        # Re-write file where this feed was read.
        session_user = self.session.get_logged_in("user")
        hist = self.get_history()
        favs = self.get_favorites()
        if feed in hist:
            save_history(hist, settings.get_config_folder(),
                         settings.get_history_filename(session_user))
        elif feed in favs:
            update_favorites(favs,
                             settings.get_config_folder(),
                             settings.get_favorites_filename(session_user))

    def handle_change_css_style(self, query_components):
        try:
            css_style = query_components.get("css_style", [None])[-1]
            if not css_style in CSS_STYLES: # for "None" and wrong values
                css_style = None

            if settings.LOGIN_TYPE is None:
                # Note: This saves not the values permanently, but for this
                # instance. It will be used if no user cookie overwrites the value.
                self.server.html_renderer.extra_context["system_css_style"] = \
                        css_style

            # Use value in this request
            self.context["user_css_style"] = css_style

            # Store value in Cookie for further requests
            self.session.c["css_style"] = css_style
            if not css_style:
                self.session.c["css_style"]["max-age"] = -1
            self.save_session = True

        except KeyError:
                raise Exception("CSS style with this name not defined")

    def reload_favs(self):
        settings.load_default_favs(globals())
        settings.load_users(globals())

    def handle_action(self, query_components):
        try:
            action = settings.ACTIONS[query_components["a"][-1]]
            url = query_components["url"][-1]
            url_hash = query_components["s"][-1]
        except (KeyError, IndexError):
            error_msg = _('URI arguments wrong.')
            return self.show_msg(error_msg, True)

        if self.session.get_logged_in("user") == "":
            error_msg = _('Action requires login. ')
            if settings.LOGIN_TYPE is None:
                error_msg += _("Define LOGIN_TYPE in 'settings.py'. " \
                               "Proper values can be found in " \
                               "'default_settings.py'. ")
            return self.show_msg(error_msg, True)

        url_hash2 = '{}'.format( hashlib.sha224(
            (settings.ACTION_SECRET + url).encode('utf-8')).hexdigest())
        if url_hash != url_hash2:
            error_msg = _('Wrong hash for this url argument.')
            return self.show_msg(error_msg, True)

        # Strip quotes and double quotes from user input
        # for security reasons
        url = url.replace("'","").replace('"','').replace('\\', '')

        if action["check"] is not None:
            if not action["check"](url, settings):
                error_msg = _('Action not allowed for this file.')
                return self.show_msg(error_msg, True)

        try:
            action["handler"](url, settings)
        except KeyError:
                raise Exception("Action not defined")
        except Exception as e:
            error_msg = _('Running of handler for "{action_name}" failed. ' \
                          'Exception was: "{exception}".')\
                    .format(action_name=action, exception=str(e))
            return self.show_msg(error_msg, True)

        # Handling sucessful
        msg = _('Running of "{action_name}" for "{url}" started.') \
                .format(action_name=action["title"], url=url)
        return self.show_msg(msg)

    def handle_login(self, query_components):
        user = query_components.get("user", [""])[-1]
        password = query_components.get("password", [""])[-1]
        logger.debug("User: '{}'".format(user))

        if self.session.init(user, password=password, settings=settings):
            # Omit display of double entries
            if self.get_history() != settings.HISTORY:
                clear_history(self.get_favorites(), self.get_history())

            return self.session_redirect('/')
        else:
            error_msg = _('Login has failed.')
            return self.show_login(user, error_msg, True)

    def handle_logout(self, query_components):
        self.session.uninit()
        return self.session_redirect('/')

    def session_redirect(self, location):
        # Saves login session cookies

        self.send_response(303)
        # self.send_header('Content-type', 'text/html')
        self.session.save()

        self.send_header('Content-Length', 0)
        self.send_header('Location', location)  # Last header!

        """
        output = BytesIO()
        output.write(html.encode('utf-8'))
        output.seek(0, os.SEEK_END)
        self.send_header('Content-Length', output.tell())
        """
        self.end_headers()

        # self.wfile.write(output.getvalue())

# Call 'make ssl' to generate local test certificates.
def wrap_SSL(httpd):
    ssl_path = "."
    httpd.socket = ssl.wrap_socket (
        httpd.socket, server_side=True,
        keyfile=os.path.join(ssl_path, "ssl_rss_server.key"),
        certfile=os.path.join(ssl_path, "ssl_rss_server.crt"),
    )


def set_logger_levels():
    try:
        loglevel = settings.LOGLEVEL
    except AttributeError:
        return

    numeric_level = getattr(logging, loglevel.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError('Invalid log level: %s' % loglevel)

    keys = ["root", "rss_server", "feed", "session", "settings_helper",
            "icon_searcher", "cached_requests"]

    logging.basicConfig(level=numeric_level)
    for key in keys:
        logging.getLogger(key).setLevel(numeric_level)

if __name__ == "__main__":
    settings.load_config(globals())
    settings.load_users(globals())

    logging.config.fileConfig('logging.conf')

    # create logger
    logger = logging.getLogger('rss_server')
    # logging.conf contain levels for each component, but
    # this overrides this values if settings explicit force level
    set_logger_levels()

    find_installed_en_locale()

    if check_process_already_running():
        logger.info("Server process is already running.")
        os._exit(0)

    if "-d" in sys.argv:
        if not daemon_double_fork():
            # Only continue in forked process..
            os._exit(0)

    # Generate secret token if none is given
    if settings.ACTION_SECRET is None:
        settings.ACTION_SECRET = str(randint(0, 1E15))


    # Create empty favorites files if none exists
    if not os.path.lexists(settings.get_favorites_path()):
        update_favorites(settings.FAVORITES,
                         settings.get_config_folder())

    # Omit display of double entries
    clear_history(settings.FAVORITES, settings.HISTORY)

    # Syntax not supported in Python < 3.6
    # with socketserver.TCPServer(("", settings.PORT), MyHandler) as httpd:
    #    httpd.serve_forever()

    try:
        httpd = genMyHTTPServer()((settings.HOST, settings.PORT), MyHandler, settings)
    except OSError:
        # Reset stdout to print messages regardless if daemon or not
        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__
        raise

    if settings.SSL:
        wrap_SSL(httpd)

    if settings.LOGIN_TYPE is None:
        warn( _("Note: Actions for enclosured media files are disabled because LOGIN_TYPE is None."))

    if settings.LOGIN_TYPE == "single_user":
        warn( _("Warning: Without definition of users, everyone " \
                 "with access to this page can add feeds or trigger " \
                 "the associated actions." )
              + _("This could be dangerous if you use user defined actions. "))

    if settings.LOGIN_TYPE in ["users", "pam"] and not settings.SSL:
        warn( _("Warning: Without SSL login credentials aren't encrypted. ")
              + _("This could be dangerous if you use user defined actions. "))

    logger.info("Serving at port {}".format(settings.PORT))
    logger.info("Use {host}:{port}/?feed=[url] to view feed".format(
        host=settings.HOST, port=settings.PORT))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()
    except:
        httpd.shutdown()
        raise

    logger.info("END program")
