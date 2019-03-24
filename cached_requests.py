#!/usr/bin/python3
# -*- coding: utf-8 -*-

import time

# from urllib.parse import urlparse, parse_qs, quote
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

_CACHE = {}

def update_cache(key, res, headers):
    if key == "":
        return
    _CACHE[key] = (int(time.time()), res, headers)

"""
def check_cache(settings, key):
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

def fetch_file(settings, url, bCache=True):
    print("Url: " + url)

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
            print("Return cached value")
            (_, res, _) = _CACHE[url]
            return (res, 304)

        print('The server couldn\'t fulfill the request.')
        print('Error code: ', e.code)
    except URLError as e:
        print('We failed to reach a server.')
        print('Reason: ', e.reason)
    else:
        # everything is fine
        data = response.read()
        text = data.decode('utf-8')
        # tree = ElementTree.parse(response)
        update_cache(url, text, dict(response.getheaders()))
        return (text, 200)

    return (None, 404)

if __name__ == "__main__":
    import default_settings as settings

    url = "http://in-trockenen-buechern.de/feed"
    print("Get file first time…")
    (_, code) = fetch_file(settings, url)
    print("Http status code: {}".format(code))
    print("Wait…")
    time.sleep(2)
    print("Get file second time…")
    (_, code) = fetch_file(settings, url)
    print("Http status code: {}".format(code))
