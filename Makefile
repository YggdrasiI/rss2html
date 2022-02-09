FOLDER=$(realpath .)
USER?=$(shell ${SUDO_USER-:$USER})
PYTHON_BIN?=$(shell which python3 || which python)
SYSTEMD_INSTALL_DIR?=/etc/systemd/system
SINCE?=1 day

# To use subcommand output as file [ cat <(echo "Test") ]
SHELL=/bin/bash

DEBUG?=1

# Name of package
PACKAGE=rss2html

# Position of package in this repo
SRC_PACKAGES=src

# Root dir for static data
DATA_DIR=$(SRC_PACKAGES)/$(PACKAGE)/


# Fallback position for packages which are not installed.
SITE_PACKAGES=site-packages
PIP_PACKAGES=$(shell cat "requirements.txt" | sed "s/.*/\"\0\"/")

# Template releated
# JINIJA_2_10=https://files.pythonhosted.org/packages/56/e6/332789f295cf22308386cf5bbd1f4e00ed11484299c5d7383378cf48ba47/Jinja2-2.10.tar.gz

# Translation releated
SUPPORTED_LANGS=en_US de_DE  # Space between entries

PYBABEL=$(shell echo -n "PYTHONPATH='$(SITE_PACKAGES)' ./site-packages/bin/pybabel")
# Use installed pybabel if available
# PYBABEL=$(shell which pybabel || echo -n "PYTHONPATH='$(SITE_PACKAGES)' ./site-packages/bin/pybabel")

LESSC=$(shell which lessc)
#LESSC=$(echo -n "PYTHONPATH='$(SITE_PACKAGES)' ./site-packages/bin/lesscpy")

help:
	@echo -e "Common targets:\n" \
		"make run                 -- Start daemon. Quit with Ctl+C.\n" \
		"make install_deps_local  -- Install dependencies locally for this user\n" \
		"make install_deps_global -- Install dependencies global on system\n" \
		"USER=${USER} make install_service     -- Install systemd service for automatic start\n" \
		"                            Service will started as user '${USER}'\n" \
		"make uninstall_service   -- Uninstall systemd service\n" \
		"\n" \
		"    For developpers: \n" \
		"make css                 -- Build CSS from LESS files.\n" \
		"make babel_update        -- Localization: Apply source code changes in po-Files\n" \
		"make ssl                 -- Generate self signed certificates to test HTTPS.\n" \
		"                            This certicate is self-signed, thus the browers\n" \
		"                            will warns the users. If needed, replace\n" \
		"                            ssl_rss_server.[key|crt] by better ones.\n" \
		"USER=${USER} make runas  -- Start server as selected user\n" \
		"" \

run: check_env
	PYTHONPATH='$(SRC_PACKAGES):$(SITE_PACKAGES)' $(PYTHON_BIN) -m rss2html

runas: check_env
	sudo -u $(USER) PYTHONPATH='$(SRC_PACKAGES):$(SITE_PACKAGES)' $(PYTHON_BIN) -m rss2html

%.service: %.service.template
	echo "Create service file for user '$(USER)'."
	test "$(USER)" != "root" \
		|| (echo "Selected user for template is root. Aborting creation." && false)
	@echo "Create systemd service file for startup."
	sed -e "s#{USER}#$(USER)#g" \
		-e "s#{FOLDER}#$(FOLDER)#g" \
		-e "s#{PYTHON_BIN}#$(PYTHON_BIN)#g" \
		-e "s#{SITE_PACKAGES}#$(SRC_PACKAGES):$(SITE_PACKAGES)#g" \
		$< > $(basename $<)

create_service_file: rss_server.service

check_env:
	@PYTHONPATH='$(SRC_PACKAGES):$(SITE_PACKAGES)' $(PYTHON_BIN) \
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

css: $(DATA_DIR)rss_server-page/less/default.css \
	$(DATA_DIR)rss_server-page/less/light.css \
	$(DATA_DIR)rss_server-page/less/dark.css
	mv $(DATA_DIR)rss_server-page/less/*.css $(DATA_DIR)rss_server-page/css/.

log:
	journalctl -u rss_server --since "$(SINCE) ago"

# ====================================================
clean:
	@echo "This will clean the following files:"
	@git clean -n -d .
	@echo "Continue?" && read RSS_READER_CLEAN \
		&& test -n "$${RSS_READER_CLEAN}" -a "$${RSS_READER_CLEAN}" != "no" \
		&& git clean -f -d .

install_deps_local:
	$(PYTHON_BIN) -m pip install -U --target $(SITE_PACKAGES) $(PIP_PACKAGES)

install_deps_global:
	sudo $(PYTHON_BIN) -m pip install -U $(PIP_PACKAGES)

# ====================================================
# Required for developers, only

babel_prepare:
	$(PYBABEL) -v extract -F $(DATA_DIR)locale/babel.config -o ./$(DATA_DIR)locale/messages.pot --input-dirs=$(DATA_DIR)

# Overwrites existing messages.po!
babel_init:
	@for SLANG in $(SUPPORTED_LANGS) ; do \
		make $(DATA_DIR)locale/$${SLANG}/LC_MESSAGES/messages.po ;\
		done

babel_update: babel_prepare
	@for SLANG in $(SUPPORTED_LANGS) ; do \
		$(PYBABEL) update -l $${SLANG} -d ./$(DATA_DIR)locale -i ./$(DATA_DIR)locale/messages.pot ;\
		done
	@echo "Now, 'git diff $(DATA_DIR)locale' show the differences."
	@echo "Update $(DATA_DIR)locale/*/LC_MESSAGES/*.po and finally run 'make babel_compile'"

babel_compile:
	@for SLANG in $(SUPPORTED_LANGS) ; do \
		make $(DATA_DIR)locale/$${SLANG}/LC_MESSAGES/messages.mo ;\
		done

locale/messages.pot:
	make babel_prepare
	@echo "BABEL: create *.pot file"

%.po: $(DATA_DIR)locale/messages.pot
	$(PYBABEL) init -l $(word 2, $(subst /, ,$@)) -d ./$(DATA_DIR)locale -i ./$(DATA_DIR)locale/messages.pot ;\

%.mo: %.po
	$(PYBABEL) compile -l $(word 4, $(subst /, ,$@)) -d ./$(DATA_DIR)locale -i "$(@:.mo=.po)" 
	
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

$(DATA_DIR)rss_server-page/less/%.css: \
	$(DATA_DIR)rss_server-page/less/%.less \
	$(DATA_DIR)rss_server-page/less/base.less \
	$(DATA_DIR)rss_server-page/less/plugin_css_invert.js
	$(LESSC) "$<" "$@"

md:
	PYTHONPATH=site-packages python3 -m grip README.md
