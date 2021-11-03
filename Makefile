FOLDER=$(realpath .)
USER=$(shell whoami)
PYTHON_BIN?=$(shell which python3 || which python)
SYSTEMD_INSTALL_DIR?=/etc/systemd/system

# To use subcommand output as file [ cat <(echo "Test") ]
SHELL=/bin/bash

DEBUG?=1

# Fallback position for packages which are not installed.
SITE_PACKAGES=site-packages
PIP_PACKAGES=$(shell cat "requirements.txt" | sed "s/.*/\"\0\"/")
# 'Jinja2>=2.10' \
#			 'httplib2' \
#			 'babel>=2.6' \
#			 'python-pam' \
#			 'webassets-babel>=0.3' \

# Template releated
# JINIJA_2_10=https://files.pythonhosted.org/packages/56/e6/332789f295cf22308386cf5bbd1f4e00ed11484299c5d7383378cf48ba47/Jinja2-2.10.tar.gz

# Translation releated
SUPPORTED_LANGS=en_US de_DE  # Space between entries

PYBABEL=$(shell echo -n "PYTHONPATH='$(SITE_PACKAGES)' ./site-packages/bin/pybabel")
# Use installed pybabel if available
# PYBABEL=$(shell which pybabel || echo -n "PYTHONPATH='$(SITE_PACKAGES)' ./site-packages/bin/pybabel")

help:
	@echo -e "Common targets:\n" \
		"make run                 -- Start daemon. Quit with Ctl+C.\n" \
		"make install_service     -- Install systemd service for automatic start\n" \
		"                            Service will started as user '${USER}'\n" \
		"make uninstall_service   -- Uninstall systemd service\n" \
		"make install_deps_local  -- Install dependencies locally for this user\n" \
		"make install_deps_global -- Install dependencies global on system\n" \
		"\n" \
		"    For developpers: \n" \
		"make babel_update        -- Localization: Apply source code changes in po-Files\n" \
		"make ssl                 -- Generate self signed certificates to test HTTPS.\n" \
		"                            This certicate is self-signed, thus the browers\n" \
		"                            will warns the users. If needed, replace\n" \
		"                            ssl_rss_server.[key|crt] by better ones. " \
		"make css                 -- Build CSS from LESS files.\n" \
		"" \

run: check_env ssl
	PYTHONPATH='$(SITE_PACKAGES)' $(PYTHON_BIN) rss_server.py

%.service: %.service.template
	@echo "Create systemd service file for startup."
	sed -e "s#{USER}#$(USER)#g" \
		-e "s#{FOLDER}#$(FOLDER)#g" \
		-e "s#{PYTHON_BIN}#$(PYTHON_BIN)#g" \
		-e "s#{SITE_PACKAGES}#$(SITE_PACKAGES)#g" \
		$< > $(basename $<)

create_service_file: rss_server.service

check_env:
	@PYTHONPATH='$(SITE_PACKAGES)' $(PYTHON_BIN) \
		-c "import jinja2; import babel" \
						2>/dev/null \
						|| make install_deps_local \
						|| make print_pip_upgrade 
	@echo "Python dependencies found."

install_service: rss_server.service
	sudo cp "$(FOLDER)/$<" "$(SYSTEMD_INSTALL_DIR)/$<"
	sudo systemctl daemon-reload
	sudo systemctl enable "$<"
	@echo "Service enabled, but not started. " \
		"Call 'systemctl start $<' to start service."

uninstall_service: rss_server.service
	sudo systemctl stop "$<"
	sudo systemctl disable "$<"
	sudo rm "$(SYSTEMD_INSTALL_DIR)/$<"

start_service: rss_server.service
	sudo systemctl start "$<"

build: check_env babel_compile

ssl: ssl_rss_server.key ssl_rss_server.crt

css: rss_server-page/less/default.css \
	rss_server-page/less/light.css \
	rss_server-page/less/dark.css
	mv rss_server-page/less/*.css rss_server-page/css/.

# ====================================================
clean:
	@echo "This will clean the following files:"
	@git clean -n -d .
	@echo "Continue?" && read RSS_READER_CLEAN \
		&& test -n "$${RSS_READER_CLEAN}" -a "$${RSS_READER_CLEAN}" != "no" \
		&& git clean -f -d .

# Note about --system flag: --target can not be combined with --user
# The --system flag disables the implicit --user.
# Problem occoured with Python 3.5 and pip 9.0.1
install_deps_local_old:
	$(PYTHON_BIN) -m pip install --target $(SITE_PACKAGES) --system $(PIP_PACKAGES)

install_deps_local:
	$(PYTHON_BIN) -m pip install --target $(SITE_PACKAGES) $(PIP_PACKAGES)

install_deps_global:
	sudo $(PYTHON_BIN) -m pip install $(PIP_PACKAGES)

# ====================================================
# Required for developers, only

babel_prepare:
	$(PYBABEL) -v extract -F locale/babel.config -o ./locale/messages.pot --input-dirs=.

# Overwrites existing messages.po!
babel_init:
	@for SLANG in $(SUPPORTED_LANGS) ; do \
		make locale/$${SLANG}/LC_MESSAGES/messages.po ;\
		done

babel_update: babel_prepare
	@for SLANG in $(SUPPORTED_LANGS) ; do \
		$(PYBABEL) update -l $${SLANG} -d ./locale -i ./locale/messages.pot ;\
		done
	@echo "Now, 'git diff locale' show the differences."
	@echo "Update locale/*/LC_MESSAGES/*.po and finally run 'make babel_complie'"

babel_compile:
	@for SLANG in $(SUPPORTED_LANGS) ; do \
		make locale/$${SLANG}/LC_MESSAGES/messages.mo ;\
		done

locale/messages.pot:
	make babel_prepare
	@echo "BABEL: create *.pot file"

%.po: locale/messages.pot
	$(PYBABEL) init -l $(word 2, $(subst /, ,$@)) -d ./locale -i ./locale/messages.pot ;\

%.mo: %.po
	$(PYBABEL) compile -l $(word 2, $(subst /, ,$@)) -d ./locale -i "$(@:.mo=.po)" 
	
print_pip_upgrade:
	@echo "Installing of packages failed. Maybe your pip version is outdated?!"
	@/bin/echo -e "Update it with\n\tsudo python3 -m pip install --upgrade pip"
	@false

ssl_rss_server.key:
	openssl req -x509 -newkey rsa:2048 -nodes -sha256 -days 365 \
		-out ssl_rss_server.crt \
		-keyout ssl_rss_server.key \
		-subj '/CN=localhost' -extensions EXT \
		-config <( \
		printf "[dn]\nCN=localhost\n[req]\ndistinguished_name = dn\n[EXT]\nsubjectAltName=DNS:localhost\nkeyUsage=digitalSignature\nextendedKeyUsage=serverAuth") \
		|| true

rss_server-page/less/%.css: rss_server-page/less/%.less \
	rss_server-page/less/base.less \
	rss_server-page/less/plugin_css_invert.js
	lessc "$<" "$@"

run_feed_provider:
	cd non-public && python3 -m http.server 8889

md:
	python3 -m markdown -f /dev/shm/README.html README.md
	test -d /dev/shm/screenshots || cp -r screenshots /dev/shm/.
	python3 -m markdown -f /dev/shm/screenshots/README.html screenshots/README.md
