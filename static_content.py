#!/usr/bin/python3
# -*- coding: utf-8 -*-

from io import BytesIO
import sys
import os

import hashlib

import logging
logger = logging.getLogger(__name__)

import default_settings as settings  # Overriden in load_config()

__css_output = None
def action_icon_dummy_classes(handler):
    # Because Browser does not support CSS3's expressions like
    # background-image:attr(some_attr_name url, fallback.png)
    # we prepares some classes with this information.
    # (This approach avoids inline style code.)

    global __css_output
    if __css_output is None:
        logger.debug("Begin generation of css file for actions.")

        context = handler.context
        context.update({"actions": settings.ACTIONS})
        css = handler.server.html_renderer.run("action_icons.css",
                                            handler.context)

        output = BytesIO()
        output.write(css.encode('utf-8'))

        # Etag
        etag = '"{}"'.format( hashlib.sha1(output.getvalue()).hexdigest())

        __css_output = (output, etag)
        logger.debug("End generation of css file for actions.")

    output, etag = __css_output

    browser_etag = handler.headers.get("If-None-Match", "")
    if etag == browser_etag:
        handler.send_response(304)
        handler.send_header('ETag', etag)
        handler.send_header('Cache-Control', "public, max-age=0, ")
        handler.send_header('Content-Location', "/css/action_icons.css")
        handler.send_header('Vary', "ETag, User-Agent")
        handler.end_headers()
        return None

    handler.send_response(200)

    # Preparation for 304 replys....
    # Note that this currently only works with Chromium, but not FF
    handler.send_header('ETag', etag)
    handler.send_header('Cache-Control', "public, max-age=10, ")
    handler.send_header('Content-Location', "/index.html")
    handler.send_header('Vary', "ETag, User-Agent")

    # Other headers
    handler.send_header('Content-Length', output.tell())
    handler.send_header('Content-type', 'text/css')
    handler.end_headers()

    # Push content
    handler.wfile.write(output.getvalue())
