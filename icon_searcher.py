#!/usr/bin/python3
# -*- coding: utf-8 -*-

import sys
import os.path
import default_settings as settings  # Overriden in load_config()

GTK3 = True

try:
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk, Gio
except ImportError:
    print("Gtk3 module not available")
    GTK3 = False

FALLBACK_BASE_DIR = "/icons/oxygen-icons"
AVAILABLE_PNG = [
    "application",
    "audio",
    "imag",
    "podcast",
    "text",
    "unknown",
    "video",
]

_PATH_CACHE = {}
_FILE_CACHE = {}


def cache_local_file(local_path, uri):
    if uri in _FILE_CACHE:
        return

    if os.path.splitext(local_path)[1] not in settings.ALLOWED_FILE_EXTENSIONS:
        return

    with open(local_path, "rb") as f:
        _FILE_CACHE[uri] = f.read(-1)


def get_cached_file(uri):
    try:
        return _FILE_CACHE[uri]
    except KeyError:
        pass


def convert_local_path(local_path):
    """ As file://-urls are not allowed anymore, convert the path into
    an url, provided by rss_server.

    Be sure to call this function only for checked path!
    """
    icon = "/icons/system/{}".format(
        os.path.basename(local_path))
    return icon


def get_icon_path_fallback(mimetype, size):
    if size <= 64:
        size2 = "32x32"
    else:
        size2 = "256x256"

    if "/" in mimetype:
        prefix = mimetype[:mimetype.find("/")]
    else:
        prefix = mimetype

    if not prefix in AVAILABLE_PNG:
        prefix = "unknown"

    icon = "{}/{}/{}.png".format(FALLBACK_BASE_DIR,
                                 size2, prefix)

    return icon


if GTK3:
    def get_icon_path_gtk3(mimetype, size):
        icon = Gio.content_type_get_icon(mimetype)
        theme = Gtk.IconTheme.get_default()
        if theme is None:
            # print("No Gtk IconTheme detectable");
            return None

        info = theme.choose_icon(icon.get_names(), -1, 0)
        if info:
            # print(info.get_filename())
            return info.get_filename()
        else:
            return None


def get_icon_path(mimetype, size=32):
    try:
        return _PATH_CACHE[(mimetype, size)]
    except KeyError:
        pass

    icon = None
    if GTK3:
        local_icon = get_icon_path_gtk3(mimetype, size)
        if local_icon:
            icon = convert_local_path(local_icon)
            cache_local_file(local_icon, icon)

    if not icon:
        icon = get_icon_path_fallback(mimetype, size)

    _PATH_CACHE[(mimetype, size)] = icon
    return icon


if __name__ == "__main__":
    settings.load_config(globals())
    # Test icon search
    print(get_icon_path("application/rss+xml"))
    print(get_icon_path("audio/mpeg", 256))
    print(get_icon_path("audio/ogg;codecs=opus"))
    print(get_icon_path("audio/ogg", 64))
    print(get_icon_path("foobar/ogg", 64))
    for arg in sys.argv[1:]:
        print("Arg {} => {}".format(
            arg,
            get_icon_path("foobar/ogg", 64),
        ))
