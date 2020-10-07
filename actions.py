#!/usr/bin/python3
# -*- coding: utf-8 -*-

import sys
import os
import re
from os.path import expandvars
from subprocess import Popen, PIPE

from urllib.request import Request, urlopen
from urllib.parse import urlparse

import cached_requests
import feed_parser

import logging
logger = logging.getLogger(__name__)

def fork(handler):
    # Do not block, but kill process if rss_server processes will be closed.

    pid = os.fork()
    if pid == 0:
        try:
            ret = handler()  # None or Popen
            if isinstance(ret, subprocess.Popen):
                ret.wait()  # Popen.wait…
        finally:
            os._exit(0)

def double_fork(handler):
    # Use double fork to start programm as new process
    pid = os.fork()
    if pid == 0:
        pid2 = os.fork()
        os.setsid()  # Posix: Decouple from parent process
        if pid2 == 0:
            # Continue with second child process
            handler().wait()  # Popen.wait…
            os._exit(0)
        else:
            os._exit(0)  # Quit first child process
    else:
        # Wait on first child process
        os.waitpid(pid, 0)


def can_download(feed, url, settings):
    target_dir = expandvars(settings.DOWNLOAD_DIR)
    if os.path.isdir(target_dir) or os.path.islink(target_dir):
        return True

    return False


def can_play(feed, url, settings):
    return True


def download_with_wget(feed, url, settings):
    target_root = settings.DOWNLOAD_DIR
    # => I.e. $HOME/Downloads

    target_root = expandvars(target_root)
    # => I.e. /home/rss_server/Downloads

    # Derive item_title, etc
    entry = get_item_for_url(feed, url, settings)
    try:
        item_title = entry["title"]
        pubDate = entry["pubDate"]
        item_guid = entry["guid"]
    except (TypeError, KeyError):
        logger.warn("Can not evaluate item_title.")
        logger.warn("Entry: {}".format(entry))
        item_title = None
        pubDate = ""
        item_guid = ""

    if pubDate:
        pubDate = feed_parser.parse_pubDate(pubDate, settings.PUB_DATE_FORMAT)

    if item_guid:
        # Some feeds use the url as guid.
        # Avoid some chars in file/folder names.
        item_guid = item_guid.replace(".", "_")
        item_guid = re.sub(r"([\/:\\])", r"", item_guid)

    # Derive subdirectories and pathname from DOWNLOAD_NAMING_SCHEME
    target_path = os.path.join(target_root, settings.DOWNLOAD_NAMING_SCHEME)
    keys_later_resolved = ["basename", "file_ext", "item_title"]
    target_path = target_path.format(
        feed_name=feed.name,
        feed_title=feed.title,
        item_guid=item_guid,
        pub_date=pubDate,
        **dict([(k, "{{{}}}".format(k)) \
                for k in keys_later_resolved])
    )
    # => I.e. /home/rss_server/Downloads/My Podcast 1/{basename}

    def wget():
        # Get filename of download. If the url does not
        # contain the filename, evaluate it from Content-disposition
        # header.
        cmd_pre = ("wget", "--spider", "--debug", url)
        # spider = run(cmd_pre, capture_output=True)  # Not in Python 3.4
        # spider_output = spider.stderr.decode('utf-8')

        spider = Popen(cmd_pre, stdout=PIPE, stderr=PIPE).communicate()
        spider_output = spider[1].decode('utf-8')

        filename_in_header = re.search(
            "Content-disposition[^\r\n]*filename=([^\r\n]*)",
            spider_output)
        if filename_in_header:
            basename = filename_in_header.group(1)
            file_ext = os.path.splitext(basename)[1]
        else:
            basename = os.path.basename(urlparse(url).path)
            file_ext = os.path.splitext(basename)[1]

        # Replace open keys. Avoid same variable name as outer scope
        target_path_ = target_path.format(
            basename=basename,
            file_ext=file_ext,
            item_title=item_title if item_title else basename,
        )

        target_dir = os.path.dirname(target_path_)
        target_file = os.path.basename(target_path_)
        cmd = ("wget",
               # "--content-disposition",  # useless/wrong with -O
               # "--directory-prefix", target_dir,  # useless with -O
               "-O", target_path_,
               url)
        # cmd = ("touch", target_path_)

        try:
            os.makedirs(target_dir, exist_ok=True)
            # => I.e. creates 'My Podcast 1'
        except OSError:
            logging.error("Can not create '{}'".format(target_dir))
            return None

        nullsink = open(os.devnull, 'w')
        nullsource = open(os.devnull, 'r')
        return Popen(cmd, stdin=nullsource,
                     stdout=nullsink, stderr=nullsink)

    # wget()
    return fork(wget)

def play_with_mimeopen(feed, url, settings):
    # Dangerous because mimeopen could return program to execute code?!

    def mimeopen():
        cmd = ("mimeopen", "-n", url)
        nullsink = open(os.devnull, 'w')
        nullsource = open(os.devnull, 'r')

        return Popen(cmd, stdin=nullsource,
                    stdout=nullsink, stderr=nullsink)

    double_fork(mimeopen)


def play_with_mpv(feed, url, settings):

    def mpv():
        cmd = ("mpv", url)
        nullsink = open(os.devnull, 'w')
        nullsource = open(os.devnull, 'r')

        return Popen(cmd, stdin=nullsource,
                    stdout=nullsink, stderr=nullsink)

    double_fork(mpv)


def factory__ssh_cmd(ssh_hostname, ssh_cmd, identity_file=None):
    # Returns action function handler
    #
    # Example: factory__ssh_cmd("you@localhost", "echo '{url}'")

    def action(feed, url, settings):
        def ssh():
            if identity_file:
                cmd = ("ssh", "-i", "{}".format(identity_file),
                        ssh_hostname, ssh_cmd.format(url=url))
            else:
                cmd = ("ssh", ssh_hostname, ssh_cmd.format(url=url))

            logging.debug("SSH-Cmd: {}".format(cmd))

            nullsink = open(os.devnull, 'w')
            nullsource = open(os.devnull, 'r')
            return Popen(cmd, stdin=nullsource,
                         stdout=nullsink, stderr=nullsink)

        fork(ssh)

    return action


def get_item_for_url(feed, url, settings):
    if True:  # if not feed.items:
        (text, code) = cached_requests.fetch_file(feed.url)
        if not text:
            logger.error("Fetching uncached feed '{}' failed.".format(feed.url))
            return None

        feed_parser.parse_feed(feed, text)
        for entry in feed.context["entries"]:
            for enclosure in entry["enclosures"]:
                logger.info("Compare {} with {}".format(
                    url, enclosure.get("enclosure_url")))
                if enclosure.get("enclosure_url") == url:
                    return entry

    return None

