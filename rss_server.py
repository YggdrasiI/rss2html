#!/usr/bin/python3
# -*- coding: utf-8 -*-

import sys
import os.path
from datetime import datetime  # , timedelta, timezone
from xml.etree import ElementTree

from urllib.parse import urlparse, parse_qs, quote, unquote
from threading import Thread
import http.server
from http import cookies
import hashlib
import socket
import socketserver
from io import BytesIO
import locale
from time import sleep
from random import randint
from warnings import warn
# from importlib import reload
import ssl
from enum import Enum, auto

#from gettext import gettext as _
from locale_gettext import gettext as _, set_gettext
# from jina2.utils import unicode_urlencode as urlencode

from feed import Feed, get_feed, save_history, clear_history, update_favorites
import feed_parser

import templates
import default_settings as settings  # Overriden in load_config()
import icon_searcher
import cached_requests

from session import LoginType, init_session

from static_content import action_icon_dummy_classes


import logging
import logging.config
logging.config.fileConfig('logging.conf')

'''logging.root.setLevel(logging.NOTSET)
logging.root.setLevel(0)
logging.basicConfig(level=0)'''
logger = None


CSS_STYLES = {
    "default.css": _("Default theme"),
    "light.css": _("Light theme"),
    "dark.css": _("Dark theme"),
}

XML_NAMESPACES = {'content': 'http://purl.org/rss/1.0/modules/content/',
                  'atom': 'http://www.w3.org/2005/AtomX',
                  'atom10': 'http://www.w3.org/2005/Atom',
                 }

class ViewType(Enum):
    INDEX_PAGE = auto()
    ADD_FAVS = auto()
    REMOVE_FEED = auto()
    QUIT = auto()
    RELOAD = auto()
    LOGIN = auto()
    LOGOUT = auto()
    SHOW_LOGIN = auto()
    CHANGE_STYLE = auto()
    USER_ACTION = auto()
    SHOW_FEED = auto()
    SHOW_FEED_FROM_FILE = auto()
    ACTION_ICONS_CSS = auto()
    SYSTEM_ICON = auto()
    PROVIDE_FILE = auto()

# TIMEZONE = str(datetime.now(timezone(timedelta(0))).astimezone().tzinfo)
# DATE_HEADER_FORMAT = "%a, %d %h %Y %T {}".format(TIMEZONE)

def check_process_already_running():
    # from tendo import singleton  # hm, to much dependencies
    # try:
    #     me = singleton.SingleInstance() # will sys.exit(-1) if other instance is running
    # except SingleInstanceException:
    #     return True

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


def load_xml(filepath):
    # Reads file as byte string to match type of urllib3 response data
    with open(filepath, 'rb') as f:
        byte_str = f.read(-1)
        return byte_str

    return None

def qget(query_components, key, default_value=None):
    # Helper function to return latest value of "?key=&key=" queries
    # or default value.
    #
    # query_component is of type(parse_qs(content))
    return query_components.get(key, [default_value])[-1]

def genMyHTTPServer():
# The definition of the MyTCPServer class is wrapped
# because settings module only maps to the correct module
# at runtime (after load_config() call).
# At compile time it maps on 'default_settings'.

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

        request_queue_size = 100

        def __init__(self, *largs, **kwargs):
            super().__init__(*largs, **kwargs)
            self.html_renderer.extra_context["login_type"] = \
                    settings.LOGIN_TYPE

        def server_bind(self):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket.bind(self.server_address)

    return _MyHTTPServer


class MyHandler(http.server.SimpleHTTPRequestHandler):
    server_version = "RSS_Server/0.2"

    # Note: ETag ignored for 1.0, but protcol version 1.1
    # requires header 'Content-Length' for all requests. Otherwise,
    # the browsers will wait forever for more data...
    #
    # ETag in FF still ignored
    ## protocol_version = "HTTP/1.1"
    protocol_version = 'HTTP/1.1'


    # directory="rss_server-page"  # for Python 3.4

    def __init__(self, *largs, **kwargs):
        self.session = init_session(self, settings)

        # Flag to send session cookies without login form.
        # The header info will send for visit of index- or feed-page.
        self.save_session = False
        self.context = {}

        # super().__init__(*largs, **kwargs)  # for Python 3.4
        super().__init__(*largs, directory="rss_server-page", **kwargs)

    def end_headers(self):
        # Add HTTP/1.1 header data required for each request.
        # Pipelining of multiple requests not supported.
        self.send_header('Keep-Alive', 'timeout=0, max=0')
        # self.send_header('Expires', self.date_time_string(1695975089))
        super().end_headers()


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
                logging.info("Remove feed '{}' from history.".format(feed))
                try:
                    hist.remove(feed)
                except ValueError:
                    logging.debug("Removing of feed '{}' from history" \
                                  "failed.".format(feed))

            (fav_feed, _) = get_feed(feed_key, favs)
            if not fav_feed:  # Add if not already in FAVORITES
                logging.info("Add feed '{}' to favorites.".format(feed))
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

    def eval_gui_lang(self, avail_langs=None):
        if not avail_langs:
            avail_langs = templates.HtmlRenderer.list_of_available_locales

        session_lang = self.session.get("lang")
        if session_lang in avail_langs:
            return session_lang

        # Example header: Accept-Language: de,en-US;q=0.7,en;q=0.3
        # Assume descending ordering of q=-weights, so we can select first hit.
        header_langs = self.headers.get("Accept-Language")
        if header_langs:
            for _lang in header_langs.split(","):
                _q = _lang.split(";q=")
                lang = _q[0]
                match_prefix = [alang for alang in avail_langs if
                                alang.startswith(lang)]
                if len(match_prefix) > 0:
                    # Save value in session to avoid re-evaluation
                    self.session.c["lang"] = match_prefix[0]
                    self.session.c["lang"]["max-age"] = 86000
                    try:
                        self.session.c["lang"]["samesite"] = "Strict"
                    except cookies.CookieError:
                        pass  # Requires Python >= 3.8

                    self.save_session = True
                    return match_prefix[0]

        return settings.GUI_LANG



    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        content = self.rfile.read(content_length).decode('utf-8')
        query_components = parse_qs(content)

        if self.path == "/login" or \
           "login" in query_components.get("form_id", []):
            return self.handle_login(query_components)

        if self.path == "/logout" or \
           "logout" in query_components.get("form_id", []):
            return self.handle_logout(query_components)

        msg = 'Post values: {}'.format(str(query_components))
        return self.show_msg(msg)

    def do_GET(self):

        self.session.load()
        self.save_session = False  # To send session headers without login form.

        if settings._LOGIN_TYPE == LoginType.SINGLE_USER and \
           not self.session.get("user"):
            logger.debug("Generate new ID for default user!")
            # Login as "default" user and trigger send of headers
            if self.session.init(user="default"):
                # return self.session_redirect(self.path)
                self.save_session = True

        session_user = self.session.get_logged_in("user")
        self.context["gui_lang"] = self.eval_gui_lang()

        # for CSS menus (onclick3.css, onclick3_actions.css)
        self.context["menu_animation_cls"] = (
                "animated"
                if settings.DETAIL_PAGE_ANIMATED else
                "not_animated")


        # User CSS-Style can overwrite server value
        user_css_style = self.session.get("css_style")
        if user_css_style and user_css_style in CSS_STYLES:
            self.context["user_css_style"] = user_css_style

        # Switch _ to language of request.
        # (Note: In templates Jinja2 translates, but not
        # in _("") calls in the py's files itself.)
        set_gettext(self.server.html_renderer, self.context)

        query_components = parse_qs(urlparse(self.path).query)
        view = self.eval_view(self.path, query_components)

        ret = self.error_page_if_login_required(view)
        if ret:
            return ret

        if view == ViewType.QUIT:
            return self.handle_quit()
        if view == ViewType.ADD_FAVS:
            add_favs = query_components.get("add_fav", [])  # List!
            self.do_add_favs(add_favs)
            return self.session_redirect('/')
        if view == ViewType.REMOVE_FEED:
            to_rm = query_components.get("rm", [])          # List!
            self.do_rm_feed(to_rm)
            return self.session_redirect('/')
        elif view == ViewType.RELOAD:
            self.reload_favs()
            return self.session_redirect('/')
        elif view == ViewType.LOGIN:
            return self.handle_login(query_components)
        elif view == ViewType.SHOW_LOGIN:
            return self.show_login()
        elif view == ViewType.LOGOUT:
            return self.handle_logout(query_components)
        elif view == ViewType.CHANGE_STYLE:
            self.handle_change_css_style(query_components)
            return self.session_redirect('/')
        elif view == ViewType.USER_ACTION:
            return self.handle_action(query_components)
        elif view == ViewType.SHOW_FEED:
            return self.handle_show_feed(query_components)
        elif view == ViewType.SHOW_FEED_FROM_FILE:
            return self.handle_show_feed_from_file(query_components)
        elif view == ViewType.ACTION_ICONS_CSS:
            return action_icon_dummy_classes(self)
        elif view == ViewType.SYSTEM_ICON:
            return self.system_icon(self)
        elif view == ViewType.INDEX_PAGE:
            return self.write_index()
        elif view == ViewType.PROVIDE_FILE:
            # self.path = MyHandler.directory + self.path  # for Python 3.4
            return super().do_GET()
        else:
            print(self.path)
            # return super().do_GET()
            return self.send_error(404)

    def eval_view(self, path, query_components):
        # eval handler for do_GET operation

        session_user = self.session.get_logged_in("user")

        feed_key = qget(query_components, "feed")  # key, url or feed title
        filepath = qget(query_components, "file")  # From 'open with' dialog
        #add_favs = query_components.get("add_fav", [])  # List!
        #to_rm = query_components.get("rm", [])          # List!

        if "add_fav" in query_components:
            return ViewType.ADD_FAVS

        if "rm" in query_components:
            return ViewType.REMOVE_FEED

        if self.path == "/quit":
            return ViewType.QUIT
        elif self.path == "/reload":
            return ViewType.RELOAD
        elif self.path.startswith("/login?"):
            return ViewType.LOGIN
        elif self.path == "/login":
            return ViewType.SHOW_LOGIN
        elif self.path ==  "/logout":
            return ViewType.SHOW_LOGOUT
        elif self.path.startswith("/change_style"):
            return ViewType.CHANGE_STYLE
        elif self.path.startswith("/action"):
            return ViewType.USER_ACTION
        elif feed_key:
            return ViewType.SHOW_FEED
        elif filepath:
            return ViewType.SHOW_FEED_FROM_FILE
        elif self.path == "/css/action_icons.css":
            return ViewType.ACTION_ICONS_CSS
        elif self.path.startswith("/icons/system/"):
            return ViewType.SYSTEM_ICON
        elif self.path in ["/", "/index.html"]:
            return ViewType.INDEX_PAGE
        elif os.path.splitext(urlparse(self.path).path)[1] in \
                settings.ALLOWED_FILE_EXTENSIONS:
            return ViewType.PROVIDE_FILE
        elif self.path == "/robots.txt":
            return ViewType.PROVIDE_FILE
        else:
            return None

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

        html = self.server.html_renderer.run("index.html", self.context)

        output = BytesIO()
        output.write(html.encode('utf-8'))
        output.seek(0, os.SEEK_END)  # As reminder…

        # Etag
        etag = '"{}"'.format( hashlib.sha1(output.getvalue()).hexdigest())
        browser_etag = self.headers.get("If-None-Match", "")

        # logger.debug("\n\nETag of index page: {}".format(etag))
        # logger.debug("ETag from client:   {}\n\n".format(browser_etag))

        if etag == browser_etag and not self.save_session:
            self.send_response(304)
            self.send_header('ETag', etag)
            # self.send_header('Cache-Control', 'public, max-age=10, ')
            self.send_header('Cache-Control', 'max-age=0, public ')
                            # "must-revalidate, post-check=0, pre-check=0")
            self.send_header('Content-Location', '/index.html')
            self.send_header('Vary', 'User-Agent')
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
        # self.send_header('Cache-Control', 'public')
        self.send_header('Cache-Control', 'max-age=60, public')
        self.send_header('Content-Location', '/index.html')
        #self.send_header('Content-Location', '/{}.html'.format(etag))

        # tmp_date = datetime.utcnow()
        # Das führt zu doppeltem Date-Header!
        # self.send_header('Date', tmp_date.strftime(DATE_HEADER_FORMAT))

        # tmp_date += timedelta(seconds=1000060)
        # self.send_header('Expires', tmp_date.strftime(DATE_HEADER_FORMAT))
        #... Expires ignored if max-age is given. Added to check effect on ETag feature
        self.send_header('Vary', 'User-Agent')

        # For Safari
        # tmp_date += timedelta(seconds=-120)
        # self.send_header('Last-Modified', tmp_date.strftime(DATE_HEADER_FORMAT))
        # self.send_header('Cache-Control', 'max-age=0, must-revalidate')
        # self.send_header('Expires', '-1')

        if self.save_session:
            self.session.save()

        # Other headers
        self.send_header('Content-Length', output.tell())
        self.send_header('Content-type', 'text/html')
        self.end_headers()

        self.wfile.write(output.getvalue())

    def show_msg(self, msg, error=False, minimal=False):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')

        self.context.update({
            "msg": msg,
        })

        self.context["session_user"] = self.session.get_logged_in("user")

        output = BytesIO()
        if error:
            self.context["msg_type"] = _("Error")
        else:
            self.context["msg_type"] = _("Debug Info")

        if minimal:
            html = self.server.html_renderer.run("message_minimal.html", self.context)
        else:
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
            css_style = qget(query_components, "css_style", None)
            if not css_style in CSS_STYLES:  # for "None" and wrong values
                css_style = None

            if css_style == "default.css":
                # Do not save the style in cookie/renderer if it's already
                # the value which will provided anyway.
                css_style = None

            if settings._LOGIN_TYPE is LoginType.NONE:
                # Note: This saves not the values permanently, but for this
                # instance. It will be used if no user cookie overwrites the value.
                self.server.html_renderer.extra_context["system_css_style"] = \
                        css_style

            # Use value in this request
            self.context["user_css_style"] = css_style

            # Store value in Cookie for further requests
            self.session.c["css_style"] = css_style
            try:
                self.session.c["css_style"]["samesite"] = "Strict"
            except cookies.CookieError:
                pass  # Requires Python >= 3.8

            if not css_style:
                self.session.c["css_style"]["max-age"] = -1
            self.save_session = True

        except KeyError:
                raise Exception("CSS style with this name not defined")

    def handle_show_feed(self, query_components):
        session_user = self.session.get_logged_in("user", "")

        feed_key = qget(query_components, "feed")  # key, url or feed title
        bUseCache = (qget(query_components, "cache", "1") != "0")
        url_update = (qget(query_components, "url_update", "0") != "0")
        try:
            feed = get_feed(feed_key,
                            self.get_favorites(),
                            self.get_history())[0]
            feed_url = feed.url if feed else feed_key

            res = None
            (cEl, code) = cached_requests.fetch_file(
                    feed_url, bUseCache, self.directory)

            if cEl is None:
                if code == 500:
                    error_msg = _('Cannot fetch data for this feed.')
                else:
                    error_msg = _('No feed found for this URI arguments.')
                return self.show_msg(error_msg, True)

            # Parse 'page' uri argument (affects etag!)
            page = int(query_components.setdefault("page", ['1'])[-1])

            # Generate etag
            etag = '"{}p{}"'.format(
                hashlib.sha1((cEl.byte_str if cEl.byte_str is not None \
                              else "")).hexdigest(),
                page
            )
            #logger.debug("Eval ETag '{}'".format(etag))
            #logger.debug("Browser ETag '{}'".format(self.headers.get("If-None-Match", "")))
            # logger.debug("Received headers:\n{}".format(self.headers))

            # If feed is unchanged and tags match return nothing, but 304.
            if code == 304 and self.headers.get("If-None-Match", "") == etag:
                self.send_response(304)
                self.send_header('ETag', etag)
                self.send_header('Cache-Control', "public, max-age=10, ")
                        # "must-revalidate, post-check=0, pre-check=0")
                self.send_header('Vary', "ETag, User-Agent")
                self.end_headers()
                return None

            if not feed:
                feed = Feed("", feed_url)
                bNew = True
            else:
                bNew = False

            if code == 304 and len(feed.context)>0:
                logger.debug("Skip parsing of feed and re-use previous")
            elif not feed_parser.parse_feed(feed, cEl.byte_str):
                error_msg = _('Parsing of Feed XML failed.')
                return self.show_msg(error_msg, True)

            # Note: without copy, changes like warnings on res
            # would be stored peristend into feed.context.
            res = feed.context.copy()

            # Select displayed range of feed entries
            if settings.ENTRIES_PER_PAGE > 0:
                res["entry_list_first_id"] = (page-1) * \
                        settings.ENTRIES_PER_PAGE

                # feed.context["query_components"] = query_components
                res["feed_page"] = page

            self.update_cache_feed(feed, bNew)

            # Warn if feed url might changes
            parsed_feed_url = res["href"]
            if (not url_update and parsed_feed_url
                and parsed_feed_url != feed_url):
                res.setdefault("warnings", []).append({
                    "title": _("Warning"),
                    "msg": _(
                        """Feed url difference detected. It might
                        be useful to <a href="/?{ARGS}&url_update=1">update</a> \
                        the stored url.<br /> \
                        Url in config/history file: {OLD_URL}<br /> \
                        Url in feed xml file: {NEW_URL} \
                        """).format(OLD_URL=feed_url,
                                    NEW_URL=parsed_feed_url,
                                    ARGS="feed=" + quote(str(feed_key)),
                                   )
                })

            res["nocache_link"] = True
            res["session_user"] = session_user

            # Replace stored url, if newer value is given.
            if feed and url_update and res["href"]:
                feed_url = feed.url
                feed.url = res["href"]
                feed.title = res.get("title", feed.title)
                self.save_feed_change(feed)

            if False:  #  entryid
                html = "TODO"
            else:
                context = {}
                context.update(self.context)
                context.update(res)
                html = self.server.html_renderer.run("feed.html", context)

        except ValueError as e:
            error_msg = str(e)
            return self.show_msg(error_msg, True)
        except:
            raise
        else:
            return self.show_feed(html)


    def handle_show_feed_from_file(self, query_components):
        session_user = self.session.get_logged_in("user", "")

        filepath = qget(query_components, "file")  # From 'open with' dialog
        # No cache read in this variant
        try:
            www_dir = os.path.realpath(self.directory)
            if os.path.isabs(filepath):
                feed_filepath = filepath
            else:
                feed_filepath = os.path.join(www_dir, filepath)
                feed_filepath = os.path.realpath(feed_filepath)

            if not feed_filepath.startswith(www_dir):
                logger.debug("Datei NICHT aus www-Dir")

            # TODO: Restrict reading on several allowed paths here?!
            # Currently only the failing parsing below prevents users
            # from reading arbitary files.
            logger.debug("Read {}".format(feed_filepath))

            try:
                byte_str = load_xml(feed_filepath)

                feed_new = Feed("", filepath)
                if not feed_parser.parse_feed(feed_new, byte_str):
                    error_msg = _('Parsing of Feed XML failed.')
                    return self.show_msg(error_msg, True)

            except FileNotFoundError:
                error_msg = _("Feed XML document '{}' does not " \
                              "exists.".format(filepath))
                return self.show_msg(error_msg, True)
            except ElementTree.ParseError:
                error_msg = _("Parsing of feed XML document '{}' " \
                              "failed.".format(filepath))
                return self.show_msg(error_msg, True)
            except Exception as e:
                # raise(e)
                error_msg = _("Loading of feed XML document '{}' " \
                              "failed.".format(filepath))
                return self.show_msg(error_msg, True)

            # res = find_feed_keyword_values(tree)
            res = feed_new.context

            self.update_cache_filepath(feed_new, byte_str)
            res["nocache_link"] = res["title"]
            res["session_user"] = session_user

            context = {}
            context.update(self.context)
            context.update(res)
            html = self.server.html_renderer.run("feed.html", context)

        except ValueError as e:
            error_msg = str(e)
            return self.show_msg(error_msg, True)
        except:
            raise
        else:
            return self.show_feed(html)


    def show_feed(self, html, etag=None):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.send_header('Cache-Control', "public, max-age=10, ")
        if etag:
            # logger.debug("Add ETag '{}'".format(etag))
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

    def system_icon(self):
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


    def error_page_if_login_required(self, view):
        session_user = self.session.get_logged_in("user", "")
        _no_login_required = []
        return None
        if session_user == "" and view not in _no_login_required:
            error_msg = _('Login required.')
            return self.show_msg(error_msg, True)

        return None


    def handle_quit(self):
        ret = self.show_msg(_("Quit"))

        def __delayed_shutdown():
            sleep(1.0)
            self.server.shutdown()

        t = Thread(target=__delayed_shutdown)
        t.daemon = True
        t.start()
        return ret

    def reload_favs(self):
        settings.load_default_favs(globals())
        settings.load_users(globals())

    def handle_action(self, query_components):
        minimal = (False
                if qget(query_components, "js", "0") != "0"
                else True)
        already_send = False  # mutex for multithreaded handling
        try:
            aname = query_components["a"][-1]
            url = unquote(query_components["url"][-1])
            feed_name = unquote(qget(query_components, "feed", ""))
            url_hash = query_components["s"][-1]
            action = settings.ACTIONS[aname]

        except (KeyError, IndexError):
            error_msg = _('URI arguments wrong.')
            return self.show_msg(error_msg, True, minimal)

        if self.session.get_logged_in("user") == "":
            error_msg = _('Action requires login. ')
            if settings._LOGIN_TYPE is LoginType.NONE:
                error_msg += _("Define LOGIN_TYPE in 'settings.py'. " \
                               "Proper values can be found in " \
                               "'default_settings.py'. ")
            return self.show_msg(error_msg, True, minimal)

        # Check if url args were manipulated
        url2 = url.replace("&js=1", "") # ignore flag added by js
        url_hash2 = '{}'.format( hashlib.sha224(
            (settings.ACTION_SECRET + url2 + aname).encode('utf-8')
        ).hexdigest())
        if url_hash != url_hash2:
            error_msg = _('Wrong hash for this url argument.')
            return self.show_msg(error_msg, True, minimal)

        # Strip quotes and double quotes from user input
        # for security reasons
        url = url.replace("'","").replace('"','').replace('\\', '')

        # Get feed for this action (to eval download folder name, etc.)
        feed = get_feed(feed_name,
                        self.get_favorites(),
                        self.get_history())[0]
        if not feed:
            error_msg = _('No feed found for given URI argument.')
            return self.show_msg(error_msg, True, minimal)

        # Print error if pre-check of action fails
        if action.get("check") is not None:
            check = action["check"]
            try:
                if not check(feed, url, settings):
                    error_msg = _('Action not allowed for this file.')
                    return self.show_msg(error_msg, True, minimal)
            except Exception as e:
                logger.debug("check-Handler of '{aname}' failed. " \
                             "Exception was: '{e}'.".format(aname=aname, e=e))
                error_msg = _('Action not allowed for this file.')
                return self.show_msg(error_msg, True, minimal)

        try:
            handler = action["handler"]
        except KeyError:
            logger.debug("Handler of action '{aname}' not defined." \
                         .format(aname))
            error_msg = _("Handler of action not defined.")
            return self.show_msg(error_msg, True, minimal)

        try:
            handler(feed, url, settings)
        except Exception as e:
            error_msg = _('Running of handler for "{action_name}" failed. ' \
                          'Exception was: "{e}".')\
                    .format(action_name=action, e=e)
            print(error_msg)
            # Hm, durchs forken kann hier eine (zweite Antwort
            # geschrieben werden obwohl die Antwort weiter unten
            # schon gesendet wurde...?!
            if not already_send:
                already_send = True
            return self.show_msg(error_msg, True, minimal)

        # Handling sucessful
        sleep(2.0)
        if not already_send:
            msg = _('Running of "{action_name}" for "{url}" started.') \
                    .format(action_name=action["title"], url=url)
            already_send = True
            return self.show_msg(msg, False, minimal)

    def handle_login(self, query_components):
        user = qget(query_components, "user", "")
        password = qget(query_components, "password", "")
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

    def update_cache_feed(self, feed_new, bNew):
        """ Update cache and history """

        res = feed_new.context
        if bNew:
            session_user = self.session.get_logged_in("user")
            # Add this (new) url to feed history.
            hist = self.get_history()
            # feed_title = res["title"]
            # hist.append(Feed(feed_title, feed.url, feed_title))
            hist.append(feed_new)
            save_history(hist, settings.get_config_folder(),
                         settings.get_history_filename(session_user))


    def update_cache_filepath(self, feed_new, byte_str):
        """ Update cache and history and old feed entry, if found."""

        res = feed_new.context
        # 1. Find feed with same title
        feed = get_feed(res["title"],
                        self.get_favorites(),
                        self.get_history())[0]

        # 2. Update favorites/history files.
        if feed:
            # The feed name (human), uid (machine) acts as unique keys.
            # Replace feed with feed_new, but transfer
            # this fields into new instance
            feed_new.name = feed.name
            feed_new._uid = feed._uid

            # If a new url is found, save feed immediately, but not
            # at end of program.
            parsed_feed_url = res["href"]
            if parsed_feed_url and parsed_feed_url != feed.url:
                self.save_feed_change(feed_new)

            feed = feed_new
        else:

            # Extract feed url from xml data because no url is
            # given directly if file was loaded from disk.
            url = res.get("href", "")

            # Update other values.
            title = res.get("title", feed_new.title)
            name = feed_new.name
            if name == "" and title:
                name = title

            # Create new instance. This will generate a proper uid
            # from url/name
            feed = Feed(name, url, title=title)
            feed.context = res

            # A new feed can not be found in favorites.
            # Save it into the history file.
            session_user = self.session.get_logged_in("user")
            hist = self.get_history()
            hist.append(feed)
            save_history(hist, settings.get_config_folder(),
                         settings.get_history_filename(session_user))

        # 3. Write changes in cache.
        # Note that this clears saved headers for this feed.
        cEl =  cached_requests.CacheElement.from_bytes(byte_str)
        cached_requests.update_cache(feed.cache_name(), cEl)


# Call 'make ssl' to generate local test certificates.
def wrap_SSL(httpd, key_file, crt_file):
    ssl_path = "."
    httpd.socket = ssl.wrap_socket (
        httpd.socket, server_side=True,
        keyfile=os.path.join(ssl_path, key_file),
        certfile=os.path.join(ssl_path, crt_file),
    )


def set_logger_levels():
    try:
        loglevel = settings.LOGLEVEL
    except AttributeError:
        return

    numeric_level = getattr(logging, loglevel.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError('Invalid log level: {}'.format(loglevel))

    keys = list(logging.root.manager.loggerDict.keys())
    keys.insert(0, "root")
    # print("Logger keys: {}".format(keys))

    print("Set logging level on {}".format(numeric_level))
    logging.basicConfig(level=numeric_level)
    for key in keys:
        logging.getLogger(key).setLevel(numeric_level)


if __name__ == "__main__":
    # create logger
    logger = logging.getLogger('rss_server')

    settings.load_config(globals())
    settings.load_users(globals())

    # Overwrite 'settings' in other modules, too.
    settings.update_submodules(globals())

    # logging.conf already contain levels for each component, but
    # settings could override this by a global value
    set_logger_levels()

    feed_parser.find_installed_en_locale()

    if not ("-m" in sys.argv or "--multiple" in sys.argv):
        if check_process_already_running():
            logger.info("Server process is already running.")
            os._exit(0)

    if "-d" in sys.argv or "--daemon" in sys.argv:
        if not daemon_double_fork():
            # Only continue in forked process..
            os._exit(0)

    # Create empty favorites files if none exists
    if not os.path.lexists(settings.get_favorites_path()):
        update_favorites(settings.FAVORITES,
                         settings.get_config_folder())

    # Omit display of double entries
    clear_history(settings.FAVORITES, settings.HISTORY)

    # Syntax not supported in Python < 3.6
    # with socketserver.TCPServer(("", settings.PORT), MyHandler) as httpd:
    #    httpd.serve_forever()

    # Preload feed xml files from earlier session
    if settings.CACHE_DIR:
        settings.CACHE_DIR = os.path.expandvars(settings.CACHE_DIR)
        __l1 = len(cached_requests._CACHE)
        cached_requests.gen_cache_dirname(True)
        cached_requests.load_cache(settings.FAVORITES, settings.HISTORY)
        cached_requests.load_cache(*(settings.USER_FAVORITES.values()))
        cached_requests.load_cache(*(settings.USER_HISTORY.values()))
        __l2 = len(cached_requests._CACHE)
        logger.info("Loaded {} feeds from disk into cache.".format(__l2 - __l1))

        cached_requests.trim_cache(force_memory=True, force_disk=False)
        __l3 = len(cached_requests._CACHE)
        logger.info("Trim on {} elements in cache.".format(__l3))

    try:
        httpd = genMyHTTPServer()((settings.HOST, settings.PORT), MyHandler, settings)
    except OSError:
        # Reset stdout to print messages regardless if daemon or not
        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__
        raise

    if settings.SSL:
        wrap_SSL(httpd,
                settings.SSL_KEY_PATH, settings.SSL_CRT_PATH)

    if settings._LOGIN_TYPE is LoginType.NONE:
        warn( _("Note: Actions for enclosured media files are disabled because LOGIN_TYPE is None."))

    if settings._LOGIN_TYPE == LoginType.SINGLE_USER:
        warn( _("Warning: Without definition of users, everyone " \
                 "with access to this page can add feeds or trigger " \
                 "the associated actions." )
              + _("This could be dangerous if you use user defined actions. "))

    if settings._LOGIN_TYPE in [LoginType.USERS] and not settings.SSL:
        warn( _("Warning: Without SSL login credentials aren't encrypted. ")
              + _("This could be dangerous if you use user defined actions. "))

    logger.info("Serving at port {}".format(settings.PORT))
    logger.info("Use {protocol}{host}:{port}/?feed=[url] to view feed".format(
        protocol="https://" if settings.SSL else "http://",
        host=settings.HOST if settings.HOST else "localhost",
        port=settings.PORT))

    restart_service = True

    # Sometimes, external request spamming leads to a failure
    # of the http service after a few days.
    # The service will be blocked by the OS until we restart it.
    # As workaround, I added a loop to periodical restart the service..
    def __shutdown_and_serve_again():
        while True:
            sleep(3600.0)
            logger.info("Periodical restart of http service at port {}"
                    .format(settings.PORT))
            global restart_service
            restart_service = True
            httpd.shutdown()

            # Cache cleanup
            cached_requests.trim_cache()  # Currently redundant

    t = Thread(target=__shutdown_and_serve_again)
    t.daemon = True
    t.start()

    while restart_service:
        restart_service = False
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            httpd.shutdown()
        except:
            httpd.shutdown()
            raise

    if settings.CACHE_DIR:
        logger.info("Save cache on disk")
        cached_requests.store_cache(settings.FAVORITES, settings.HISTORY)
        cached_requests.store_cache(*(settings.USER_FAVORITES.values()))
        cached_requests.store_cache(*(settings.USER_HISTORY.values()))

    logger.info("END program")
