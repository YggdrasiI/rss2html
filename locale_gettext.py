#!/usr/bin/python3
# -*- coding: utf-8 -*-

from gettext import gettext as _

def set_gettext(renderer, context):
    globals()['_'] = renderer.gettext(context)


def gettext(*args):
    return _(*args)
