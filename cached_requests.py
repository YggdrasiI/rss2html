#!/usr/bin/python3
# -*- coding: utf-8 -*-

import time
import ssl
import os.path
from os import mkdir

import logging
logger = logging.getLogger(__name__)

# from urllib.parse import urlparse, parse_qs, quote
from urllib.parse import urlparse
# from urllib.request import Request, urlopen
# from urllib.error import URLError, HTTPError

import certifi
from urllib3 import PoolManager, Timeout
from urllib3.exceptions import HTTPError, TimeoutError, ResponseError
from io import BytesIO

# For storage
from hashlib import sha1
from pickle import loads, dumps
from feed import Feed

import default_settings as settings


_CACHE = {}
_HTTP = None
_HTTP = PoolManager(
    cert_reqs='CERT_REQUIRED',
    ca_certs=certifi.where()
)

class CacheElement:
    # Putting this into _CACHE avoids copy of big underlying
    # strings because reference of object is returned
    def __init__(self, text, headers):
        self.byte_str = text.encode('utf-8')
        # self.text = text  # TODO: Remove redundant 'text' member variable
        self.headers = headers
        self.timestamp = int(time.time())
        self.bSaved = False

    def __getstate__(self):
        state = self.__dict__.copy()
        # del state[...]
        return state

    def __setstate__(self):
        # Objects initialized by pickle.loads are
        # tagged as already saved
        self.bSaved = True

    @classmethod
    def from_bytes(cls, byte_str, headers):
        cEl = cls("", headers)
        cEl.byte_str = byte_str
        # cEl.text = byte_str.decode('utf-8')
        return cEl

    @classmethod
    def from_file(cls, filename, headers):
        cEl = cls("", headers)
        with open(filename, 'rb',) as f:
            cEl.byte_str = f.read(-1)
            # cEl.text = cEl.byte_str.decode('utf-8')
            return cEl

        return None

    @classmethod
    def from_response(cls, res):
        cEl = cls("", dict(res.getheaders()))
        cEl.byte_str = res.data  # urllib3 style of response
        # cEl.text = cEl.byte_str.decode('utf-8')
        return cEl

    @classmethod
    def from_response_streamed(cls, res, prev_data):
        cEl = cls("", dict(res.getheaders()))
        # initial_buffer_len = int(res.getheader("Content-Length", 0))
        f = BytesIO()
        read_chunk_size = 2**16
        search_chunk_size = 2**12  # <= read_chunk_size
        # Do not use too small search_chunk_size! A false positive
        # would be fatal.

        # Read bytes from response and compare last bytes of this
        # chunk with cached values. Break up reading if we can assume
        # that the tail of the response matches the cached value.
        num_new_bytes = f.write(res.read(read_chunk_size))
        while num_new_bytes > 0:
            search_len = search_chunk_size \
                    if search_chunk_size < num_new_bytes \
                    else num_new_bytes
            f.seek(-search_len, 2)
            pos_in_cache = prev_data.find(f.read(search_len))
            if -1 < pos_in_cache:
                # Fill data with previous value.
                logger.debug("Fill up response after {} bytes with cached "
                             "file. Position in cache: {}."\
                             .format(f.tell(), pos_in_cache))
                f.write(prev_data[pos_in_cache+search_len:])
                break

            num_new_bytes = f.write(res.read(read_chunk_size))

        f.seek(0, 0)  # go back to start of file
        cEl.byte_str = f.read(-1)
        # cEl.text = cEl.byte_str.decode('utf-8')
        return cEl


def update_cache(key, cEl):
    if key == "":
        return

    cEl.bSaved = False
    _CACHE[key] = cEl


def trim_cache():
    # Unload data if maximal memory footprint is exceeded
    pass

def fetch_from_cache(feed):
    try:
        cEl = _CACHE[feed.url]
        return cEl
    except KeyError:
        pass

    try:
        cEl = _CACHE[feed.title]
        return cEl
    except KeyError:
        pass

    return None

def fetch_file(url, bCache=True, local_dir="rss_server-page/"):
    logger.debug("Url: " + url)

    cEl = _CACHE.get(url)

    headers={'User-Agent': 'Mozilla/5.0'}
    # Prepare headers for lookup of modified content
    # This allows the target server to decide if we had already
    # the newest file version.

    # Force return cached value without check of change on source
    # url if less time was
    now = int(time.time())
    if (cEl and bCache and
            (now - cEl.timestamp) < settings.CACHE_EXPIRE_TIME_S):
        # We do not want hassle the target with a new request.
        logger.debug("Skip request because current data is fresh.")
        return (cEl, 304)

    if cEl:  # and bCache:
        # Give extern server enough information to decide
        # if we had already the newest version.
        if "ETag" in cEl.headers:
            headers['If-None-Match'] = cEl.headers.get('ETag')
            # req.add_header('If-None-Match',
            #                cEl.headers.get('ETag'))
        if "Last-Modified" in cEl.headers:
            headers['If-Modified-Since'] = cEl.headers.get('Last-Modified')
            # req.add_header('If-Modified-Since',
            #                cEl.headers.get('Last-Modified'))

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
                    cElDummy = CacheElement.from_file(local_relative_path, {})
                    # cElDummy is not cached in _CACHE
                    return (cElDummy, 200)
        except Exception as e:
            logger.debug("Local file search failed for url '{}'. Error was: "
                    "'{}'".format(url, e))


        # Request new version
        response = _HTTP.request('GET', url,
                                 headers=headers,
                                 timeout=Timeout(connect=3.2, read=60.0),
                                 preload_content=False
                                )

        try:
            # Content-Length header optional/not set in all cases…
            content_len = int(response.getheader("Content-Length", 0))
            if content_len > settings.MAX_FEED_BYTE_SIZE:
                raise Exception("Feed file exceedes maximal size. {0} > {1}"
                                "".format(content_len,
                                          settings.MAX_FEED_BYTE_SIZE))
        except ValueError:
            pass

    # old urllib approach
    # except HTTPError as e:
    #     if e.code == 304:  # Not modified => Return cached value
    #         logger.debug("Extern server replies: No new data available. Return cached value")
    #         if cEl:
    #             return (cEl, 304)

    #     logger.debug('The server couldn\'t fulfill the request.'
    #             'Error code: {} '.format(e.code))

    # except URLError as e:
    #     logger.debug('We failed to reach a server.'
    #             'Reason: {}'.format(e.reason))
    #     if cEl:
    #         return (cEl, 304)
    #

    # urllib3
    except TimeoutError as e:
        logger.debug("Server request timed out.")
        if cEl:
            return (cEl, 304)

    except ResponseError as e:
        logger.debug('ResponseError: '.format(str(e)))
        if cEl:
            return (cEl, 304)

    else:
        if response.status == 304:  # Not modified => Return cached value
            cEl.timestamp = int(time.time())  # Our local data is still fresh
            logger.debug("Extern server replies: No new data available. Return cached value")
            if cEl:
                return (cEl, 304)

        # everything is fine

        if cEl and bCache and len(cEl.byte_str) > 10000:
            cEl =  CacheElement.from_response_streamed(response, cEl.byte_str)
        else:
            cEl = CacheElement.from_response(response)

        response.release_conn()  # preload_content=False requires this

        # Check needed for responses without Content-Length header
        # and responses with wrong header vaules.
        if len(cEl.byte_str) > settings.MAX_FEED_BYTE_SIZE:
            raise Exception("Feed file exceedes maximal size. {0} > {1}"
                            "".format(len(cEl.byte_str),
                                      settings.MAX_FEED_BYTE_SIZE))

        update_cache(url, cEl)

        if settings.CACHE_DIR and False:
            # Write file to disk
            feed = Feed(url, url)
            store_cache([feed])


        return (cEl, 200)

    return (None, 404)


def gen_cache_filename(feed_name):
    s = sha1()
    s.update(feed_name.encode('utf-8'))
    return s.hexdigest()[:16]


def gen_cache_dirname(bCreateFolder=False):
    if not settings.CACHE_DIR:
        return None

    dirname = os.path.join(settings.CACHE_DIR, "rss_server_cache")
    if bCreateFolder and not os.path.isdir(dirname):
        try:
            mkdir(dirname)
        except Exception as e:
            logger.info("Cache folder '{}' can not be created."
                    "".format(dirname));

    return dirname


def store_cache(*feed_lists):
    dirname = gen_cache_dirname()
    for idx in range(len(feed_lists)):
        for feed in feed_lists[idx]:
            filename = gen_cache_filename(feed.url)
            cEl = fetch_from_cache(feed)
            if not cEl or cEl.bSaved:
                continue

            try:
                with open(os.path.join(dirname, filename), 'wb') as f:
                    f.write(dumps(cEl))
            except Exception as e:
                logger.debug("Writing of '{}' failed. "
                "Error was: {}".format(filename, e))
            else:
                cEl.bSaved = True
                logger.debug("Writing of '{}' succeeded. ".format(filename))


def load_cache(*feed_lists):
    dirname = gen_cache_dirname()
    for idx in range(len(feed_lists)):
        for feed in feed_lists[idx]:
            filename = gen_cache_filename(feed.url)
            try:
                with open(os.path.join(dirname, filename), 'rb') as f:
                    cEl = loads(f.read(-1))
                    update_cache(feed.url, cEl)
                    # cEl.bSaved = True  # shifted logic into class
            except Exception as e:
                # logger.debug("Reading of '{}' failed. "
                # "Error was: {}".format(filename, e))
                pass
            else:
                logger.debug("Reading of '{}' succeeded. ".format(filename))
                pass


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    url = "http://in-trockenen-buechern.de/feed"
    lfeeds = [Feed("Test feed", url)]
    settings.CACHE_DIR = "."

    dirname = gen_cache_dirname(True)  # Creates dir
    if not dirname:
        print("Hey, can not create directory")

    if dirname:
        print("Load cache")
        load_cache(lfeeds)

    print("Get file first time…")
    (_, code) = fetch_file(url, local_dir=".")
    print("Http status code: {}".format(code))
    print("Wait…")
    time.sleep(2)
    print("Get file second time…")
    (_, code) = fetch_file(url, local_dir=".")
    print("Http status code: {}".format(code))

    if dirname:
        print("Save cache")
        store_cache(lfeeds)
        print("Load cache")
        load_cache(lfeeds)
