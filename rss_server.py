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
import socketserver
from io import BytesIO
import time
import locale
from time import sleep
from importlib import reload 

from feed import Feed, get_feed, save_history, clear_history

# Default settings
# Put changes of these variables into settings.py!
HOST = "localhost"  # "" allows access from everywhere....
PORT = 8888
CACHE_EXPIRE_TIME_S = 600
MAX_FEED_BYTE_SIZE = 10E6
FEED_FAVORITES = [
    Feed("example", "http://www.deutschlandfunk.de/podcast-das-war-der-tag.803.de.podcast",
         "Example Feed (&lt;channel&gt;&lt;title&gt;-value, optional)"),
]

try:
    from feed_history import FEED_HISTORY
except:
    FEED_HISTORY = []

def load_templates():
    """ Nested to allow reload of templates. """
    from templates import gen_html, \
            TEMPLATE_TITLE_IMG, TEMPLATE_ENTRY_CONTENT, \
            TEMPLATE_HELP, TEMPLATE_FAVORITE, TEMPLATE_HISTORY, \
            TEMPLATE_MSG, TEMPLATE_NOCACHE_LINK

    globals().update(locals())

load_templates()



XML_NAMESPACES = {'content': 'http://purl.org/rss/1.0/modules/content/'}
_CACHE = {}

ORIG_LOCALE = locale.getlocale()
EN_LOCALE = ("en_US", ORIG_LOCALE[1])

# Read overrides/settings
SETTINGS = "settings.py"
if os.path.exists(SETTINGS):
    if "." not in sys.path:
        sys.path.append(".")

    exec(open(os.path.join(SETTINGS)).read())

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
            os._exit(0) # Quit first child process
    else:
        # Wait on first child process
        os.waitpid(pid, 0)

    return False

def parse_pubDate(s):
    """
    Example input:
        <pubDate>Tue, 04 Dec 2018 06:48:30 +0000</pubDate>
    """
    try:
        locale.setlocale(locale.LC_ALL, EN_LOCALE)
        dt = datetime.strptime(s, "%a, %d %b %Y %H:%M:%S %z")

        # Without this line the locale is ignored...
        locale.setlocale(locale.LC_ALL, '')
        ret = dt.strftime("%d. %B %Y, %H:%M%p")

        locale.resetlocale(locale.LC_ALL)
    except locale.Error as e:
        print("Can not set locale: %s" % str(e))

    return ret


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
            if content_len > MAX_FEED_BYTE_SIZE:
                raise Exception("Feed file exceedes maximal size. {0} > {1}" \
                                "".format(content_len, MAX_FEED_BYTE_SIZE))
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

    # NOTE: 'if node' is False even if it is a node instance.
    node = tree.find('./channel/title')
    kwdict["FEED_TITLE"] = "Undefined" if node is None else node.text

    node = tree.find('./channel/description')
    kwdict["FEED_SUBTITLE"] = "Undefined" if node is None else node.text

    node = tree.find('./channel/image/url')
    image_url = "" if node is None else node.text

    node = tree.find('./channel/image/title')
    image_title = "" if node is None else node.text

    kwdict["FEED_TITLE_IMAGE"] = ("" if not image_url else
                                  TEMPLATE_TITLE_IMG.format(
                                      IMAGE_URL=image_url,
                                      IMAGE_TITLE=image_title))

    entries = []
    for item_node in tree.findall('./channel/item'):
        entry = {}
        node = item_node.find('./link')
        entry["ENTRY_URL"] = "Undefined" if node is None else node.text

        node = item_node.find('./title')
        entry["ENTRY_TITLE"] = "Undefined" if node is None else node.text

        node = item_node.find('./description')
        content = "" if node is None else node.text
        entry["ENTRY_CONTENT"] = TEMPLATE_ENTRY_CONTENT.format(
            ENTRY_CONTENT=content)

        node = item_node.find('./content:encoded', XML_NAMESPACES)
        entry["ENTRY_CONTENT_FULL"] = "Undefined" if node is None else node.text

        node = item_node.find('./pubDate')
        if node is not None:
            entry["ENTRY_LAST_UPDATE"] = parse_pubDate(node.text)
        else:
            entry["ENTRY_LAST_UPDATE"] = "Undefined date"

        entry["enclosures"] = find_enclosures(item_node)

        entries.append(entry)

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
        if (now - t) < CACHE_EXPIRE_TIME_S:
            print("Use cache")
            return res

    return None


class MyHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        #reload(sys.modules['templates'])
        #load_templates()

        query_components = parse_qs(urlparse(self.path).query)
        feed_feched = False
        error_msg = None
        feed_arg = query_components.get("feed")  # key, url or feed title
        filepath = query_components.get("file")  # From 'open with' dialog
        nocache = query_components.get("cache", ["1"])[-1] == "0"

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
            load_templates()
            return self.show_msg("Templates reloaded")

        elif feed_arg:
            try:
                feed = get_feed(feed_arg[-1], FEED_FAVORITES, FEED_HISTORY)
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
                        FEED_HISTORY.append(Feed(feed_title, feed_url, feed_title))
                        save_history(FEED_HISTORY)

                    update_cache(feed_url, res)
                else:
                    uncached_url = TEMPLATE_NOCACHE_LINK.format(
                        ARGS="feed=" + feed_arg[-1])
                    res["NOCACHE_LINK"] = uncached_url

                html = gen_html(res)

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
                feed = get_feed(res["FEED_TITLE"], FEED_FAVORITES, FEED_HISTORY)
                if feed:
                    feed_title = feed.title
                else:
                    feed_title = res["FEED_TITLE"]
                    # Add this (new) feed to history. Here, we had no clue
                    # about the feed url!
                    FEED_HISTORY.append(Feed(feed_title, "", feed_title))
                    save_history(FEED_HISTORY)

                update_cache(feed_title, res)
                html = gen_html(res)

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
        elif self.path == "/":
            return self.show_index()
        elif self.path[-4:] in [".css", ".png", ".jpg"]:
            return super().do_GET()
        else:
            # return super().do_GET()
            return self.send_error(404)

    def show_index(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()

        host = self.headers.get("HOST", "")
        # Gen list of favs.
        favs = [TEMPLATE_FAVORITE.format(
            TITLE=feed.title if feed.title else feed.url,
            NAME=feed.name, HOST=host)
                for feed in FEED_FAVORITES]
        favorites = ("<ul><li>{}</li></ul>".format("</li>\n<li>".join(favs))
                     if len(favs) else "—")
        # Gen list of history entries.
        other_feeds = [TEMPLATE_HISTORY.format(TITLE=feed.title, HOST=host)
                       for feed in FEED_HISTORY]
        history = ("<ul><li>{}</li></ul>".format("</li>\n<li>".join(other_feeds))
                     if other_feeds else "—")

        output = BytesIO()
        output.write(TEMPLATE_HELP.format(
            HOST=host,
            FAVORITES=favorites,
            HISTORY=history,
        ).encode('utf-8'))
        self.wfile.write(output.getvalue())

    def show_msg(self, msg, error=False):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()

        output = BytesIO()
        if error:
            output.write(TEMPLATE_MSG.format(
                MSG_TYPE="Error",
                MSG=msg).encode('utf-8'))
        else:
            output.write(TEMPLATE_MSG.format(
                MSG_TYPE="Debug Info",
                MSG=msg).encode('utf-8'))

        self.wfile.write(output.getvalue())


if __name__ == "__main__":

    if check_process_already_running():
        print("Server process is already running.")
        os._exit(0)

    if "-d" in sys.argv:
        if not daemon_double_fork():
            # Only continue in forked process..
            os._exit(0)

    # Omit display of double entries
    clear_history(FEED_FAVORITES, FEED_HISTORY)

    # Syntax not supported in Python < 3.6
    # with socketserver.TCPServer(("", PORT), MyHandler) as httpd: 
    #    httpd.serve_forever()

    try:
        httpd = socketserver.TCPServer((HOST, PORT), MyHandler)
    except OSError:
        # Reset stdout to print messages regardless if daemon or not
        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__
        raise

    print("Serving at port", PORT)
    print("Use localhost:{0}/?feed=[url] to read feed".format(PORT))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()
    except:
        httpd.shutdown()
        raise

    print("END")