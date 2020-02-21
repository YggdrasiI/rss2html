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
from time import sleep
# from importlib import reload

from gettext import gettext as _
# from jina2.utils import unicode_urlencode as urlencode

from feed import Feed, get_feed, save_history, clear_history, update_favorites

import templates
import default_settings as settings  # Overriden in load_config()
import icon_searcher
import cached_requests
import actions


XML_NAMESPACES = {'content': 'http://purl.org/rss/1.0/modules/content/',
                  'atom': 'http://www.w3.org/2005/AtomX',
                  'atom10': 'http://www.w3.org/2005/Atom',
                 }
ORIG_LOCALE = locale.getlocale()
EN_LOCALE = ("en_US", ORIG_LOCALE[1])  # second index probably UTF-8
HISTORY = []

CSS_STYLES = {
    None: _("Default theme"),
    "dark.css": _("Dark theme"),
}

# ==========================================================


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
            print("Can not set locale: %s" % str(e))
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

        enclosures.append(e)

    return enclosures


def genMyHTTPServer():
    # The definition of the MyTCPServer class is wrapped
    # because settings module only maps to the right module
    # at runtime (after load_config() call).
    # Before it maps on default_settings.

    # class _MyHTTPServer(socketserver.TCPServer):
    class _MyHTTPServer(http.server.ThreadingHTTPServer):
        print("Use language {}".format(settings.GUI_LANG))
        html_renderer = templates.HtmlRenderer(settings.GUI_LANG,
                                               settings.CSS_STYLE)

        def server_bind(self):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket.bind(self.server_address)

    return _MyHTTPServer


class MyHandler(http.server.SimpleHTTPRequestHandler):
    server_version = "RSS_Server/0.1"

    # Note: ETag ignored for 1.0, but protcol version 1.1
    # requires header 'Content-Lenght' for all requests. Otherwise,
    # the browsers will wait forever for more data...
    protocol_version = "HTTP/1.1"

    def do_add_favs(self, add_favs):
        for feed_key in add_favs:
            (feed, idx) = get_feed(feed_key,
                                   settings.FAVORITES,
                                   HISTORY)
            if feed and idx > 0:  # Index indicates that feed not in FAVORITES
                settings.FAVORITES.append(feed)
                try:
                    HISTORY.remove(feed)
                except ValueError:
                    pass

        save_history(HISTORY, settings.get_config_folder())
        update_favorites(settings.FAVORITES, settings.get_config_folder())


    def do_rm_feed(self, to_rm):
        for feed_key in to_rm:
            (feed, idx) = get_feed(feed_key,
                                   settings.FAVORITES,
                                   HISTORY)
            if idx == 0:
                try:
                    settings.FAVORITES.remove(feed)
                    update_favorites(settings.FAVORITES,
                                     settings.get_config_folder())
                except ValueError:
                    pass

            if idx == 1:
                try:
                    HISTORY.remove(feed)
                    save_history(HISTORY, settings.get_config_folder())
                except ValueError:
                    pass

    def do_GET(self):
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

        elif self.path.startswith("/change_style"):
            self.handle_change_css_style(query_components)
            return self.write_index()
        elif self.path == "/action":
            try:
                self.handle_action(query_components)
            except Exception as e:
                error_msg = str(e)

        elif feed_key:
            try:
                feed = get_feed(feed_key,
                                settings.FAVORITES,
                                HISTORY)[0]
                feed_url = feed.url if feed else feed_key

                res = None
                (text, code) = cached_requests.fetch_file(settings, feed_url, bUseCache)
                etag = '"{}"'.format(
                    hashlib.sha1(text.encode('utf-8') if text is not None \
                                 else "").hexdigest())
                print("Eval ETag '{}'".format(etag))
                print("Browser ETag '{}'".format(self.headers.get("If-None-Match", "")))
                print("All headers:")
                print(self.headers)

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
                    HISTORY.append(
                        Feed(feed_title, feed_url, feed_title))
                    save_history(HISTORY, settings.get_config_folder())

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

                # Replace stored url, if newer value is given.
                if feed and url_update and res["href"]:
                    feed_url = feed.url
                    feed.url = res["href"]
                    feed.title = res.get("title", feed.title)
                    self.save_feed_change(feed)

                if entryid:
                    html = "TODO"
                else:
                    html = self.server.html_renderer.run("feed.html", res)

            except ValueError as e:
                error_msg = str(e)
            except:
                raise
            finally:
                feed_feched = True

        elif filepath:
            # No cache read in this variant
            try:
                feed_filepath = filepath[-1]
                print("Read " + feed_filepath)
                text = load_xml(feed_filepath)
                tree = ElementTree.XML(text)

                res = find_feed_keyword_values(tree)
                res["nocache_link"] = res["title"]

                # Update cache and history
                feed = get_feed(res["title"],
                                settings.FAVORITES,
                                HISTORY)[0]
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
                    HISTORY.append(feed)
                    save_history(HISTORY, settings.get_config_folder())

                cached_requests.update_cache(feed.title, res, {})
                html = self.server.html_renderer.run("feed.html", res)

            except ValueError as e:
                error_msg = str(e)
            except:
                raise
            finally:
                feed_feched = True

        if error_msg:
            return self.show_msg(error_msg, True)
        elif feed_feched:
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.send_header('Cache-Control', "public, max-age=10, ")
            if etag:
                print("Add ETag '{}'".format(etag))
                self.send_header('ETag', etag)
                self.send_header('Vary', "ETag, User-Agent")

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
                self.send_header('Content-type', 'text/xml')
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
            return self.write_index()
        elif self.path[-4:] in settings.ALLOWED_FILE_EXTENSIONS:
            return super().do_GET()
        else:
            # return super().do_GET()
            return self.send_error(404)

    def write_index(self):

        context = {
            "host": self.headers.get("HOST", ""),
            "CONFIG_FILE": settings.get_settings_path(),
            "favorites": settings.FAVORITES,
            "history": HISTORY,
            "css_styles": CSS_STYLES
        }

        html = self.server.html_renderer.run("index.html", context)

        output = BytesIO()
        output.write(html.encode('utf-8'))
        output.seek(0, os.SEEK_END)  # As reminder…

        # Etag
        etag = '"{}"'.format( hashlib.sha1(output.getvalue()).hexdigest())

        browser_etag = self.headers.get("If-None-Match", "")
        if etag == browser_etag:
            self.send_response(304)
            self.send_header('ETag', etag)
            self.send_header('Cache-Control', "public, max-age=10, ")
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

        # Other headers
        self.send_header('Content-Length', output.tell())
        self.send_header('Content-type', 'text/html')
        self.end_headers()

        self.wfile.write(output.getvalue())

    def show_msg(self, msg, error=False):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')

        output = BytesIO()
        if error:
            res = {"msg_type": _("Error"),
                   "msg": msg}
            html = self.server.html_renderer.run("message.html", res)
        else:
            res = {"msg_type": _("Debug Info"),
                   "msg": msg}
            html = self.server.html_renderer.run("message.html", res)

        output.write(html.encode('utf-8'))
        output.seek(0, os.SEEK_END)
        self.send_header('Content-Length', output.tell())
        self.end_headers()

        self.wfile.write(output.getvalue())

    def save_feed_change(self, feed):
        # Re-write file where this feed was read.
        if feed in HISTORY:
            save_history(HISTORY, settings.get_config_folder())
        elif feed in settings.FAVORITES:
            update_favorites(settings.FAVORITES,
                             settings.get_config_folder())

    def handle_change_css_style(self, query_components):
        try:
            css_style = query_components.get("css_style", [None])[-1]
            if not css_style in CSS_STYLES: # for "None" and wrong values
                css_style = None

            # Note: This saves not the values permanently, but for this
            # instance.
            self.server.html_renderer.extra_context["user_css_style"] = \
                    css_style

        except KeyError:
                raise Exception("CSS style with this name not defined")

    def handle_action(self, query_components):
        try:
            action = actions.ACTIONS(query_components["title"])
            action["handler"]
        except KeyError:
                raise Exception("Action not defined")

if __name__ == "__main__":
    settings.load_config(globals())

    if check_process_already_running():
        print("Server process is already running.")
        os._exit(0)

    if "-d" in sys.argv:
        if not daemon_double_fork():
            # Only continue in forked process..
            os._exit(0)

    # Omit display of double entries
    clear_history(settings.FAVORITES, HISTORY)

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

    print("Serving at port", settings.PORT)
    print("Use localhost:{0}/?feed=[url] to read feed".format(settings.PORT))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()
    except:
        httpd.shutdown()
        raise

    print("END")
