#!/usr/bin/python3
# -*- coding: utf-8 -*-

from http import cookies
from hashlib import sha224, sha1
from random import randint
from subprocess import Popen, PIPE, TimeoutExpired
from enum import Enum

import logging
logger = logging.getLogger(__name__)


class LoginType(Enum):
    NONE = None
    SINGLE_USER = "single_user"
    USERS = "users"

class Session():
    def __init__(self, request, secret):
        self.request = request
        self.secret = secret
        self.c = cookies.SimpleCookie()
        self.login_ok = False

    def is_logged_in(self):
        return self.login_ok

    def init(self, user, **kwargs):

        if user != "":
            session_id = str(randint(0, 1E15))

            session_hash = sha224(
                (self.secret + session_id + user).encode('utf-8')
            ).hexdigest()

            self.c["user"] = user
            self.c["session_id"] = session_id
            self.c["session_hash"] = session_hash

            self.add_cookie_directives()
            self.login_ok = True

            return True

        return False

    def uninit(self):
        self.c["session_id"] = "-1"
        self.c["session_hash"] = "-1"
        self.c["session_id"]["max-age"] = -1  # triggers deletion
        self.c["session_hash"]["max-age"] = -1
        self.login_ok = False

    def clear(self):
        # Remove login releated values from cookies.
        # self.c.pop("user", None)
        self.c.pop("session_id", None)
        self.c.pop("session_hash", None)
        self.login_ok = False

    def add_cookie_directives(self):
        # Metadata
        if True:
            self.c["user"]["max-age"] = 31536000        # year
            # self.c["session_id"]["max-age"] = 604800    # week
            # self.c["session_hash"]["max-age"] = 604800
            self.c["session_id"]["max-age"] = 2592000   # month
            self.c["session_hash"]["max-age"] = 2592000

        else:
            # Set 'Expires' directive to omit 'session cookie' behaviour
            # (No effect in FF 81.0?! ...)
            exp = "Fri, 31-Dec-2021 20:00:00 GMT"
            self.c["user"]["expires"] = exp
            self.c["session_id"]["expires"] = exp
            self.c["session_hash"]["expires"] = exp

        try:
            self.c["user"]["samesite"] = "Strict"
            self.c["session_id"]["samesite"] = "Strict"
            self.c["session_hash"]["samesite"] = "Strict"
        except cookies.CookieError:
            pass  # Requires Python >= 3.8

        self.c["session_id"]["httponly"] = True
        self.c["session_hash"]["httponly"] = True

        # Browser only sends them over https
        # self.c["session_id"]["secure"] = True
        # self.c["session_hash"]["secure"] = True


    def get(self, key, default=""):
        # Return value of Morsel object
        try:
            val = self.c[key].value
        except KeyError:
            val = default

        return val

    def get_logged_in(self, key, default=""):
        if not self.is_logged_in():
            return default

        return self.get(key, default)

    def load(self):
        self.c.load(self.request.headers.get("Cookie", ""))
        user = self.get("user", "")
        session_id = self.get("session_id", "-1")

        if session_id != "-1":
            # logger.debug("Session User:" + user)
            # logger.debug("Session Id:" + session_id)
            session_hash = self.get("session_hash", "-1")

            # Check cookie
            session_hash2 = sha224(
                (self.secret + session_id  + user).encode('utf-8')
            ).hexdigest()

            if not session_hash == session_hash2:
                logger.debug("Hey, session params not match!")
                # self.c.clear()  # Deletes too much
                self.clear()
                self.login_ok = False
            else:
                self.login_ok = True

        else:
            # self.c.clear()  # Deletes too much
            self.clear()

            if user:
                logger.debug("User (not logged in): " + self.get("user"))


    def save(self):
        logger.debug("Session Type: " + str(type(self)))
        logger.debug("Save cookies\n"+self.c.output())
        self.request.send_header(
            "Set-Cookie", self.c.output(header="",
                                        sep="\r\nSet-Cookie:"))
        # Less ugly, but this does not work:
        # self.request.wfile.write(self.c.output().encode('utf-8'))


class LoginFreeSession(Session):
    # No users at all. Do not touch cookies and failing on each
    # operation which needs a login.

    def init(self, user, **kwargs):
        # Do not set/overwrite cookie values
        # self.login_ok = False
        return True

    def load(self):
        # Cookie loading still required for css style sheed
        self.c.load(self.request.headers.get("Cookie", ""))
        # Delete user related cookie values, if any
        self.clear()
        # self.login_ok = False


# Login everyone as "default" user
class DefaultUserSession(Session):
    def init(self, user, **kwargs):
        self.c["user"] = user
        # self.c["session_id"] = "0"
        self.c["session_id"] = str(randint(0, 1E15))
        self.c["session_hash"] = "0"
        self.add_cookie_directives()
        self.login_ok = True
        return True

    def load(self):
        self.c.load(self.request.headers.get("Cookie", ""))
        # user, session_id and session_hash are arbitary
        self.login_ok = True

        # Overwrite user value.
        # It can be != default if LOGIN_TYPE was changed.
        self.c["user"] = "default"


# Check agains explicit list of users from settings.py
class ExplicitSession(Session):
    def init(self, user, password, settings, **kwargs):
        if not hasattr(settings, "USERS"):
            return False

        if not user in settings.USERS:
            return False

        user_settings = settings.USERS[user]
        if "password" in user_settings and \
           password == user_settings["password"]:
            return super().init(user, **kwargs)

        if "hash" in user_settings and \
           sha1(password.encode('utf-8')).hexdigest() == user_settings["hash"]:
            return super().init(user, **kwargs)

        return False


SESSION_TYPES = {
    LoginType.NONE: LoginFreeSession,
    LoginType.SINGLE_USER: DefaultUserSession,
    LoginType.USERS: ExplicitSession,
}

def init_session(request, settings):
    Session = SESSION_TYPES.get(settings._LOGIN_TYPE, ExplicitSession)
    return Session(request, settings.ACTION_SECRET)

