#!/usr/bin/python3
# -*- coding: utf-8 -*-
#
# Alternative for 'wget' if it is not
# available, e.g. on Windows.
#

import os.path
import posixpath
from urllib.parse import urlsplit
from urllib3 import PoolManager, Retry
from urllib3.exceptions import HTTPError, TimeoutError, ResponseError,\
        MaxRetryError, SSLError
import urllib3

import logging
logger = logging.getLogger(__name__)


def download(http, url, *,
             target_dir="", target_name="", path_handler=None):
    # Downloads file without holding whole content in memory.

    try:
        res = http.request("GET", url,
                     retries=Retry(3, redirect=20),
                     preload_content=False)

        headers = res.getheaders()

        # Check for alternative target filename
        path = urlsplit(url).path
        filename = posixpath.basename(path)
        filename = headers.get("Content-Disposition", filename)

        if path_handler:
            (target_dir, target_name) = path_handler(
                target_dir, target_name, filename)
        elif filename != "":
            target_name = filename

        filepath = os.path.join(target_dir, target_name)
        logger.debug("Download target: '{}'".format(filepath))

        # Write result
        read_chunk_size = 2**22  # 4 MB
        with open(filepath, "wb") as f:
            num_new_bytes = f.write(res.read(read_chunk_size))
            while num_new_bytes > 0:
                num_new_bytes = f.write(res.read(read_chunk_size))

    except (TimeoutError, MaxRetryError, ResponseError, SSLError) as e:
        logger.debug('{}: {}'.format(type(e).__name__, str(e)))
    except Exception as e:
        raise(e)



if __name__ == "__main__":
    http = PoolManager()
    url = "https://github.com/YggdrasiI/rss2html/raw/master/screenshots/screenshot_01.png"
    target_dir = "/dev/shm/"

    download(http, url, target_dir=target_dir)
