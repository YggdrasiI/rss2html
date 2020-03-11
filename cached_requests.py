#!/usr/bin/python3
# -*- coding: utf-8 -*-

import time
import ssl
import os.path

import logging
logger = logging.getLogger(__name__)

# from urllib.parse import urlparse, parse_qs, quote
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

import default_settings as settings


_CACHE = {}

def update_cache(key, res, headers):
    if key == "":
        return
    _CACHE[key] = (int(time.time()), res, headers)

"""
def check_cache(key):
    if key in _CACHE:
        now = int(time.time())
        (t, res, headers) = _CACHE.get(key)
        if (now - t) < settings.CACHE_EXPIRE_TIME_S:
            print("Use cache")
            return res

    return None
"""

def fetch_from_cache(feed):
    try:
        (_, res, _) = _CACHE[feed.url]
        return res
    except KeyError:
        pass

    try:
        (_, res, _) = _CACHE[feed.title]
        return res
    except KeyError:
        pass

    return None

def fetch_file(url, bCache=True, local_dir="rss_server-page/"):
    logger.debug("Url: " + url)

    req = Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    if bCache:
        try:
            (_, _, headers) = _CACHE[url]
            if "ETag" in headers:
                req.add_header('If-None-Match',
                               headers.get('ETag'))
            if "Last-Modified" in headers:
                req.add_header('If-Modified-Since',
                               headers.get('Last-Modified'))
        except KeyError:
            pass

    try:

        # Workaround for self signed certificate on own
        # address. Read (some) files directly.
        try:
            parsed_url = urlparse(url)
            port = parsed_url.port if parsed_url.port else 80
            host = parsed_url.hostname
            if (port == settings.PORT and host in [
                settings.HOST, "localhost", "::1", "127.0.0.1"]):

                if (os.path.splitext(parsed_url.path)[1] in [".xml"]
                        and "../" not in parsed_url.path):
                    local_relative_path = os.path.join(
                            local_dir.lstrip("/"),
                            parsed_url.path.lstrip("/"))
                    logger.debug("Fetch local file '{}'".format(
                        local_relative_path))
                    text = load_xml(local_relative_path)
                    return (text, 200)
        except Exception as e:
            logger.debug("Local file search failed for url '{}'. Error was: "
                    "'{}'".format(url, e))

        response = urlopen(req, timeout=10)
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
        if e.code == 304:  # Not modified => Return cached value
            logger.debug("Return cached value")
            (_, res, _) = _CACHE[url]
            return (res, 304)

        logger.debug('The server couldn\'t fulfill the request.')
        logger.debug('Error code: ', e.code)
    except URLError as e:
        logger.debug('We failed to reach a server.')
        logger.debug('Reason: ', e.reason)
    else:
        # everything is fine
        data = response.read()
        text = data.decode('utf-8')
        # tree = ElementTree.parse(response)
        update_cache(url, text, dict(response.getheaders()))
        return (text, 200)

    return (None, 404)


def load_xml(filename):
    with open(filename, 'rt') as f:
        text = f.read(-1)
        return text

    return None


if __name__ == "__main__":
    url = "http://in-trockenen-buechern.de/feed"
    print("Get file first time…")
    (_, code) = fetch_file(url, local_dir=".")
    print("Http status code: {}".format(code))
    print("Wait…")
    time.sleep(2)
    print("Get file second time…")
    (_, code) = fetch_file(url, local_dir=".")
    print("Http status code: {}".format(code))
