#!/usr/bin/python3
# -*- coding: utf-8 -*-

# default-src: 'chrome:'; ersetzt...
TEMPLATE_HTML_HEADER = '''<html id="feedHandler" xmlns="http://www.w3.org/1999/xhtml">
<head>
  <meta http-equiv="content-type" content="text/html; charset=UTF-8" />
  <meta http-equiv="XXXContent-Security-Policy" content="{POLICY}" />
  <link rel="stylesheet" href="subscribe.css" type="text/css" media="all" />
  <title>{{FEED_TITLE}}</title>
</head><body>
'''.format(
    POLICY="default-src chrome: 'self'; img-src * chrome:; media-src *; "
    "script-src 'self'; style-src 'self'; ",
    # POLICY="default-src chrome:; img-src moz-icon: 'self';"
)

TEMPLATE_HTML_END = '''</html>'''

TEMPLATE_NOCACHE_LINK = '''
<a href="/?{ARGS}&cache=0">Uncached Feed</a></h2>'''

TEMPLATE_FEED_HEADER = '''
  <div id="feedHeaderContainer" style="width:100%">
    <div id="feedHeader" dir="ltr" class="feedBackground">
      <h2><a href="/">Overview</a></h2>
    </div>
    <div id="feedHeaderContainerSpacer"></div>
    <div id="feedHeader" dir="ltr" class="feedBackground">
      <h2>{NOCACHE_LINK}</h2>
    </div>
  </div>
'''

TEMPLATE_BODY = '''
  <div id="feedBody">
    <div id="feedTitle">
      <a id="feedTitleLink">
        {FEED_TITLE_IMAGE}
      </a>
      <div id="feedTitleContainer">
        <h1 id="feedTitleText" >{FEED_TITLE}</h1> 
        <h2 id="feedSubtitleText" >{FEED_SUBTITLE}</h2>
      </div>
    </div>
    <div id="feedContent">
'''

TEMPLATE_BODY_END = '''
    </div>
  </div>
</body>
'''

TEMPLATE_ENTRY = '''
      <div class="entry">
        <h3><a href="{ENTRY_URL}"><span>{ENTRY_TITLE}</span></a>
          <div class="lastUpdated">{ENTRY_LAST_UPDATE}</div>
          </h3>
        {ENTRY_CONTENT}
        {ENTRY_ENCLOSURES}
      </div>
      <div style="clear: both;"></div>
'''

TEMPLATE_TITLE_IMG = '''
        <img id="feedTitleImage" src="{IMAGE_URL}"
        title="{IMAGE_TITLE}" />
'''
TEMPLATE_ENTRY_CONTENT = '<div class="feedEntryContent">{ENTRY_CONTENT}</div>'
TEMPLATE_ENTRY_ENCLOSURES = '''
        <div class="enclosures">Medien-Dateien
          {ENTRY_ENCLOSURES}
        </div>
'''

TEMPLATE_ENCLOSURE = '''
          <div class="enclosure">
             <img class="type-icon" src="moz-icon://.?size=16&contentType={ENCLOSURE_TYPE}" />
             <a href="{ENCLOSURE_URL}">{ENCLOSURE_FILENAME}</a> ({ENCLOSURE_TYPE}, {ENCLOSURE_LENGTH})
          </div>
'''

TEMPLATE_HELP = '''<html id="feedHandler" xmlns="http://www.w3.org/1999/xhtml">
<head>
  <meta http-equiv="content-type" content="text/html; charset=UTF-8" />
  <title>Overview</title>
  <link rel="stylesheet" href="subscribe.css" type="text/css" media="all" />
</head>
<body>
<h1>Overview</h1>
<h2>Description</h2>
<p>As Firefox 64.0 removes it's internal RSS reader, this script replaces the
functionality.<br />
It converts a 2.0 RSS feed into html page (similar looking to FF's version).</p>
<h2>Favorites</h2>
<p>{FAVORITES}</p>
<h2>Other Feeds</h2>
<p>{HISTORY}</p>
<h2>URI Arguments</h2>
<p>Prepend feed url by '<i>{HOST}/?feed=</i>' to get a link 
to the html representation of the feed.</p>
<p>Add a feed to FEED_FAVORITES in 'settings.py', it's name can be used as
shortcut: <i>{HOST}/?feed={{name}}</i></p>
<h2>Miscellaneous</h2>
<ul>
<li><a href="/quit">Quit daemon</a></li>
<li><!----><a href="/refresh_templates">Reload templates variables</a></li>
</ul>
</body>
</html>
'''

TEMPLATE_FAVORITE = '''<a href="http://{HOST}/?feed={NAME}">{TITLE}</a>'''
TEMPLATE_HISTORY = '''<a href="http://{HOST}/?feed={TITLE}">{TITLE}</a>'''

TEMPLATE_MSG = '''<html id="feedHandler" xmlns="http://www.w3.org/1999/xhtml">
<head>
  <meta http-equiv="content-type" content="text/html; charset=UTF-8" />
  <title>{MSG_TYPE}</title>
  <link rel="stylesheet" href="subscribe.css" type="text/css" media="all" />
</head>
<body>
<h1>{MSG_TYPE}</h1>
<p>{MSG}</p>
</body>
</html>
'''


def gen_html(res):
    s = [TEMPLATE_HTML_HEADER.format(**res),
         TEMPLATE_FEED_HEADER.format(**res),
         TEMPLATE_BODY.format(**res)]

    for e in res["entries"]:
        sen = []
        for en in e["enclosures"]:
            sen.append(TEMPLATE_ENCLOSURE.format(**en))

        enclosures = (TEMPLATE_ENTRY_ENCLOSURES.format(
            ENTRY_ENCLOSURES=''.join(sen), **en)
            if len(sen) else "")
        s.append(TEMPLATE_ENTRY.format(
            ENTRY_ENCLOSURES=enclosures, **e)
        )

    s.append(TEMPLATE_BODY_END.format(**res))
    s.append(TEMPLATE_HTML_END.format(**res))

    return ''.join(s)


