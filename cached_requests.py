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
from urllib3.exceptions import HTTPError, TimeoutError, ResponseError,\
        MaxRetryError, SSLError
from io import BytesIO
# from ssl import SSLError

# For storage
from hashlib import sha1
from pickle import loads, dumps
from pathlib import Path
from feed import Feed, bytes_str, gen_hash

import default_settings as settings

CACHE_DIR_NAME = "rss_server_cache"

_CACHE = {}
_HTTP = None
_HTTP = PoolManager(
    cert_reqs='CERT_REQUIRED',
    # cert_reqs='CERT_NONE',
    ca_certs=certifi.where()
)

class CacheElement:
    # Putting this into _CACHE avoids copy of big underlying
    # strings because reference of object is returned
    def __init__(self, text, headers):
        self.byte_str = text.encode('utf-8')
        # self.text = text  # TODO: Remove redundant 'text' member variable
        self.headers = dict() if headers is None else headers
        self.timestamp = int(time.time())
        self.bSaved = False

    def __getstate__(self):
        state = self.__dict__.copy()
        # del state[...]
        return state

    def __setstate__(self, d):
        # Objects initialized by pickle.loads are
        # tagged as already saved
        self.__dict__.update(d)
        self.bSaved = True

    def memory_footprint(self):
        # Estimation of memory footprint of this object.
        return len(self.byte_str)

    def store(self, filename):
        dirname = gen_cache_dirname()
        try:
            with open(os.path.join(dirname,filename), 'wb') as f:
                f.write(dumps(self))
        except Exception as e:
            logger.debug("Writing of '{}' failed. "
            "Error was: {}".format(filename, e))
        else:
            self.bSaved = True
            logger.debug("Writing of '{}' succeeded. ".\
                    format(filename))

    @classmethod
    def load(cls, filename):
        dirname = gen_cache_dirname()
        try:
            with open(os.path.join(dirname,filename), 'rb') as f:
                cEl = loads(f.read(-1))
                # cEl.bSaved is now True
        except Exception as e:
            #logger.debug("Reading of '{}' failed. "
            #        "Error was: {}".format(filename, e))
            return None
        else:
            logger.debug("Reading of '{}' succeeded. ".format(filename))
            pass

        return cEl

    @classmethod
    def from_bytes(cls, byte_str, headers=None):
        cEl = cls("", headers)
        cEl.byte_str = byte_str
        # cEl.text = byte_str.decode('utf-8')
        return cEl

    @classmethod
    def from_file(cls, filename, headers=None):
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


def update_cache(key, cEl, bFromDisk=False):
    if key == "":
        return

    if cEl is None:
        # Omit adding empty values, but remove key
        try:
            del _CACHE[key]
        except KeyError:
            pass
        return

    logger.debug("update_cache for {}, {}".format(key, bFromDisk))
    if not bFromDisk:
        cEl.bSaved = False
    _CACHE[key] = cEl

    trim_cache()  # called too often here?!

__trim_cache_counter = 0
def trim_cache(force_memory=None, force_disk=None):
    # Unload data if maximal memory footprint is exceeded
    #
    # force_memory: None|False|True
    # force_disk: None|False|True
    #
    # If force_* value isn't set. trim_cache() will decide on
    # its own if the trimming will be started.

    trim_cache_interval_memory = 10
    trim_cache_interval_disk = 24

    global __trim_cache_counter
    __trim_cache_counter += 1

    if force_memory is False and \
            (__trim_cache_counter % trim_cache_interval_memory) == 0:
        force_memory = True

    if force_memory is False and \
            (__trim_cache_counter % trim_cache_interval_disk) == 0:
        force_disk = True

    if force_memory:
        footprint = cache_memory_footprint()
        if footprint  > settings.CACHE_MEMORY_LIMIT:
            logger.debug("Cache memory footprint exceeded:"\
                    "\n{} used.\n{} allowed".\
                    format(bytes_str(footprint),
                        bytes_str(settings.CACHE_MEMORY_LIMIT)))
            cache_reduce_memory_footprint(int(2/3 * settings.CACHE_MEMORY_LIMIT))

    if force_disk:
        cache_reduce_disk_footprint(settings.CACHE_DISK_LIMIT)

def fetch_from_cache(feed):
    try:
        filename = feed.cache_name()
        cEl = _CACHE[filename]
        return cEl
    except KeyError:
        pass

    try:
        # cEl = _CACHE[feed.title]
        filename = gen_hash(feed.url)
        cEl = _CACHE[filename]
        logger.debug("cache_name() was not right?! This line should not be reached!")
        return cEl
    except KeyError:
        pass

    try:
        # cEl = _CACHE[feed.title]
        filename = gen_hash(feed.title)
        cEl = _CACHE[filename]
        logger.debug("cache_name() was not right?! This line should not be reached!")
        return cEl
    except KeyError:
        pass

    return None

def fetch_file(url, no_lookup_for_fresh=True, local_dir="rss_server-page/"):
    logger.debug("Url: " + url)

    # Lockup im memory
    # cEl = _CACHE.get(url)
    filename = gen_hash(url)
    cEl = _CACHE.get(filename)

    # Lookup on disk if not im memory
    if not cEl:
        cEl = CacheElement.load(filename)
        if cEl:
            update_cache(filename, cEl, bFromDisk=True)

    headers={'User-Agent': 'Mozilla/5.0'}
    # Prepare headers for lookup of modified content
    # This allows the target server to decide if we had already
    # the newest file version.

    # Force return cached value without check of change on source
    # url if less time was
    now = int(time.time())
    if (cEl and no_lookup_for_fresh and
            (now - cEl.timestamp) < settings.CACHE_EXPIRE_TIME_S):
        # We do not want hassle the target with a new request.
        logger.debug("Skip request because current data is fresh.")
        return (cEl, 304)

    if cEl:
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
                                 preload_content=False,
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
    except (TimeoutError, MaxRetryError, ResponseError, SSLError) as e:
        logger.debug('{}: '.format(type(e).__name__, str(e)))
        # raise e
        if cEl:
            # Our data is old, but the server connection failed.
            # Do not hassle server directly again.
            cEl.timestamp = now - settings.CACHE_EXPIRE_TIME_S/4
            return (cEl, 304)
        else:
            return (None, 500)

    else:
        if response.status == 304:  # Not modified => Return cached value
            cEl.timestamp = now  # Our local data is still fresh
            logger.debug("Extern server replies: No new data available. Return cached value")
            if cEl:
                return (cEl, 304)

        # everything is fine

        if cEl and no_lookup_for_fresh and len(cEl.byte_str) > 10000:
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

        update_cache(filename, cEl)

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

    dirname = os.path.join(settings.CACHE_DIR, CACHE_DIR_NAME)
    if bCreateFolder and not os.path.isdir(dirname):
        try:
            mkdir(dirname)
        except Exception as e:
            logger.info("Cache folder '{}' can not be created."
                    "".format(dirname));

    return dirname


def store_cache(*feed_lists):
    # Save all unsaved cache elements on disk
    for idx in range(len(feed_lists)):
        for feed in feed_lists[idx]:
            cEl = fetch_from_cache(feed)
            if not cEl or cEl.bSaved:
                continue

            filename = feed.cache_name()
            logger.info("Write {}".format(filename))
            cEl.store(filename)


def load_cache(*feed_lists):
    # Load cache elements from disk
    #
    # To respect the maximal memory consumption,
    # the loading stops if the barrier is reaced.
    # Not the best strategy (disrespect of timestamp),
    # but simple...
    footprint = cache_memory_footprint()
    for idx in range(len(feed_lists)):
        for feed in feed_lists[idx]:
            filename = feed.cache_name()
            cEl = CacheElement.load(filename)

            if cEl:
                footprint += cEl.memory_footprint()
                if footprint > settings.CACHE_MEMORY_LIMIT:
                    logger.debug("Stopping load_cache(). "\
                            "\n{} requested.\n{} allowed".\
                            format(bytes_str(footprint),
                                bytes_str(settings.CACHE_MEMORY_LIMIT)))
                    return

                update_cache(filename, cEl, bFromDisk=True)


def cache_memory_footprint():
    # Return consumed bytes of cache elements
    footprint = 0
    for cEl in _CACHE.values():
        footprint += cEl.memory_footprint()

    return footprint

def cache_reduce_memory_footprint(upper_bound):
    # Unload oldest elements
    footprint = 0
    to_remove = []
    for (filename, cEl) in sorted(_CACHE.items(),
            key=lambda x: x[1].timestamp, reverse=True):
        footprint2 = footprint + cEl.memory_footprint()
        if footprint2 > upper_bound:
            to_remove.append(filename)
        else:
            footprint = footprint2

    for filename in to_remove:
        logger.debug("Remove '{}' from loaded cached_requests: ".\
                format(filename))

        cEl = _CACHE[filename]
        if not cEl.bSaved:
            cEl.store(filename)
        del _CACHE[filename]


    # footprint of leftover elements
    return footprint


def cache_reduce_disk_footprint(upper_bound):
    # Avoid infinite filling of disk by deleting oldest files
    cache_dir = Path(gen_cache_dirname())

    # glob('*') is non-recursive , '**/*' recursive
    cache_files = [f for f in cache_dir.glob('*') if f.is_file()]
    consumed_bytes = 0
    n_removed = 0
    for f in sorted(cache_files,
            key=lambda x: x.stat().st_mtime, reverse=True):
        consumed_bytes += f.stat().st_size
        if consumed_bytes > upper_bound:
            logger.debug("Remove {} from cache dir.".format(f.name))

            # To be sure to not remove files in a wrong folder,
            # re-check if we're in the cache folder.
            if f.absolute().parent.name == CACHE_DIR_NAME:
                f.unlink(True)
                n_removed += 1
            else:
                logger.debug("ATTENTION, {} IS NOT IN CACHE DIRECTORY." \
                        "SKIP DELETION".format(f.name))

    logger.info("Removed {} files from cache dir.".format(n_removed))


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    url = "https://www.deutschlandfunk.de/forschung-aktuell-102.xml"
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

    # Unload cache to trigger read from disk on demmand
    print("Memory footprint: {}".format(
        cache_memory_footprint()))

    print("Unload all elements")
    cache_reduce_memory_footprint(0)

    print("Memory footprint: {}".format(
        cache_memory_footprint()))

    print("Get file third time (from disk)…")
    (_, code) = fetch_file(url, local_dir=".")
    print("Http status code: {}".format(code))

    if dirname:
        print("Clear cache dir")
        cache_reduce_disk_footprint(0)
