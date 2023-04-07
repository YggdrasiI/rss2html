#!/usr/bin/python3
# -*- coding: utf-8 -*-

import sys
import os.path
import argparse
from datetime import datetime  # , timedelta, timezone

try:
    from defusedxml import ElementTree
except ImportError:
    from xml.etree import ElementTree

from urllib.parse import urlparse, parse_qs, quote, unquote
from threading import Thread, Lock
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

import json  # To parse application/json -requests

#from gettext import gettext as _
from .locale_gettext import gettext as _, set_gettext
# from jina2.utils import unicode_urlencode as urlencode

from multiprocessing import set_start_method

import logging

'''logging.root.setLevel(logging.NOTSET)
logging.root.setLevel(0)
logging.basicConfig(level=0)'''
logger = logging.getLogger('rss_server')

from . import default_settings as settings  # Overriden in load_config()
settings_mutex = Lock()

from .feed import Feed, Group, get_feed, save_history, clear_history, update_favorites
from .httpcompressionserver import *
from . import feed_parser
from . import templates
from . import icon_searcher
from . import cached_requests

from .session import LoginType, init_session

from .static_content import action_icon_dummy_classes

from .actions import worker_handler, PickableAction, PopenArgs, factory__local_cmd
from .actions_pool import ActionPool

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
    SHOW_EXTRAS = auto()
    YT_SCRIPT = auto()

# To spawn actions of users a pool of processes is used
actions_pool = None

# TIMEZONE = str(datetime.now(timezone(timedelta(0))).astimezone().tzinfo)
# DATE_HEADER_FORMAT = "%a, %d %h %Y %T {}".format(TIMEZONE)

HIST_GROUP_NAME = "__others"

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

    ServerClass = ThreadingHTTPServer
    """
    if hasattr(http.server, "ThreadingHTTPServer"):
        ServerClass = http.server.ThreadingHTTPServer
    else:
        ServerClass = socketserver.TCPServer
    """

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
            # Saves processed form id to avoid multiple handling
            self.form_ids = []

            # Saves user etags for some pages for 304 messages
            self.latest_etags = {}


        def server_bind(self):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket.bind(self.server_address)


    return _MyHTTPServer


class MyHandler(HTTPCompressionRequestHandler):
    server_version = "RSS_Server/0.3"

    # protocol_version = 'HTTP/1.1'

    def __init__(self, *largs, **kwargs):
        self.session = init_session(self, settings)

        # Flag to send session cookies without login form.
        # The header info will send for visit of index- or feed-page.
        self.save_session = False
        self.session_user = None
        self.context = {}

        # Root dir of server is inside of package
        www_dir = os.path.join(os.path.dirname(__file__),
                               "rss_server-page")

        super().__init__(*largs, directory=www_dir, **kwargs)

    def end_headers(self):
        # Add HTTP/1.1 header data required for each request.
        # Pipelining of multiple requests not supported.
        self.send_header('Keep-Alive', 'timeout=0, max=0') # TODO
        # https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Keep-Alive
        # self.send_header('Expires', self.date_time_string(1695975089))
        super().end_headers()


    def get_favorites(self):
        # session_user = self.session.get_logged_in("user")
        return settings.USER_FAVORITES.get(self.session_user,
                                           settings.FAVORITES)

    def get_history(self):
        # session_user = self.session.get_logged_in("user")
        return settings.USER_HISTORY.get(self.session_user,
                                         settings.HISTORY)

    def get_group(self, group_name):
        favs = self.get_favorites()
        for g in favs:
            if g.name == group_name:
                return g
        return None

    def set_favorites(self, favs):
        if favs == self.get_favorites():
            return

        # session_user = self.session.get_logged_in("user")
        logger.info("Save favs for session_user '{}'".format(self.session_user))
        settings.USER_FAVORITES[self.session_user] = favs

    def set_history(self, hist):
        if hist == self.get_history():
            return

        # session_user = self.session.get_logged_in("user")
        logger.info("Save hist for session_user '{}'".format(self.session_user))
        settings.USER_HISTORY[self.session_user] = hist


    def save_favorites(self):
        # session_user = self.session.get_logged_in("user")
        update_favorites(self.get_favorites(),
                         settings.get_config_folder(),
                         settings.get_favorites_filename(self.session_user))

    def save_history(self):
        # session_user = self.session.get_logged_in("user")
        save_history(self.get_history(),
                     settings.get_config_folder(),
                     settings.get_history_filename(self.session_user))

    def set_group(self, group_name, feeds):
        favs = self.get_favorites()
        for g in favs:
            if g.name == group_name:
                if g.feeds == feeds:
                    return  # No change of existing list

                g.feeds = feeds
                break

    def do_add_favs(self, add_favs):
        # session_user = self.session.get_logged_in("user")

        settings_mutex.acquire()
        favs = self.get_favorites()
        hist = self.get_history()
        for feed_key in add_favs:
            # Check for feed with this name
            (feed, parent_list) = get_feed(feed_key, hist)
            if feed:
                logger.info("Remove feed '{}' from history.".format(feed))
                try:
                    #hist.remove(feed)
                    parent_list.remove(feed)
                except ValueError:
                    logger.debug("Removing of feed '{}' from history" \
                                  "failed.".format(feed))

            (fav_feed, _) = get_feed(feed_key, favs)
            if not fav_feed:  # Add if not already in FAVORITES
                logger.info("Add feed '{}' to favorites.".format(feed))
                #favs.append(feed)
                favs.append(Group("TODO: Add to existing group", [feed]))

        update_favorites(favs, settings.get_config_folder(),
                         settings.get_favorites_filename(self.session_user))
        save_history(hist, settings.get_config_folder(),
                     settings.get_history_filename(self.session_user))
        settings_mutex.release()


    def do_rm_feed(self, to_rm):
        # session_user = self.session.get_logged_in("user")
        settings_mutex.acquire()
        favs = self.get_favorites()
        hist = self.get_history()
        for feed_key in to_rm:
            (feed, parent_list) = get_feed(feed_key, favs, hist)

            if parent_list != hist:
                try:
                    parent_list.remove(feed)
                    update_favorites(
                        favs, settings.get_config_folder(),
                        settings.get_favorites_filename(self.session_user))
                except ValueError:
                    pass

            if parent_list == hist:
                try:
                    parent_list.remove(feed)
                    save_history(
                        hist, settings.get_config_folder(),
                        settings.get_history_filename(self.session_user))
                except ValueError:
                    pass

        settings_mutex.release()

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


    def setup_context(self):
        # Called by do_GET, do_POST
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

    def do_POST(self):
        self.session.load()
        self.save_session = False

        self.session_user = self.session.get_logged_in("user")
        self.setup_context()

        content_length = int(self.headers['Content-Length'])
        content = self.rfile.read(content_length).decode('utf-8')

        content_type = self.headers.get("Content-Type","").split(";")[0]
        logger.info(f"do_POST: '{content_type}'\n '{content}'")
        if content_type == "application/json":
            components = json.loads(content)
            # Normalize values as list to get same structure 
            # as parse_qs()-function.
            query_components = {}
            for (k,v) in components.items():
                if isinstance(v, list):
                    query_components[k] = v
                else:
                    query_components.setdefault(k, []).append(v)

        elif content_type == "application/x-www-form-urlencoded":
            query_components = parse_qs(content)
        else:
            logger.info(f"TODO: Fix formular handling. "\
                        "Request includes unsupported content type"\
                        "{content_type}")
            return self.show_msg("Unsupported content_type", True, True)
            
        form_id = qget(query_components, "form_id")
        if not form_id is None:
            if form_id in self.server.form_ids:
                logger.debug("Skip do_POST for id {}".format(form_id))

                # NOTE: 304 for POST request not work as expected
                #       Browser will show empty page.
                if False:
                    self.send_response(304)
                    self.send_header('ETag', "extras_const_etag")
                    self.send_header('Cache-Control', 'max-age=0, private, stale-while-revalidate=86400')
                    self.send_header('Content-Location', '/extras')
                    # self.send_header('Vary', 'User-Agent')
                    self.end_headers()
                    return None
                else:
                    return self.show_msg("This data was already processed.", False)

                # NOTE: Sending 204 would be possible if using PUT
                #       instead of POST?!
                #self.send_response(204)  # No Content, mainly for PUT

            # NOTE: Adding id here does not respect
            #       the result of the formular handling.
            self.server.form_ids.append(form_id)
            if len(self.server.form_ids) > 20:
                self.server.form_ids[:10] = []

        if self.path == "/login" or \
           "login" in query_components.get("form_name", []):
            return self.handle_login(query_components)

        if self.path == "/logout" or \
           "logout" in query_components.get("form_name", []):
            return self.handle_logout(query_components)

        if self.path == "/change_feed_order" or \
           "change_feed_order" in query_components.get("form_name", []):
            return self.handle_change_feed_order(query_components)

        if self.path == "/" or \
                "feed" == qget(query_components, "form_name"):
            # Hm, using POST-method for feed will invoke
            # requests if using back/forward in browser ?!
            # With GET browser will use it's cache.
            return self.handle_show_feed(query_components)

        if self.path == "/extras/yt" or \
                "yt" == qget(query_components, "form_name"):
            return self.handle_youtube(query_components)

        msg = 'Post values: {}'.format(str(query_components))
        return self.show_msg(msg)

    def do_GET(self):

        self.session.load()
        self.save_session = False

        if settings._LOGIN_TYPE == LoginType.SINGLE_USER and \
           not self.session.get("user"):
            logger.debug("Generate new ID for default user!")
            # Login as "default" user and trigger send of headers
            if self.session.init(user="default"):
                # return self.session_redirect(self.path)
                self.save_session = True

        self.session_user = self.session.get_logged_in("user")
        self.setup_context()

        query_components = parse_qs(urlparse(self.path).query)
        view = self.eval_view(self.path, query_components)

        if self.login_required_for_page(view):
            error_msg = _('Login required.')
            return self.show_msg(error_msg, True)

        if view == ViewType.QUIT:
            return self.handle_quit()
        if view == ViewType.ADD_FAVS:
            add_favs = query_components.get("add_fav", [])  # List!
            self.do_add_favs(add_favs)
            self.set_etag('/index.html', None)
            return self.session_redirect('/')
        if view == ViewType.REMOVE_FEED:
            to_rm = query_components.get("rm", [])          # List!
            self.do_rm_feed(to_rm)
            self.set_etag('/index.html', None)
            return self.session_redirect('/')
        elif view == ViewType.RELOAD:
            self.reload_favs()
            self.set_etag('index.html', None)
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
            return self.system_icon()
        elif view == ViewType.INDEX_PAGE:
            return self.write_index()
        elif view == ViewType.SHOW_EXTRAS:
            return self.show_extras()
        elif view == ViewType.YT_SCRIPT:
            return self.handle_youtube(query_components)
        elif view == ViewType.PROVIDE_FILE:
            # self.path = MyHandler.directory + self.path  # for Python 3.4
            self.log_message("Provide %s", self.path)
            return super().do_GET()
        else:
            self.log_message("Skip %s", self.path)
            # return super().do_GET()
            return self.send_error(404)

    def eval_view(self, path, query_components):
        # eval handler for do_GET operation

        # session_user = self.session.get_logged_in("user")

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
            return ViewType.LOGOUT  # redirects on index page
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
        elif self.path.startswith("/extras"):
            if not settings.ENABLE_EXTRAS:
                return None
            if self.path.startswith("/extras/yt?"):
                return ViewType.YT_SCRIPT
            return ViewType.SHOW_EXTRAS
        elif os.path.splitext(urlparse(self.path).path)[1] in \
                settings.ALLOWED_FILE_EXTENSIONS:
            return ViewType.PROVIDE_FILE
        elif self.path == "/robots.txt":
            return ViewType.PROVIDE_FILE
        else:
            return None

    def get_etag(self, location):
        etag = self.server.latest_etags.get(self.session_user,{}).get(location)
        return etag

    def set_etag(self, location, etag):
        self.server.latest_etags.setdefault(self.session_user,{})[location] = etag

    def _write_1_1(self, s, etag=None, location=None, max_age=None):
        """ Encoding given string, sets Content-Length header
            and writing s into response.

            Setting the Content-Length header is required for HTTP/1.1.
        """
        output = BytesIO()
        output.write(s.encode('utf-8'))
        output.seek(0, os.SEEK_END)
        self.send_header('Content-Length', output.tell())
        if max_age:
            self.send_header('Cache-Control', f'max-age={max_age}, private, stale-while-revalidate=86400')
        if location:
            self.send_header('Content-Location', location)

        # Preparation for 304 replys....
        if etag:
            if etag is True:
                etag = '"{}"'.format( hashlib.sha1(output.getvalue()).hexdigest())
            self.send_header('ETag', etag)

            # Update etag for this user
            if location:
                self.set_etag(location, etag)

        self.end_headers()

        self.wfile.write(output.getvalue())

    def _write_304(self, etag, location=None, max_age=None):
        # Write 304 header information and finish response.
        #
        # Regarding to
        # https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/304
        # following headers hast to be set in 304 again if 
        # previously added to the 200-response
        # Cache-Control, Content-Location, Date (is already included),
        # ETag, Expires (overwritten by max-age, but still required?!)
        # and Vary.
        self.send_response(304)
        self.send_header('ETag', etag)
        if max_age:
            self.send_header('Cache-Control', f'max-age={max_age}, private, stale-while-revalidate=86400')
        # self.send_header('Vary', 'User-Agent')
        if location:
            self.send_header('Content-Location', location)
        self.end_headers()
        return None

    def write_index(self):
        # session_user = self.session.get_logged_in("user")

        # Even set if user is not logged in
        # Used to prefill form input fields in template, etc
        user = self.session.get("user")

        location='/index.html'
        etag = self.get_etag(location)
        browser_etag = self.headers.get("If-None-Match", "")
        logger.debug("\n\nETag of index page: {}".format(etag))
        logger.debug("\nETag from client:   {}\n\n".format(browser_etag))

        if etag == browser_etag and not self.save_session:
            return self._write_304(etag, location=location)

        # Generate (new) page content
        self.context.update({
            "host": self.headers.get("HOST", ""),
            "protocol": "https://" if settings.SSL else "http://",
            "session_user": self.session_user,
            "user": user,
            "CONFIG_FILE": settings.get_settings_path(),
            "FAVORITES_FILE": settings.get_favorites_path(user),
            "favorites": self.get_favorites(),
            "history": self.get_history(),
            "HIST_GROUP_NAME": HIST_GROUP_NAME,
            "css_styles": CSS_STYLES,
        })

        html = self.server.html_renderer.run("index.html", self.context)

        self.send_response(200)
        #  DO NOT set max-age Cache-Control for index page
        #  This is BAD for redirects on '/' because the browser 
        #  will show the outdated version from it's cache.
        #  Example: Changing the css style will still showing the old one.
        # self.send_header('Cache-Control', 'max-age=60, private')

        # self.send_header('Vary', 'User-Agent')

        # Test of adding several other headers...
        #tmp_date = datetime.utcnow()
        # Das führt zu doppeltem Date-Header!
        # self.send_header('Date', tmp_date.strftime(DATE_HEADER_FORMAT))

        # tmp_date += timedelta(seconds=1000060)
        # self.send_header('Expires', tmp_date.strftime(DATE_HEADER_FORMAT))
        #... Expires ignored if max-age is given. Added to check effect on ETag feature

        # For Safari
        # tmp_date += timedelta(seconds=-120)
        # self.send_header('Last-Modified', tmp_date.strftime(DATE_HEADER_FORMAT))
        # self.send_header('Cache-Control', 'max-age=0, must-revalidate')
        # self.send_header('Expires', '-1')

        if self.save_session:
            self.session.save()

        # End headers and write page content
        if False:
            self.send_header('Content-type', 'text/html')
            self._write_1_1(html, etag=True, location=location)
        else:
            self._write_compressed(html, 'text/html'
                    , etag=True, location=location)

    def show_msg(self, msg, error=False, minimal=False):
        """ Sends msg/error as html page.

        - error: Inform template it's an error message
        - minimal: Just prints message without header/footer.
        """

        self.send_response(200)
        self.send_header('Content-type', 'text/html')

        self.context.update({
            "msg": msg,
        })

        self.context["session_user"] = self.session_user

        if error:
            self.context["msg_type"] = _("Error")
        else:
            self.context["msg_type"] = _("Debug Info")

        if minimal:
            html = self.server.html_renderer.run("message_minimal.html", self.context)
        else:
            html = self.server.html_renderer.run("message.html", self.context)

        self._write_1_1(html)

    def show_login(self, user=None, msg=None, error=False,
            display_settings=True, redirect_url=None):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')

        if user is None:
            user = self.session.get("user")

        self.context.update({"user": user,
               "msg": msg})

        self.context["session_user"] = self.session_user
        self.context["user"] = self.session.get("user")
        self.context["display_login_settings"] = display_settings
        self.context["redirect_url"] = redirect_url

        if error:
            self.context["msg_type"] = _("Error")
        else:
            self.context["msg_type"] = _("Info")

        html = self.server.html_renderer.run("login.html", self.context)
        self._write_1_1(html)

    def show_extras(self, msg=None, error=False):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')

        self.send_header('ETag', "extras_const_etag")
        self.send_header('Cache-Control', 'max-age=60, private')
        # self.send_header('Content-Location', '/extras')

        self.context["session_user"] = self.session.get_logged_in("user")
        self.context["msg"] = msg
        if error:
            self.context["msg_type"] = _("Error")
        else:
            self.context["msg_type"] = _("Info")

        html = self.server.html_renderer.run("extras/extras.html", self.context)
        self._write_1_1(html)

    def save_feed_change(self, feed):
        # Re-write file where this feed was read.
        # session_user = self.session.get_logged_in("user")
        hist = self.get_history()
        favs = self.get_favorites()
        if feed in hist:
            save_history(hist, settings.get_config_folder(),
                         settings.get_history_filename(self.session_user))
        else:
            update_favorites(favs,
                             settings.get_config_folder(),
                             settings.get_favorites_filename(self.session_user))

    def handle_change_css_style(self, query_components):
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
        # Note: This had no effect if redirect-response is invoked.
        #       Updating the session cookies is more important
        #       but the first rendering using still the old css style?!

        # Store value in Cookie for further requests
        self.session.c["css_style"] = css_style
        try:
            self.session.c["css_style"]["samesite"] = "Strict"
        except cookies.CookieError:
            pass  # Requires Python >= 3.8

        if not css_style:
            self.session.c["css_style"]["max-age"] = -1
        self.save_session = True

        # Reset eTags of user to avoid 304-replys with old style
        self.server.latest_etags[self.session_user] = {}

    def handle_show_feed(self, query_components):
        # session_user = self.session.get_logged_in("user", "")

        feed_key = qget(query_components, "feed")  # key, url or feed title
        bUseCache = (qget(query_components, "cache", "1") != "0")
        url_update = (qget(query_components, "url_update", "0") != "0")
        try:
            feed = get_feed(feed_key,
                            self.get_favorites(),
                            self.get_history())[0]

            # feed_url = feed.url if feed else feed_key
            if feed:
                feed_url = feed.url
            elif urlparse(feed_key).scheme:  # Distinct 'feed=Name' variant
                # Check if argument is url
                feed_url = feed_key
            else:
                error_msg = _('No feed found for this URI arguments.')
                if self.session.is_logged_in():
                    return self.show_msg(error_msg, True)
                else:
                    return self.show_login(self.session_user, error_msg,
                            error=True, display_settings=False,
                            redirect_url=self.path)

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

            if not feed:
                feed = Feed("", feed_url)
                bNew = True
            else:
                bNew = False

            etag_location = None
            browser_etag = self.headers.get("If-None-Match", "")
            location = f"/feed/{feed.get_uid()}"
            if code == 304:
                # Our data hasn't changed. Check if users etag is already
                # the current one.
                etag_location = self.get_etag(location)

            if not etag_location:
                # Generate etag
                etag_location = cEl.hash()  # Same for all pages of feed.

            etag = '"{}p{}"'.format(etag_location, page)

            if browser_etag == etag:
                # External feed source not changed and already send
                # current state to user. Just send 304.
                return self._write_304(etag, max_age=10)

            # Generate new output page
            if code == 304 and len(feed.context)>0:
                logger.debug("Skip parsing of feed and re-use previous")
            else:
                if not feed_parser.parse_feed(feed, cEl.data()):
                    error_msg = _('Parsing of Feed XML failed.')
                    return self.show_msg(error_msg, True)

            # Preparing feed.context on current side by updating
            # some of its values. This is to be done here because
            # processing all feed entries in feed_parser.parse_feed
            # would delay the output of first page and doing it as
            # template filter will process it at each call of the
            # page, but not once.
            feed_parser.prepare_page(feed, page)

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
            res["session_user"] = self.session_user

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
            # Set etag manually because it is the same for all feed pages
            # (_write_1_1(...) method can not set value because
            # etag != # etag_location.)
            self.set_etag(location, etag_location)
            return self.show_feed(html, etag=etag)


    def handle_show_feed_from_file(self, query_components):
        # session_user = self.session.get_logged_in("user", "")

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
            res["session_user"] = self.session_user

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
        # self.send_header('Content-type', 'text/html')

        if self.save_session:
            self.session.save()

        # self._write_1_1(html, etag=etag, max_age=10)
        self._write_compressed(html, 'text/html', etag=etag, max_age=10)

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

        #self.send_header('Cache-Control', "public, max-age=86000, stale-while-revalidate=86400 ")
        # self.send_header('Last-Modified', self.date_time_string())
        self.send_header('Last-Modified', "Wed, 21 Oct 2019 07:28:00 GMT")
        # TODO: Image not cached :-(

        self._write_1_1(image, max_age=860000)


    def login_required_for_page(self, view):
        if settings._LOGIN_TYPE is LoginType.NONE:
            return False  # No restrictions

        
        _no_login_required = [
            ViewType.INDEX_PAGE,
            ViewType.PROVIDE_FILE,
            ViewType.SHOW_FEED,
            ViewType.ADD_FAVS,
            # ViewType.REMOVE_FEED,
            ViewType.SHOW_LOGIN,
            ViewType.LOGIN,
            ViewType.LOGOUT,
            ViewType.CHANGE_STYLE,
            ViewType.ACTION_ICONS_CSS,
            ViewType.SYSTEM_ICON,
            ViewType.SHOW_EXTRAS,
            ViewType.YT_SCRIPT,
        ]
        if self.session_user == "" and view not in _no_login_required:
            return True

        return False


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
        minimal = (qget(query_components, "js", "0") != "0")
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
            # Begin action by handling non-serializable stuff.
            # This could prepare a (serializable) handler for the
            # worker.
            h = handler(feed, url, settings)
            if isinstance(h, PickableAction):
                # Finish action in worker process
                print(actions_pool.statistic())
                actions_pool.push_action(worker_handler, args=(h,))
            elif callable(h):
                h()  # Finish action in this process.
            else:
                logger.debug("Handler return unexpected type '{}'".\
                             format(h))
        except Exception as e:
            error_msg = _('Running of handler for "{action_name}" failed. ' \
                          'Exception was: "{e}".')\
                    .format(action_name=action, e=e)
            self.log_message("%s", error_msg)
            return self.show_msg(error_msg, True, minimal)


        # Handling sucessful
        sleep(2.0)  # TODO
        if not already_send:
            msg = _('Running of "{action_name}" for "{url}" started.') \
                    .format(action_name=action["title"], url=url)
            already_send = True
            return self.show_msg(msg, False, minimal)

    def handle_youtube(self, query_components):
        minimal = (qget(query_components, "js", "0") != "0")
        try:
            url = unquote(query_components["url"][-1])
        except (KeyError, IndexError):
            error_msg = _('URI arguments wrong.')
            return self.show_msg(error_msg, True, minimal)

        # Skip yt-dlp but use given url as final target
        explicit = (qget(query_components, "explicit", "0") != "0" \
                or qget(query_components, "e", "0") != "0")

        # Url to evaluate final target by yt-dlp
        yt_format = qget(query_components, "format") or qget(query_components, "f")
        target = qget(query_components, "target") or qget(query_components, "t")

        cmd = ["ytTV.sh", "{url}"]
        if target:
            cmd.insert(1, "{}".format(target))
            cmd.insert(1, "--target")
        if explicit:
            cmd.insert(1, "--explicit")
        if yt_format:
            cmd.insert(1, "{}".format(yt_format))
            cmd.insert(1, "--format")

        yt_action = factory__local_cmd(cmd, by_worker_pool=True)
        try:
            # Begin action by handling non-serializable stuff.
            # This could prepare a (serializable) handler for the
            # worker.
            h = yt_action(None, url, None)
            if isinstance(h, PickableAction):
                # Finish action in worker process
                actions_pool.push_action(worker_handler, args=(h,))
            elif callable(h):
                h()  # Finish action in this process.
            else:
                logger.debug("Handler return unexpected type '{}'".\
                             format(h))
        except Exception as e:
            error_msg = _('Running of handler for "{action_name}" failed. ' \
                          'Exception was: "{e}".')\
                    .format(action_name="yt", e=e)
            self.log_message("%s", error_msg)
            return self.show_msg(error_msg, True, minimal)

        msg = "Youtube command send."
        logger.info(msg)
        if minimal:
            return self.show_msg(msg, False, minimal)
        return self.show_extras(msg, False)

    def handle_login(self, query_components):
        user = qget(query_components, "user", "")
        password = qget(query_components, "password", "")
        redirect_url = qget(query_components, "redirect_url")
        logger.debug("User: '{}'".format(user))

        if self.session.init(user, password=password, settings=settings):
            # Omit display of double entries
            if self.get_history() != settings.HISTORY:
                clear_history(self.get_favorites(), self.get_history())

            return self.session_redirect(redirect_url or '/')
        else:
            error_msg = _('Login has failed.')
            return self.show_login(user, error_msg, True)

    def handle_logout(self, query_components):
        self.session.uninit()
        return self.session_redirect('/')

    def handle_change_feed_order(self, query_components):
        self.send_response(200)

        logger.info(query_components)
        group_names = query_components.get("groups", [])
        feed_ids = query_components.get("feed_ids", [])
        #save_on_disk = ("0" != qget(query_components, "save", "0"))
        save_on_disk = True

        # Convert ids from ','-separated string to list
        feed_ids = [ids.split(",") for ids in feed_ids]

        def feed_list_by_ids(ids, favs, hist):
            new_feeds = []
            for group in favs:
                if isinstance(group, Group):
                    new_feeds.extend(
                        [f for f in group.feeds if f.public_id() in ids])
                elif isinstance(group, Feed):
                    if group.public_id() in ids:
                        new_feeds.append(group)

            new_feeds.extend(
                [f for f in hist if f.public_id() in ids])

            # Sorting given by ids
            def sortkey_by_list_id(f):
                try:
                    return ids.index(f.public_id())
                except ValueError:
                    return -1

            new_feeds.sort(key=sortkey_by_list_id)

            return new_feeds

        def feed_in_group(feed, favs, hist):
            if feed in hist: 
                return True
            if feed in favs: 
                return True
            for group in favs:
                if isinstance(group, Group):
                    if feed in group.feeds:
                        return True

            return False

        settings_mutex.acquire()
        favs = self.get_favorites()
        hist = self.get_history()

        # Sanity check of group names
        #   (Just allow already existing names.)
        valid_group_names = []
        if HIST_GROUP_NAME in group_names:
            valid_group_names.append(HIST_GROUP_NAME)
        for group in favs:
            if isinstance(group, Group):
                if group.name in group_names:
                    valid_group_names.append(group.name)

        if len(valid_group_names) != len(group_names):
            msg = "Invalid group name."
            logger.error(msg)
            return self.show_msg(msg, error=True, minimal=True)

        # Create new groups (may be subset of all groups+hist)
        hist_new = []
        favs_new = []
        for i in range(len(group_names)):
            if group_names[i] == HIST_GROUP_NAME:
                hist_new.extend(feed_list_by_ids(feed_ids[i], favs, hist))
            else:
                g = Group(group_names[i],
                          feed_list_by_ids(feed_ids[i], favs, hist))
                favs_new.append(g)

        # Check if new groups containing all feeds of old groups
        ok = True
        for group_name in group_names:
            if group_name != HIST_GROUP_NAME:
                _l = self.get_group(group_name).feeds
            else:
                _l = hist

            for feed in _l:
                ok = ok and feed_in_group(feed, favs_new, hist_new)

        if not ok:
            msg = "Missing feed in new order."
            logger.error(msg)
            return self.show_msg(msg, error=True, minimal=True)

        # Check for duplicate ids in new given groups
        N_new, N_old = 0,0
        i = 0
        for group_name in group_names:
            if group_name == HIST_GROUP_NAME:
                N_old += len(hist)
                N_new += len(hist_new)
            else:
                N_new += len(favs_new[i].feeds)
                N_old += len(self.get_group(group_name).feeds)

            i += 0

        if N_new != N_old:
            msg = "Length of new ordered feeds doesn't match."
            logger.error(msg)
            return self.show_msg(msg, error=True, minimal=True)


        # Update favs and hist
        # self.set_favorites(favs_new)  # wrong. favs_new could be subset
        favs_changed = False
        for g in favs_new:
            for g2 in favs:
                if g.name == g2.name:
                    if g2.feeds != g.feeds:
                        favs_changed = True
                    g2.feeds = g.feeds
        self.set_history(hist_new)

        if save_on_disk:
            if favs_changed:
                self.save_favorites()
            if hist_new != hist:
                self.save_history()
        settings_mutex.release()

        # Reset 304/etag evaluation on start page
        self.set_etag('/index.html', None)
        self._write_1_1("Sorted")

    def session_redirect(self, location):
        # Saves login session cookies

        self.send_response(303)
        # self.send_header('Content-type', 'text/html')
        self.session.save()

        self.send_header('Content-Length', 0)
        self.send_header('Location', location)  # Last header!
        self.end_headers()

    def update_cache_feed(self, feed_new, bNew):
        """ Update cache and history """

        res = feed_new.context
        if bNew:
            # session_user = self.session.get_logged_in("user")
            # Add this (new) url to feed history.
            hist = self.get_history()
            # feed_title = res["title"]
            # hist.append(Feed(feed_title, feed.url, feed_title))
            hist.append(feed_new)
            save_history(hist, settings.get_config_folder(),
                         settings.get_history_filename(self.session_user))


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
            # session_user = self.session.get_logged_in("user")
            hist = self.get_history()
            hist.append(feed)
            save_history(hist, settings.get_config_folder(),
                         settings.get_history_filename(self.session_user))

        # 3. Write changes in cache.
        # Note that this clears saved headers for this feed.
        cEl =  cached_requests.CacheElement.from_bytes(byte_str)
        cached_requests.update_cache(feed.cache_name(), cEl)


# Call 'make ssl' to generate local test certificates.
def wrap_SSL(httpd, key_file, crt_file):
    if not os.path.isfile(key_file) and not os.path.isfile(crt_file):
        # Try relative path for both files
        cf = settings.get_config_folder()
        key_file = os.path.join(cf, key_file)
        crt_file = os.path.join(cf, crt_file)
    if not os.path.isfile(key_file):
        logger.error("Key file not found check settings.SSL_KEY_PATH")
    if not os.path.isfile(crt_file):
        logger.error("Certificate file not found check settings.SSL_CRT_PATH")

    httpd.socket = ssl.wrap_socket (
        httpd.socket, server_side=True,
        keyfile=key_file,
        certfile=crt_file,
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

    # print("Set logging level on {}".format(numeric_level))
    logging.basicConfig(level=numeric_level)
    for key in keys:
        logging.getLogger(key).setLevel(numeric_level)


def main():
    # Workaround...
    set_start_method("spawn")

    settings.load_config(globals())
    settings.load_users(globals())

    # Overwrite 'settings' in other modules, too.
    settings.update_submodules(globals())

    # logging.conf already contain levels for each component, but
    # settings could override this by a global value
    set_logger_levels()

    feed_parser.find_installed_en_locale()

    parser = create_argument_parser()
    args = parser.parse_args()

    if not args.multiple and check_process_already_running():
        logger.info("Server process is already running.")
        return 0

    if args.daemon and os.name in ["posix"]:
        if not daemon_double_fork():
            # Only continue in forked process..
            return 0

    if args.port:
        settings.PORT = args.port

    if args.host:
        settings.HOST = args.host

    if not args.ssl is None:
        settings.SSL = args.ssl

    # Create empty favorites files if none exists
    if not os.path.lexists(settings.get_favorites_path()):
        update_favorites(settings.FAVORITES,
                         settings.get_config_folder())

    # Omit display of double entries
    clear_history(settings.FAVORITES, settings.HISTORY)

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


    global actions_pool
    actions_pool = ActionPool(settings,
                             processes=2,
                             max_active_or_pending=6,
                             allow_abort_after=3600.0)
    logger.info("Start action pool")
    actions_pool.start()

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

    global __restart_service
    __restart_service = True

    # Sometimes, external request spamming leads to a failure
    # of the http service after a few days.
    # The service will be blocked by the OS until we restart it.
    # As workaround, I added a loop to periodical restart the service..
    def __shutdown_and_serve_again():
        while True:
            sleep(3600.0)
            logger.info("Periodical restart of http service at port {}"
                    .format(settings.PORT))
            global __restart_service
            __restart_service = True
            httpd.shutdown()

            # Cache cleanup
            cached_requests.trim_cache()  # Currently redundant

    t = Thread(target=__shutdown_and_serve_again)
    t.daemon = True
    t.start()

    while __restart_service:
        __restart_service = False
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

    logger.info("Stop action pool")
    actions_pool.stop()
    logger.info("END program")

    return 0


def create_argument_parser():
    parser = argparse.ArgumentParser(
        description='RSS Viewer', usage="python3 -m rss2html [options]")
    parser.add_argument('-m', '--multiple', action='store_true',
                        help="")
    parser.add_argument('-d', '--daemon', action='store_true',
                        help="Run as daemon process.")
    parser.add_argument('-p', '--port', type=int,
                        help="Override default port.")
    parser.add_argument('--host', type=str,
                        help="Override default hostname.")
    parser.add_argument('-s', '--ssl', type=bool, # Default is None
                        help="Override SSL option.")
    return parser

if __name__ == "__main__":
    sys.exit(main())
