#!/usr/bin/python3
# -*- coding: utf-8 -*-
import sys
import os.path
import logging
import logging.config

# Attention, all loggers created before fileConfig()-Call
# will be disabled!
# Import all modules with loggers after this line.
# (An other method would be enabling of them manually in set_logger_levels()).
logging_conf = os.path.join(os.path.dirname(__file__), "logging.conf")
logging.config.fileConfig(logging_conf)

'''logging.root.setLevel(logging.NOTSET)
logging.root.setLevel(0)
logging.basicConfig(level=0)'''
logger = logging.getLogger('rss_server')


from .rss_server import main

if __name__ == "__main__":
    sys.exit(main())
