#!/usr/bin/python3
# -*- coding: utf-8 -*-

import sys
import os
from os.path import expandvars
from subprocess import Popen

from urllib.request import Request, urlopen

def fork(handler):
    # Do not block, but kill process if rss_server processes will be closed.

    pid = os.fork()
    if pid == 0:
        try:
            handler().wait()  # Popen.wait…
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


def can_download(url, settings):
    return True


def can_play(url, settings):
    return True


def download_with_wget(url, settings):
    target_dir = expandvars(settings.DOWNLOAD_DIR)
    cmd = ("echo", "wget",
           "--directory-prefix", target_dir,
           url)

    # Popen(cmd) # Do not wait...
    nullsink = open(os.devnull, 'w')
    nullsource = open(os.devnull, 'r')
    return Popen(cmd, stdin=nullsource,
                 stdout=nullsink, stderr=nullsink)


def play_with_mimeopen(url, settings):
    # Dangerous because mimeopen could return program to execute code?!

    def mimeopen():
        cmd = ("mimeopen", "-n", url)
        nullsink = open(os.devnull, 'w')
        nullsource = open(os.devnull, 'r')

        return Popen(cmd, stdin=nullsource,
                    stdout=nullsink, stderr=nullsink)

    double_fork(mimeopen)


def play_with_mpv(url, settings):

    def mpv():
        cmd = ("mpv", url)
        nullsink = open(os.devnull, 'w')
        nullsource = open(os.devnull, 'r')

        return Popen(cmd, stdin=nullsource,
                    stdout=nullsink, stderr=nullsink)

    double_fork(mpv)


def factory__ssh_cmd(ssh_hostname, ssh_cmd):
    # Returns action function handler
    #
    # Example: factory__ssh_cmd("you@localhost", "echo '{url}'")

    def action(url, settings):
        def ssh():
            cmd = ("ssh", ssh_hostname, ssh_cmd.format(url=url))

            # Popen(cmd)
            nullsink = open(os.devnull, 'w')
            nullsource = open(os.devnull, 'r')
            return Popen(cmd, stdin=nullsource,
                         stdout=nullsink, stderr=nullsink)

        fork(ssh)

    return action


