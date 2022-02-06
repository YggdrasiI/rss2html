#!/usr/bin/python3
# -*- coding: utf-8 -*-

import sys
import os
import re
from os.path import expandvars
from subprocess import Popen, PIPE
from collections import namedtuple

from urllib.request import Request, urlopen
from urllib.parse import urlparse

import cached_requests
import feed_parser

import logging
logger = logging.getLogger(__name__)

# TODO: Maybe remove fork/double_fork. Just used for old approach.
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

## For actions_pool usage
from actions_pool import worker_handler, PickableAction, PopenArgs, FwithArgs

# Example usage:
# If an action-handler should trigger a worker procsses
# to call the function 'example_pick' return
# PickableAction(ExamplePick)
#
# See download_with_wget() for a practial example.
def example_pick(s):
    print(s)
ExamplePick = FwithArgs(f=example_pick, args=("test",))


#############################################################

##
def can_download(feed, url, settings):
    target_dir = expandvars(settings.DOWNLOAD_DIR)
    if os.path.isdir(target_dir) or os.path.islink(target_dir):
        return True

    return False


def can_play(feed, url, settings):
    return True

##
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

        try:
            os.makedirs(target_dir, exist_ok=True)
            # => I.e. creates 'My Podcast 1'
        except OSError:
            logger.error("Can not create '{}'".format(target_dir))
            return None

        #nullsink = open(os.devnull, 'w')
        #nullsource = open(os.devnull, 'r')
        #return Popen(cmd, stdin=nullsource,
        #             stdout=nullsink, stderr=nullsink)

        # Variant for worker pool
        return PickableAction(PopenArgs(cmd))

    return wget()

# Called in this thread
def play_with_mimeopen(feed, url, settings):

    def mimeopen():
        cmd = ("mimeopen", "-n", url)

        # Bad example because this opens an own disowned new process...
        cmd2 = ("gvim", "-u", "~/.vimrc_short",
               "-c", "exe \"put ='{}'\"".format(url))

        cmd3 = ("mate-calculator")

        #print(cmd)
        #nullsink = open(os.devnull, 'w')
        #nullsource = open(os.devnull, 'r')
        #popen =  Popen(cmd, stdin=nullsource,
        #            stdout=nullsink, stderr=nullsink)
        #
        #return popen.wait()

        return PickableAction(PopenArgs(cmd))

    return mimeopen()


def play_with_mpv(feed, url, settings):
    cmd = ("mpv", url)
    return PickableAction(PopenArgs(cmd))


def factory__local_cmd(lcmd):
    # Returns action function handler.
    # Split cmd into list of arguments.
    #
    # Example: factory__local_cmd(["notify-send", "RSS VIEWER", "{url}"])

    def action(feed, url, settings):
        def local_cmd():
            resolved_lcmd = [token.format(url=url) for token in lcmd]

            cmd = tuple(resolved_lcmd)
            logger.debug("Local cmd: {}".format(cmd))
            nullsink = open(os.devnull, 'w')
            nullsource = open(os.devnull, 'r')
            return Popen(cmd, stdin=nullsource,
                         stdout=nullsink, stderr=nullsink).wait


        def worker_cmd():
            resolved_lcmd = [token.format(url=url) for token in lcmd]
            cmd = tuple(resolved_lcmd)
            return PickableAction(PopenArgs(cmd))

        # return local_cmd()
        # or
        return worker_cmd()

    return action


def factory__ssh_cmd(ssh_hostname, ssh_cmd, identity_file=None, port=None):
    # Returns action function handler
    #
    # Example: factory__ssh_cmd("you@localhost", "echo '{url}'")

    def action(feed, url, settings):
        #Note: Do not define vars on this level

        def ssh():
            cmd = ["ssh", ssh_hostname, ssh_cmd.format(url=url)]
            if identity_file:
                cmd[1:1] = ["-i", "{}".format(identity_file)]
            if port:
                cmd[1:1] = ["-p", "{}".format(port)]
            cmd = tuple(cmd)

            logger.debug("SSH-Cmd: {}".format(cmd))
            nullsink = open(os.devnull, 'w')
            nullsource = open(os.devnull, 'r')
            return Popen(cmd, stdin=nullsource,
                         stdout=nullsink, stderr=nullsink).wait

        def worker_ssh():
            cmd = ["ssh", ssh_hostname, ssh_cmd.format(url=url)]
            if identity_file:
                cmd[1:1] = ["-i", "{}".format(identity_file)]
            if port:
                cmd[1:1] = ["-p", "{}".format(port)]
            cmd = tuple(cmd)

            logger.debug("SSH-Cmd: {}".format(cmd))
            return PickableAction(PopenArgs(cmd))

        # return ssh()
        # or
        return worker_ssh()

    return action

# Not serializable
def get_item_for_url(feed, url, settings):
    if True:  # if not feed.items:
        (cEl, code) = cached_requests.fetch_file(feed.url)
        if not cEl or not cEl.byte_str:
            logger.error("Fetching uncached feed '{}' failed.".format(feed.url))
            return None

        if len(feed.context)>0:
            logger.debug("Skip parsing of feed and re-use previous")
        else:
            feed_parser.parse_feed(feed, cEl.byte_str)
        for entry in feed.context["entries"]:
            for enclosure in entry["enclosures"]:
                logger.info("Compare {} with {}".format(
                    url, enclosure.get("enclosure_url")))
                if enclosure.get("enclosure_url") == url:
                    return entry

    return None

