#!/usr/bin/python3
# -*- coding: utf-8 -*-

import sys
import os.path
from datetime import datetime
from xml.etree import ElementTree

from urllib.parse import urlparse, parse_qs
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from threading import Thread
import http.server
import socket
import socketserver
from io import BytesIO
import time
import locale
from time import sleep
from importlib import reload

from feed import Feed, get_feed, save_history, clear_history, update_favorites

import templates
import default_settings as settings  # Overriden in load_config()
import icon_searcher


XML_NAMESPACES = {'content': 'http://purl.org/rss/1.0/modules/content/',
                  'atom': 'http://www.w3.org/2005/AtomX',
                  'atom10': 'http://www.w3.org/2005/Atom',
                 }
ORIG_LOCALE = locale.getlocale()
EN_LOCALE = ("en_US", ORIG_LOCALE[1])
HISTORY = []
_CACHE = {}


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
    """
    formats = [
        ("%a, %d %b %Y %H:%M:%S %z", s),
        ("%a, %d %b %Y %H:%M:%S %Z", s),
        ("%a, %d %b %Y %H:%M:%S", s[:len(s)+1-s.rfind(" ")]),
    ]

    ret = None
    for (f, s2) in formats:
        try:
            locale.setlocale(locale.LC_ALL, EN_LOCALE)
            dt = datetime.strptime(s2, "%a, %d %b %Y %H:%M:%S %z")

            # Without this line the locale is ignored...
            locale.setlocale(locale.LC_ALL, '')
            ret = dt.strftime("%d. %B %Y, %H:%M%p")

            locale.resetlocale(locale.LC_ALL)
            break
        except locale.Error as e:
            print("Can not set locale: %s" % str(e))
            dt = datetime.strptime(s2, "%a, %d %b %Y %H:%M:%S %z")
            ret = dt.strftime("%d. %B %Y, %H:%M%p")
            break
        except ValueError:
            pass

    if ret:
        return ret

    raise Exception("Can not parse {}".format(s2))


def load_xml(filename):

    with open(filename, 'rt') as f:
        tree = ElementTree.parse(f)

    return tree


def fetch_xml(url):
    tree = None
    print("Url: " + url)
    req = Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        response = urlopen(req, timeout=5)
        '''
        content_type = response.getheader('Content-Type','')
        """ Content type variates. Some possible values are…
            text/html, application/rss+xml, application/xml
        """
        if not(content_type.startswith("text/") or
               "xml" in content_type):
            raise Exception("Wrong Content-Type: '{}'?!".format(
                content_type))
        '''

        try:
            # Content-Length header optional/not set in all cases…
            content_len = int(response.getheader("Content-Length", 0))
            if content_len > settings.MAX_FEED_BYTE_SIZE:
                raise Exception("Feed file exceedes maximal size. {0} > {1}"
                                "".format(content_len,
                                          settings.MAX_FEED_BYTE_SIZE))
        except ValueError:
            pass

    except HTTPError as e:
        print('The server couldn\'t fulfill the request.')
        print('Error code: ', e.code)
    except URLError as e:
        print('We failed to reach a server.')
        print('Reason: ', e.reason)
    else:
        # everything is fine
        # data = response.read()
        # text = data.decode('utf-8')
        tree = ElementTree.parse(response)

    return tree


def find_feed_keywords_values(tree, kwdict=None):

    kwdict = kwdict if kwdict else {}

    kwdict.setdefault("FEED_TITLE", "Undefined")
    kwdict.setdefault("FEED_HREF", "")

    def search_href():
        if (atom_node.attrib.get("rel") == "self" and
            atom_node.attrib.get("type") in ["application/rss+xml",
                                                 "application/xml"]
           ):
            kwdict["FEED_HREF"] = atom_node.attrib.get("href", "")
            kwdict["FEED_TITLE"] = atom_node.attrib.get(
                "title", kwdict["FEED_TITLE"])
            return True

    for atom_node in tree.findall('./channel/atom10:link', XML_NAMESPACES):
        if search_href(): break

    for atom_node in tree.findall('./channel/atom:link', XML_NAMESPACES):
        if search_href(): break

    # ATTENTION: 'if node:' evaluates to False even if node is a 'node instance'!
    node = tree.find('./channel/title')
    if node is not None:
        kwdict["FEED_TITLE"] = node.text

    node = tree.find('./channel/description')
    kwdict["FEED_SUBTITLE"] = "Undefined" if node is None else node.text

    node = tree.find('./channel/image/url')
    image_url = "" if node is None else node.text

    node = tree.find('./channel/image/title')
    image_title = "" if node is None else node.text

    kwdict["FEED_TITLE_IMAGE"] = ("" if not image_url else
                                  templates.TEMPLATE_TITLE_IMG.format(
                                      IMAGE_URL=image_url,
                                      IMAGE_TITLE=image_title))

    entries = []
    entries_len = 0  # To remove ENTRY_CONTENT_FULL for long feeds.
    for item_node in tree.findall('./channel/item'):
        entry = {}
        node = item_node.find('./link')
        entry["ENTRY_URL"] = "Undefined" if node is None else node.text

        node = item_node.find('./title')
        entry["ENTRY_TITLE"] = "Undefined" if node is None else node.text

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

        entry["ENTRY_CONTENT"] = templates.TEMPLATE_ENTRY_CONTENT.format(
            ENTRY_CONTENT_SHORT=content_short,
            ENTRY_CONTENT_FULL=content_full,
            ENTRY_CLICKABLE="click_out" if content_full else "",
        )

        node = item_node.find('./pubDate')
        if node is not None:
            entry["ENTRY_LAST_UPDATE"] = parse_pubDate(node.text)
        else:
            entry["ENTRY_LAST_UPDATE"] = "Undefined date"

        entry["enclosures"] = find_enclosures(item_node)

        entries.append(entry)
        entries_len += len(content_full)

    kwdict["entries"] = entries
    return kwdict


def find_enclosures(item_node):
    enclosures = []
    for e_node in item_node.findall('./enclosure'):
        e = {}
        try:
            e["ENCLOSURE_URL"] = e_node.attrib["url"]
        except (AttributeError, KeyError):
            e["ENCLOSURE_URL"] = "Undefined"

        e["ENCLOSURE_FILENAME"] = os.path.basename(e["ENCLOSURE_URL"])

        try:
            e["ENCLOSURE_TYPE"] = e_node.attrib["type"]
        except (AttributeError, KeyError):
            e["ENCLOSURE_TYPE"] = "Undefined"

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

            e["ENCLOSURE_LENGTH"] = l
        except (AttributeError, KeyError, ValueError):
            e["ENCLOSURE_LENGTH"] = "0"

        enclosures.append(e)

    return enclosures


def update_cache(key, res):
    if key == "":
        return
    _CACHE[key] = (int(time.time()), res)


def check_cache(key):
    if key in _CACHE:
        now = int(time.time())
        (t, res) = _CACHE.get(key)
        if (now - t) < settings.CACHE_EXPIRE_TIME_S:
            print("Use cache")
            return res

    return None


class MyTCPServer(socketserver.TCPServer):
    def server_bind(self):
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind(self.server_address)


class MyHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        query_components = parse_qs(urlparse(self.path).query)
        feed_feched = False
        error_msg = None
        show_index = False
        feed_arg = query_components.get("feed")  # key, url or feed title
        filepath = query_components.get("file")  # From 'open with' dialog
        nocache = query_components.get("cache", ["1"])[-1] == "0"
        url_update = query_components.get("url_update", ["0"])[-1] != "0"
        add_favs = query_components.get("add_fav", [])
        to_rm = query_components.get("rm", [])


        if add_favs:
            show_index = True
            for feed_key in add_favs:
                (feed, idx) = get_feed(feed_key,
                                       settings.FAVORITES,
                                       HISTORY)
                if feed and idx > 0:  # Index indicates that feed is in HISTORY
                    settings.FAVORITES.append(feed)
                    try:
                        HISTORY.remove(feed)
                    except ValueError:
                        pass

            save_history(HISTORY, settings.get_config_folder())
            update_favorites(settings.FAVORITES, settings.get_config_folder())

        if to_rm:
            show_index = True
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


        if self.path == "/quit":
            ret = self.show_msg("Quit")

            def __delayed_shutdown():
                sleep(1.0)
                self.server.shutdown()

            t = Thread(target=__delayed_shutdown)
            t.daemon = True
            t.start()
            return ret

        elif self.path == "/refresh_templates":
            reload(sys.modules['templates'])
            return self.show_msg("Templates reloaded")

        elif feed_arg:
            try:
                feed = get_feed(feed_arg[-1],
                                settings.FAVORITES,
                                HISTORY)[0]
                feed_url = feed.url if feed else feed_arg[-1]

                res = None
                if feed and not nocache:
                    res = check_cache(feed.title)
                if not res and not nocache:
                    res = check_cache(feed_url)

                if not res:
                    tree = fetch_xml(feed_url)
                    res = find_feed_keywords_values(tree)
                    res["NOCACHE_LINK"] = ""  # Omit link

                    # Update cache and history
                    if not feed:
                        feed_title = res["FEED_TITLE"]
                        # Add this (new) url to feed history.
                        HISTORY.append(
                            Feed(feed_title, feed_url, feed_title))
                        save_history(HISTORY, settings.get_config_folder())

                    # Warn if feed url might changes
                    parsed_feed_url = res["FEED_HREF"]
                    if not url_update and  parsed_feed_url and parsed_feed_url != feed_url:
                        res.setdefault("WARNINGS", []).append({
                            "TITLE": "Warning",
                            "MSG": """Feed url difference detected. It might
                            be useful to <a href="/?{ARGS}&url_update=1">update</a> \
                            the stored url.<br /> \
                            Url in config/history file: {OLD_URL}<br /> \
                            Url in feed xml file: {NEW_URL}
                            """.format(OLD_URL=feed_url,
                                       NEW_URL=parsed_feed_url,
                                       ARGS="feed=" + feed_arg[-1],
                                      )
                        })

                    update_cache(feed_url, res)
                else:
                    uncached_url = templates.TEMPLATE_NOCACHE_LINK.format(
                        ARGS="feed=" + feed_arg[-1])
                    res["NOCACHE_LINK"] = uncached_url


                # Replace stored url, if newer value is given.
                if feed and url_update and res["FEED_HREF"]:
                    feed_url = feed.url
                    feed.url = res["FEED_HREF"]
                    feed.title = res.get("FEED_TITLE", feed.title)
                    # Re-Write this file where the feed was found.
                    if feed in HISTORY:
                        save_history(HISTORY, settings.get_config_folder())
                    elif feed in settings.FAVORITES:
                        update_favorites(settings.FAVORITES,
                                         settings.get_config_folder())

                #res["CONFIG_FILE"] = get_config_folder()
                html = templates.gen_html(res)

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
                tree = load_xml(feed_filepath)
                res = find_feed_keywords_values(tree)
                res["FEED_UNCACHED_URL"] = "/?feed={}&cache=0".format(
                    res["FEED_TITLE"])  # Hm, this requires a proper .url value

                # Update cache and history
                feed = get_feed(res["FEED_TITLE"],
                                settings.FAVORITES,
                                HISTORY)[0]
                if feed:
                    feed_title = feed.title
                else:
                    feed_title = res["FEED_TITLE"]
                    # Add this (new) feed to history.
                    # Try to extract feed url from xml data because it is not
                    # given directly!
                    HISTORY.append(Feed(feed_title,
                                        res.get("FEED_HREF", ""),
                                        feed_title))
                    save_history(HISTORY, settings.get_config_folder())

                update_cache(feed_title, res)
                res["NOCACHE_LINK"] = ""
                #res["CONFIG_FILE"] = get_config_folder()
                html = templates.gen_html(res)

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
            self.end_headers()

            output = BytesIO()
            output.write(html.encode('utf-8'))
            self.wfile.write(output.getvalue())
        elif self.path.startswith("/icons/system/"):
            image = icon_searcher.get_cached_file(self.path)
            if not image:
                return self.send_error(404)

            self.send_response(200)
            self.send_header('Content-type', 'image')
            self.end_headers()
            output = BytesIO()
            output.write(image)
            self.wfile.write(output.getvalue())
        elif self.path == "/" or show_index:
            return self.write_index()
        elif self.path[-4:] in settings.ALLOWED_FILE_EXTENSIONS:
            return super().do_GET()
        else:
            # return super().do_GET()
            return self.send_error(404)

    def write_index(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()

        host = self.headers.get("HOST", "")
        # Gen list of favs.
        favs = [templates.TEMPLATE_FAVORITE.format(
            TITLE=feed.title if feed.title else feed.url,
            NAME=feed.name, HOST=host)
            for feed in settings.FAVORITES]
        favorites = ("<ul><li>{}</li></ul>".format("</li>\n<li>".join(favs))
                     if len(favs) else "—")
        # Gen list of history entries. Here, we assume that name isn't defined.
        # Use title value as replacement.
        other_feeds = [templates.TEMPLATE_HISTORY.format(
            NAME=feed.title, TITLE=feed.title, HOST=host)
                       for feed in HISTORY]
        history = ("<ul><li>{}</li></ul>".format("</li>\n<li>".join(other_feeds))
                   if other_feeds else "—")

        output = BytesIO()
        output.write(templates.TEMPLATE_HELP.format(
            HOST=host,
            FAVORITES=favorites,
            HISTORY=history,
            CONFIG_FILE=os.path.join(settings.get_config_folder(), "settings.py")
        ).encode('utf-8'))
        self.wfile.write(output.getvalue())

    def show_msg(self, msg, error=False):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()

        output = BytesIO()
        if error:
            output.write(templates.TEMPLATE_MSG.format(
                MSG_TYPE="Error",
                MSG=msg).encode('utf-8'))
        else:
            output.write(templates.TEMPLATE_MSG.format(
                MSG_TYPE="Debug Info",
                MSG=msg).encode('utf-8'))

        self.wfile.write(output.getvalue())


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
        httpd = MyTCPServer((settings.HOST, settings.PORT), MyHandler)
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
