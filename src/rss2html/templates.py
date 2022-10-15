#!/usr/bin/python3
# -*- coding: utf-8 -*-

import os.path
from random import randint

from jinja2 import Environment, FileSystemLoader
# from jinja2 import FileSystemBytecodeCache
from babel.support import Translations

from . import icon_searcher
from .feed_parser import parse_pubDate

import gettext

import logging
logger = logging.getLogger(__name__)

# Template filters
def get_icon_for_mimetype(mime):
    return icon_searcher.get_icon_path(mime)

def get_clipped_media_name(media_name, max_len):
    if len(media_name) <= max_len:
        return media_name

    # Remove params
    if "?" in media_name:
        media_name = media_name[:media_name.find("?")]

    last_dot = media_name.rfind(".")
    extension_len = (len(media_name) - last_dot)
    if (last_dot == -1 or max_len < 10 or
            extension_len >= max_len-10 ):
        return media_name[:max_len] + "…"

    return "{}…{}".format(
        media_name[:max_len - extension_len],
        media_name[last_dot+1:]
    )

def convert_pub_date(pubDate, date_format=None):
    if pubDate:
        return parse_pubDate(pubDate, date_format)

    return "Undefined date"

def random_id(_ignored):
    return randint(1, 0xFFFFFFFF)


# @babel.localeselector
def get_locale():
    return 'de'


class HtmlRenderer:
    root_dir = os.path.dirname(__file__)
    locale_dir = os.path.join(root_dir, "locale")  # "i18n"
    msgdomain = "html"
    list_of_available_locales = ["en_US", "de_DE"]
    loader = FileSystemLoader(os.path.join(root_dir, "templates"))
    # Jinja < 3.1
    # extensions = ['jinja2.ext.i18n', 'jinja2.ext.with_', 'jinja2.ext.autoescape']
    # Jinja2 >= 3.1, some extensions are build-in, now
    extensions = ['jinja2.ext.i18n']
    # bcc = FileSystemBytecodeCache('/tmp', '%s.cache')
    babel_lang_translations = {}

    def __init__(self, lang="en_US", css_style=None):
        if lang not in HtmlRenderer.list_of_available_locales:
            logger.warn("Fallback on default language. '{}' is not "
                  "in list of available locales.".format(lang))
            lang = "en_US"

        self.translations = {}
        self.envs = {}
        for locale_key in HtmlRenderer.list_of_available_locales:
            logger.info("Create environment for language '{}'.".\
                       format(locale_key))
            self.translations[locale_key] = Translations.load(
                HtmlRenderer.locale_dir, locale_key)
            # add any other env options if needed
            env = Environment(
                extensions=HtmlRenderer.extensions,
                # bytecode_cache=HtmlRenderer.bcc,
                loader=HtmlRenderer.loader)
            env.install_gettext_translations(
                self.translations[locale_key])

            env.filters['get_icon'] = get_icon_for_mimetype
            env.filters['clipped_media_name'] = get_clipped_media_name
            env.filters['convert_pub_date'] = convert_pub_date
            env.filters['random_id'] = random_id

            self.envs[locale_key] = env

            self.babel_lang_translations.setdefault(
                locale_key,
                gettext.translation('messages', localedir=self.locale_dir,
                                    languages=[locale_key])
            )
            self.babel_lang_translations[locale_key].install()

        self.preferred_lang = lang
        self.extra_context = {"system_css_style": css_style}



    def run(self, filename="base.html", context=None):
        if context is None:
            context = {}

        try:
            lang = context["gui_lang"]
        except:
            lang = self.preferred_lang

        env = self.envs[lang]
        template = env.get_template(filename)

        for k in self.extra_context:
            if k not in context:
                context[k] = self.extra_context[k]

        return template.render(context)


    def gettext(self, context):
        try:
            lang = context["gui_lang"]
            return self.babel_lang_translations[lang].gettext
        except Exception as e:
            logger.warn("Fallback on default gettext function. Error: " +
                        str(e))
            return gettext.gettext

if __name__ == "__main__":
    r = HtmlRenderer()
    print(r.run(context={"title": "Test"}))
