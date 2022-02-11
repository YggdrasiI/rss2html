#!/usr/bin/python3
# -*- coding: utf-8 -*-
#
# Use Windows registry to find associated programm
# for given mime type or file extension.
#

import sys
import argparse
import subprocess
from winreg import OpenKey, EnumKey, EnumValue, HKEY_CLASSES_ROOT

import logging
logger = logging.getLogger(__name__)

__all__ = ['prog_for_mimetype', 'prog_for_ext']


def prog_for_mimetype(mime):
    ext = _extension_for_mime(mime)
    if ext is None:
        logger.error("No extension found for this mime type.")
        return

    return prog_for_ext(ext)


def prog_for_ext(ext):
    assoc = _assoc_for_extension(ext)

    if assoc is None:
        logger.error("No association found for this extension.")
        return

    prog = _prog_for_assoc(assoc)
    if prog is None:
        logger.error("No program found for this association")
        return -1

    return prog


def _extension_for_mime(mime):
    # Input example: 'audio/mpeg'
    # Output example: '.mp3'

    extension = None
    try:
        reg_node = OpenKey(HKEY_CLASSES_ROOT,
                'MIME\\Database\\Content Type\\' + mime )
    except FileNotFoundError:
        return None

    i = 0
    while True:
        try:
            reg_value = EnumValue(reg_node, i)
            if reg_value[0] == "Extension":
                extension = reg_value[1]
                break
            i += 1
        except OSError:
            break

    return extension


def _assoc_for_extension(extension):
    # Input example: '.mp3'
    # Output exmple: '?'

    process = subprocess.Popen(
            ['cmd', '/c', 'assoc', extension],
            stdout=subprocess.PIPE)
    out, err = process.communicate()

    if process.returncode != 0:
        print("assoc call failed. Error: {}".format(err), file=sys.stderr)
        return None

    out = out.decode('utf-8')
    file_ext = out.strip().split('=')[-1]
    return file_ext


def _prog_for_assoc(assoc):
    # Input  example 1: 'Python.File'
    # Output example 1: '"C:\Windows\py.exe" "%L" %*'
    # Input  example 2: WMP11.AssocFile.MP3
    # Output example 2: '"%ProgramFiles(x86)%\Windows Media Player\wmplayer.exe" /prefetch: 6 /Open "%L"

    value = OpenKey(HKEY_CLASSES_ROOT, assoc + '\shell\open\command')

    path = EnumValue(value, 0)[1]
    return path


def main():
    parser = argparse.ArgumentParser(

        description='Detect programm for extension or mimetype')
    parser.add_argument('-m', '--mime', type=str,
            help="")
    parser.add_argument('-e', '--ext', type=str,
            help="")

    args = parser.parse_args()

    if args.mime is None and args.ext is None:
        parser.print_help()
        return 0

    if args.mime:
        ext = _extension_for_mime(args.mime)
    else:
        ext = args.ext

    if ext is None:
        print("No extension found for this mime type.", file=sys.stderr)
        return -3

    assoc = _assoc_for_extension(ext)

    if assoc is None:
        print("No association found for this extension.", file=sys.stderr)
        return -2

    prog = _prog_for_assoc(assoc)
    if prog is None:
        print("No program found for this association", file=sys.stderr)
        return -1

    print(prog)
    return 0


if __name__ == "__main__":
    sys.exit(main())
