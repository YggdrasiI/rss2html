#!/usr/bin/python3
# -*- coding: utf-8 -*-

"""Add HTTP compression support to http.server.

When a request sent by the client includes an Accept-Encoding header, the
server handles the value (eg "gzip", "x-gzip" or "deflate") and tries to
compress the response body with the requested algorithm.

Class HTTPCompressionRequestHandler extends SimpleHTTPRequestHandler with
2 additional attributes:
- compressed_types: the list of mimetypes that will be returned compressed by
  the server. By default, it is set to a list of commonly compressed types.
- compressions: a mapping between an Accept-Encoding value and a generator
  that produces compressed data.

Chunked Transfer Encoding is used to send the compressed response.

Adaption of following source:
    https://github.com/PierreQuentel/httpcompressionserver
"""

__version__ = "0.4"

__all__ = [
    "ThreadingHTTPServer", "HTTPCompressionRequestHandler"
]

import sys
import os
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from http.cookiejar import split_header_words
from io import BytesIO
# import socket
from socketserver import ThreadingMixIn
from urllib.parse import urlsplit, urlunsplit
from functools import partial
from itertools import chain

from hashlib import sha1 # For ETag

from http import HTTPStatus
from http.server import (HTTPServer, BaseHTTPRequestHandler,
    SimpleHTTPRequestHandler, CGIHTTPRequestHandler,
    _url_collapse_path, test)

# Python might be built without zlib
try:
    import zlib
except ImportError:
    zlib = None

try:
    import brotlicffi as brotli
except ImportError:
    import brotli

BROTLI_COMPRESSION_RATE=2  # Range 0(fastest) … 11(best/default)

DEFAULT_BIND = '0.0.0.0'


# List of commonly compressed content types, copied from
# https://github.com/h5bp/server-configs-apache.
COMMONLY_COMPRESSED_TYPES = [
    "application/atom+xml",
    "application/javascript",
    "application/json",
    "application/ld+json",
    "application/manifest+json",
    "application/rdf+xml",
    "application/rss+xml",
    "application/schema+json",
    "application/vnd.geo+json",
    "application/vnd.ms-fontobject",
    "application/x-font-ttf",
    "application/x-javascript",
    "application/x-web-app-manifest+json",
    "application/xhtml+xml",
    "application/xml",
    "font/eot",
    "font/opentype",
    "image/bmp",
    "image/svg+xml",
    "image/vnd.microsoft.icon",
    "image/x-icon",
    "text/cache-manifest",
    "text/css",
    "text/html",
    "text/javascript",
    "text/plain",
    "text/vcard",
    "text/vnd.rim.location.xloc",
    "text/vtt",
    "text/x-component",
    "text/x-cross-domain-policy",
    "text/xml"
]

# Generators for HTTP compression

def _zlib_producer(fileobj, wbits):
    """Generator that yields data read from the file object fileobj,
    compressed with the zlib library.
    wbits is the same argument as for zlib.compressobj.
    """
    bufsize = 2 << 17
    producer = zlib.compressobj(wbits=wbits)
    with fileobj:
        while True:
            buf = fileobj.read(bufsize)
            if not buf: # end of file
                yield producer.flush()
                return
            yield producer.compress(buf)

def _gzip_producer(fileobj):
    """Generator for gzip compression."""
    return _zlib_producer(fileobj, 31)

def _deflate_producer(fileobj):
    """Generator for deflate compression."""
    return _zlib_producer(fileobj, 15)

def _brotli_producer(fileobj):
    """Generator for brotli compression."""
    bufsize = 2 << 17
    producer = brotli.Compressor(
        mode=brotli.MODE_TEXT,
        quality=BROTLI_COMPRESSION_RATE)
    with fileobj:
        while True:
            buf = fileobj.read(bufsize)
            if not buf: # end of file
                yield producer.finish()
                return
            yield producer.process(buf)


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class HTTPCompressionRequestHandler(SimpleHTTPRequestHandler):

    """Extends SimpleHTTPRequestHandler to support HTTP compression
    """

    server_version = "CompressionHTTP/" + __version__
    protocol_version = 'HTTP/1.1'

    # List of Content Types that are returned with HTTP compression.
    # Set to the COMMONLY_COMPRESSED_TYPES by default.
    compressed_types = COMMONLY_COMPRESSED_TYPES

    # Dictionary mapping an encoding (in an Accept-Encoding header) to a
    # generator of compressed data. By default, provided zlib is available,
    # the supported encodings are gzip and deflate.
    # Override if a subclass wants to use other compression algorithms.
    compressions = {}
    if zlib:
        compressions = {
            'br': _brotli_producer,
            'deflate': _deflate_producer,
            'gzip': _gzip_producer,
            'x-gzip': _gzip_producer # alias for gzip
        }

    prefer_brotli=True


    # Manual backport of log_message filtering from 3.11's http.server
    # https://en.wikipedia.org/wiki/List_of_Unicode_characters#Control_codes
    if sys.version_info.major == 3 and sys.version_info.minor < 11:
        _control_char_table = str.maketrans(
            {c: fr'\x{c:02x}' for c in chain(range(0x20), range(0x7f,0xa0))})
        _control_char_table[ord('\\')] = r'\\'

        def log_message(self, format, *args):
            """Log an arbitrary message.
            This is used by all other logging functions.  Override
            it if you have specific logging wishes.
            The first argument, FORMAT, is a format string for the
            message to be logged.  If the format string contains
            any % escapes requiring parameters, they should be
            specified as subsequent arguments (it's just like
            printf!).
            The client ip and current date/time are prefixed to
            every message.
            Unicode control characters are replaced with escaped hex
            before writing the output to stderr.
            """

            message = format % args
            sys.stderr.write("%s - - [%s] %s\n" %
                             (self.address_string(),
                              self.log_date_time_string(),
                              message.translate(self._control_char_table)))


    def do_GET(self):
        """Serve a GET request."""
        f = self.send_head()
        if f:
            try:
                if hasattr(f, "read"):
                    self.copyfile(f, self.wfile)
                else:
                    # Generator for compressed data
                    if self.protocol_version >= "HTTP/1.1":
                        # Chunked Transfer
                        for data in f:
                            if data:
                                self._write_chunk(data)
                        self._write_chunk(b'')
                    else:
                        for data in f:
                            self.wfile.write(data)
            finally:
                f.close()

    def _write_chunk(self, data):
        """Write a data chunk in Chunked Transfer Encoding format."""
        self.wfile.write(f"{len(data):X}".encode("ascii") + b"\r\n")
        self.wfile.write(data)
        self.wfile.write(b"\r\n")

    def send_head(self):
        """Common code for GET and HEAD commands.

        This sends the response code and MIME headers.

        Return value is either:
        - a file object (which has to be copied to the outputfile by the
        caller unless the command was HEAD, and must be closed by the caller
        under all circumstances)
        - a generator of pieces of compressed data if HTTP compression is used
        - None, in which case the caller has nothing further to do
        """
        path = self.translate_path(self.path)
        f = None
        if os.path.isdir(path):
            parts = urlsplit(self.path)
            if not parts.path.endswith('/'):
                # redirect browser - doing basically what apache does
                self.send_response(HTTPStatus.MOVED_PERMANENTLY)
                new_parts = (parts[0], parts[1], parts[2] + '/',
                             parts[3], parts[4])
                new_url = urlunsplit(new_parts)
                self.send_header("Location", new_url)
                self.end_headers()
                return None
            for index in "index.html", "index.htm":
                index = os.path.join(path, index)
                if os.path.exists(index):
                    path = index
                    break
            else:
                return self.list_directory(path)
        ctype = self.guess_type(path)
        try:
            f = open(path, 'rb')
        except OSError:
            self.send_error(HTTPStatus.NOT_FOUND, "File not found")
            return None

        try:
            fs = os.fstat(f.fileno())
            content_length = fs[6]

            # Use browser cache if possible
            if ("If-Modified-Since" in self.headers
                    and "If-None-Match" not in self.headers):
                # compare If-Modified-Since and time of last file modification
                try:
                    ims = parsedate_to_datetime(
                        self.headers["If-Modified-Since"])
                except (TypeError, IndexError, OverflowError, ValueError):
                    # ignore ill-formed values
                    pass
                else:
                    if ims.tzinfo is None:
                        # obsolete format with no timezone, cf.
                        # https://tools.ietf.org/html/rfc7231#section-7.1.1.1
                        ims = ims.replace(tzinfo=timezone.utc)
                    if ims.tzinfo is timezone.utc:
                        # compare to UTC datetime of last modification
                        last_modif = datetime.fromtimestamp(
                            fs.st_mtime, timezone.utc)
                        # remove microseconds, like in If-Modified-Since
                        last_modif = last_modif.replace(microsecond=0)

                        if last_modif <= ims:
                            self.send_response(HTTPStatus.NOT_MODIFIED)
                            self.end_headers()
                            f.close()
                            return None

            # Creating etag from fstat (without reading file content)
            # print(self.headers)
            # print("Etag: {}".format(str(fs)))
            etag = '"{}"'.format(sha1(str(fs).encode('ascii')).hexdigest())

            if self.headers.get("If-None-Match", "") == etag:
                # Note that the server generating a 304 response MUST generate
                # any of the following header fields that would have been sent
                # in a 200 (OK) response to the same request:
                #    Cache-Control, Content-Location, Date, ETag,
                #    Expires, and Vary.
                self.send_response(HTTPStatus.NOT_MODIFIED)
                self.send_header("ETag", etag)
                # self.send_header('Cache-Control', 'max-age=60, public')
                self.end_headers()
                f.close()
                return None

            self.send_response(HTTPStatus.OK)
            self.send_header("Content-type", ctype)
            self.send_header("Last-Modified",
                             self.date_time_string(fs.st_mtime))
            self.send_header("ETag", etag)
            # self.send_header('Cache-Control', 'max-age=60, public')

            if ctype not in self.compressed_types:
                self.send_header("Content-Length", str(content_length))
                self.end_headers()
                return f

            # Use HTTP compression if possible

            # Get accepted encodings ; "encodings" is a dictionary mapping
            # encodings to their quality ; eg for header "gzip; q=0.8",
            # encodings["gzip"] is set to 0.8
            accept_encoding = self.headers.get_all("Accept-Encoding", ())
            encodings = {}
            for accept in split_header_words(accept_encoding):
                params = iter(accept)
                encoding = next(params, ("", ""))[0]
                quality, value = next(params, ("", ""))
                if quality == "q" and value:
                    try:
                        q = float(value)
                    except ValueError:
                        # Invalid quality : ignore encoding
                        q = 0
                elif self.prefer_brotli and encoding == 'br':
                    q = 1.1
                else:
                    q = 1 # quality defaults to 1
                if q:
                    encodings[encoding] = max(encodings.get(encoding, 0), q)

            compressions = set(encodings).intersection(self.compressions)
            compression = None
            if compressions:
                # Take the encoding with highest quality
                compression = max((encodings[enc], enc)
                    for enc in compressions)[1]
            elif '*' in encodings and self.compressions:
                # If no specified encoding is supported but "*" is accepted,
                # take one of the available compressions.
                compression = list(self.compressions)[0]
            if compression:
                self.send_header("Content-Encoding", compression)
                # If at least one encoding is accepted, send data compressed
                # with the selected compression algorithm.
                producer = self.compressions[compression]
                if content_length < 2 << 18:
                    # For small files, load content in memory
                    with f:
                        content = b''.join(producer(f))
                    content_length = len(content)
                    f = BytesIO(content)
                else:
                    chunked = self.protocol_version >= "HTTP/1.1"
                    if chunked:
                        # Use Chunked Transfer Encoding (RFC 7230 section 4.1)
                        self.send_header("Transfer-Encoding", "chunked")
                        self.end_headers()
                        # Return a generator of pieces of compressed data
                        return producer(f)
                    else:  # (HTTP/1.0) case
                        if content_length < 2 << 26:
                            # For medium sized files files, load content in memory
                            with f:
                                content = b''.join(producer(f))
                            content_length = len(content)
                            f = BytesIO(content)
                        else:
                            # Strange case. Lets raise an exception but
                            # avoiding high memory consumption.
                            raise Exception('Big file requested over HTTP/1.0')
                         

            # TODO: Using chunked variant for uncompressed files, to?!
            self.send_header("Content-Length", str(content_length))
            self.end_headers()
            return f
        except:
            f.close()
            raise

    def _write_compressed(self, s, ctype, etag=None, location=None, max_age=None):
        """ Helper method for rss_server to send compressed data for 
        non-static content. 
        """
        output = BytesIO()
        output.write(s.encode('utf-8'))
        output.seek(0, os.SEEK_END)
        content_length = output.tell()
        output.seek(0)

        if max_age:
            self.send_header('Cache-Control', f'max-age={max_age}, public ')
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


        self.send_header("Content-type", ctype)

        if ctype not in self.compressed_types:
            self.send_header("Content-Length", str(content_length))
            self.end_headers()
            self.wfile.write(output.getvalue())
            return

        # Use HTTP compression if possible

        # Get accepted encodings ; "encodings" is a dictionary mapping
        # encodings to their quality ; eg for header "gzip; q=0.8",
        # encodings["gzip"] is set to 0.8
        accept_encoding = self.headers.get_all("Accept-Encoding", ())
        encodings = {}
        for accept in split_header_words(accept_encoding):
            params = iter(accept)
            encoding = next(params, ("", ""))[0]
            quality, value = next(params, ("", ""))
            if quality == "q" and value:
                try:
                    q = float(value)
                except ValueError:
                    # Invalid quality : ignore encoding
                    q = 0
            elif self.prefer_brotli and encoding == 'br':
                q = 1.1
            else:
                q = 1 # quality defaults to 1
            if q:
                encodings[encoding] = max(encodings.get(encoding, 0), q)

        compressions = set(encodings).intersection(self.compressions)
        compression = None
        if compressions:
            # Take the encoding with highest quality
            compression = max((encodings[enc], enc)
                for enc in compressions)[1]
        elif '*' in encodings and self.compressions:
            # If no specified encoding is supported but "*" is accepted,
            # take one of the available compressions.
            compression = list(self.compressions)[0]

        if compression:
            # If at least one encoding is accepted, send data compressed
            # with the selected compression algorithm.
            producer = self.compressions[compression]
            self.send_header("Content-Encoding", compression)
            if content_length < 2 << 18:
                # For small files, load content in memory
                with output:
                    content = b''.join(producer(output))
                content_length = len(content)
                output = BytesIO(content)
            else:
                chunked = self.protocol_version >= "HTTP/1.1"
                if chunked:
                    # Use Chunked Transfer Encoding (RFC 7230 section 4.1)
                    self.send_header("Transfer-Encoding", "chunked")
                    self.end_headers()
                    for data in producer(output):
                        if data:
                            self._write_chunk(data)
                    self._write_chunk(b'')
                else:
                    raise Exception('HTTP/1.0 case not covered.')


        # Uncompressed and compressed+non-chunked case
        self.send_header("Content-Length", str(content_length))
        self.end_headers()
        self.wfile.write(output.getvalue())


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('--bind', '-b', default=DEFAULT_BIND, metavar='ADDRESS',
                        help='Specify alternate bind address '
                             '[default: all interfaces]')
    parser.add_argument('port', action='store',
                        default=8000, type=int,
                        nargs='?',
                        help='Specify alternate port [default: 8000]')
    args = parser.parse_args()

    test(HandlerClass=HTTPCompressionRequestHandler,
         port=args.port, 
         bind=args.bind,
         protocol='HTTP/1.1')
