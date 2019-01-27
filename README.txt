============  Minimal RSS Feed to Html converter.   =============

Info:
        Simple background daemon to convert RSS Feeds into html pages.
        Representation of data is similar to Firefox's variant.


Requires:
        Python >= 3.4
        pip >= 18.0
        Python packages Jinja>=2.10 babel>=2.6


Start:
  Call 'make run' and visit 'http://localhost:8888'

  Take a look into the 'Setup section' to see how you could
  configure the program.
  If you want install the programm as background daemon, 
  call 'make install_service' (requires systemd init system)


Warning:
  The URI argument 'feed' allows relayed GET requests to arbitrary websites!
  Don't made the daemon publicly available.


Setup:
  1. Call 'make check_env' to install unmet Python dependencies.
  2. (Optional) Create settings.py file and place your favorites feed URLs and
      a free port in the file:
  
        #!/usr/bin/python3
        # -*- coding: utf-8 -*-
  
        from feed import Feed
  
        PORT = 8888
        FAVORITES = [
            Feed("example", "http://www.deutschlandfunk.de/podcast-das-war-der-tag.803.de.podcast",
                 "Example Feed (&lt;channel&gt;&lt;title&gt;-value, optional)"),
        ]
  
      Place this file in $HOME/.config/rss2html (Linux) or
                         %APPDATA%/rss2html (Windows) or
                         this folder
  
  
  3. Start background service: python3 rss_server.py [-d]
  
  4. Visit localhost:8888/?feed=[your feed url]
     to view the feed similar to FF <= 63.x.
  
  5. (Optional) Combine FF's 'Open with'-dialog for RSS-feeds
     with the 'rss_reader' script.
     This will open the feed content in a new browser tab.
  
     (Linux)
     The list of applications in the 'Open With'-dialog
     depends from the entries in '/usr/share/applications'.
  
     To extend this dialog with 'rss_reader':
     3.1 Copy 'rss_reader.desktop' into above folder and
     3.2 Copy 'rss_reader' into '/usr/local/bin' (or edit the path in 'rss_reader.desktop')
  
 
 Developing:
    To add a new language:
      1. Add language code in Makefile to SUPPORTED_LANGS
      2. Run 'make babel_compile'
    
    To update existing localization's:
      1. Run 'make babel_prepare babel_update' to update *.pot- and *.po-files
      2. Edit /locale/{LANG CODE}/LC_MESSAGES/messages.po
      3. Run 'make babel_compile'
