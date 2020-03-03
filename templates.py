#!/usr/bin/python3
# -*- coding: utf-8 -*-

from jinja2 import Environment, FileSystemLoader
# from jinja2 import FileSystemBytecodeCache
from babel.support import Translations

import icon_searcher


def get_icon_for_mimetype(mime):
    return icon_searcher.get_icon_path(mime)

def get_clipped_media_name(media_name, max_len):
    if len(media_name) <= max_len:
        return media_name

    last_dot = media_name.rfind(".")
    if last_dot == -1 or max_len < 10:
        return media_name[:max_len] + "…"

    return "{}…{}".format(
        media_name[:max_len - (len(media_name) - last_dot)],
        media_name[last_dot+1:]
    )

# @babel.localeselector
def get_locale():
    return 'de'


class HtmlRenderer:
    locale_dir = "locale"  # "i18n"
    msgdomain = "html"
    list_of_available_locales = ["en", "de"]
    loader = FileSystemLoader("templates")
    extensions = ['jinja2.ext.i18n', 'jinja2.ext.with_', 'jinja2.ext.autoescape']
    # bcc = FileSystemBytecodeCache('/tmp', '%s.cache')

    def __init__(self, lang="en", css_style=None):
        if lang not in HtmlRenderer.list_of_available_locales:
            logger.warn("Fallback on default language. '{}' is not "
                  "in list of available locales.".format(lang))
            lang = "en"

        self.translations = Translations.load(
            HtmlRenderer.locale_dir,
            [lang])
        # add any other env options if needed
        self.env = Environment(
            extensions=HtmlRenderer.extensions,
            # bytecode_cache=HtmlRenderer.bcc,
            loader=HtmlRenderer.loader)
        self.env.install_gettext_translations(
            self.translations)

        self.env.filters['get_icon'] = get_icon_for_mimetype
        self.env.filters['clipped_media_name'] = get_clipped_media_name
        
        self.extra_context = {"system_css_style": css_style}


    def run(self, filename="base.html", context=None):
        template = self.env.get_template(filename)

        for k in self.extra_context:
            if k not in context:
                context[k] = self.extra_context[k]

        return template.render(context)


if __name__ == "__main__":
    r = HtmlRenderer()
    print(r.run(context={"title": "Test"}))
