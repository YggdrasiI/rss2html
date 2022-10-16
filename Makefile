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

POETRY=$(PYTHON_BIN) -m poetry
POETRY_VENV=.venv

# Translation releated
SUPPORTED_LANGS=en_US de_DE  # Space between entries

# Venv-variant
PYBABEL=$(shell echo -n "./$(POETRY_VENV)/bin/pybabel")

LESSC=$(shell which lessc)

help:
	@echo -e "Common targets:\n" \
		"make install             -- Install dependencies in $(POETRY_VENV)\n" \
		"[USER=…] make run        -- Start daemon (with virtual environment $(POETRY_VENV))\n" \
		"                            Quit with Ctl+C.\n" \
		"[USER=…] make run_443    -- Like 'run', but HTTPS on port 443\n" \
		"                            (Port in settings.py will be ignored.)\n" \
		"                            Quit with Ctl+C.\n" \
		"\n" \
		"[USER=…] make install_service     -- Install systemd service for automatic start\n" \
		"                            Service will started as user '${USER}'\n" \
		"[USER=…] make install_service_443 -- Like 'install_service', but forces \n" \
		"                            HTTPS on port 443\n" \
		"                            (Port in settings.py will be ignored.)\n" \
		"make uninstall_service   -- Uninstall systemd service\n" \
		"\n" \
		"    For developpers: \n" \
		"make css                 -- Build CSS from LESS files.\n" \
		"make babel_update        -- Localization: Apply source code changes in po-Files\n" \
		"make ssl                 -- Generate self signed certificates to test HTTPS.\n" \
		"                            This certicate is self-signed, thus the browers\n" \
		"                            will warns the users. If needed, replace\n" \
		"                            ssl_rss_server.[key|crt] by better ones.\n" \
		"" \

# Activates venv, but run rss2html from its source folder
run: $(POETRY_VENV)
	sudo -u $(USER) $(POETRY) run \
		python3 -m rss2html

# Using python binary with capability to bind on port 443.
run_443: $(POETRY_VENV) $(POETRY_VENV)/bin/python3_443 ssl
	sudo -u $(USER) $(POETRY) run \
		$(POETRY_VENV)/bin/python3_443 -m rss2html -p 443 --ssl=1

create_service_file: rss2html.service

install_service: rss2html.service 
	sudo cp "$(FOLDER)/$<" "$(SYSTEMD_INSTALL_DIR)/$<"
	sudo systemctl daemon-reload
	sudo systemctl enable "$<"
	@echo "Service enabled, but not started. " \
		"Call 'systemctl start $<' to start service."

# Note: Target is renaming service file to 'rss2html.service'.
install_service_443: rss2html_443.service $(POETRY_VENV)/bin/python3_443 ssl
	sudo cp "$(FOLDER)/$<" "$(SYSTEMD_INSTALL_DIR)/$(subst _443,,$<)"
	sudo systemctl daemon-reload
	sudo systemctl enable "$(subst _443,,$<)"
	@echo "Service enabled, but not started. " \
		"Call 'systemctl start $(subst _443,,$<)' to start service."

uninstall_service: rss2html.service
	sudo systemctl stop "$<"
	sudo systemctl disable "$<"
	sudo rm "$(SYSTEMD_INSTALL_DIR)/$<"

start_service: rss2html.service
	sudo systemctl start "$<"

# Service starts python from $(POETRY_VENV) folder. Thus, site-package folder
# from virtual environment will be used.
# No %.service-syntax here because of .PHONY
rss2html.service: rss2html.service.template
	@echo "Create service file for user '$(USER)'."
	@test "$(USER)" != "root" \
		|| (echo "Selected user for template is root. Aborting creation." && false)
	@sed -e "s#{USER}#$(USER)#g" \
		-e "s#{FOLDER}#$(FOLDER)#g" \
		-e "s#{PYTHON_BIN}#python3#g" \
		-e "s#{RSS2HTML_ARGS}##g" \
		$< > $@

# TODO
rss2html_443.service: rss2html.service.template
	@echo "Create service file for user '$(USER)'."
	@test "$(USER)" != "root" \
		|| (echo "Selected user for template is root. Aborting creation." && false)
	@sed -e "s#{USER}#$(USER)#g" \
		-e "s#{FOLDER}#$(FOLDER)#g" \
		-e "s#{PYTHON_BIN}#python3_443#g" \
		-e "s#{RSS2HTML_ARGS}#-p 443 --ssl=1 #g" \
		$< > $@



# creates whl-file in ./dist
#build: babel_compile
#	$(PYTHON_BIN) -m build
build: babel_compile
	poetry build


ssl: ssl_rss_server.key ssl_rss_server.crt

css: $(DATA_DIR)rss_server-page/less/default.css \
	$(DATA_DIR)rss_server-page/less/light.css \
	$(DATA_DIR)rss_server-page/less/dark.css
	mv $(DATA_DIR)rss_server-page/less/*.css $(DATA_DIR)rss_server-page/css/.

log:
	journalctl -u rss2html --since "$(SINCE) ago"

# ====================================================
clean:
	@echo "This will clean the following files:"
	@git clean -n -d .
	@echo "Continue?" && read RSS_READER_CLEAN \
		&& test -n "$${RSS_READER_CLEAN}" -a "$${RSS_READER_CLEAN}" != "no" \
		&& git clean -f -d .

# Install everything in virtual environment
install: pyproject.toml poetry.toml
	$(POETRY) install

$(POETRY_VENV):
	make install

# ====================================================
# Required for developers, only

## Create redundant requiremnts.txt from setup.cfg
#requirements.txt:
#	sed -n "/^install_requires =$$/{g; :x; $$!N; s/  //; tx; p}" \
#		setup.cfg > "$@"

requirements.txt:
	sed -n "/^\[tool.poetry.dev-dependencies\]$$/{g; :x; $$!N; s/ = \"^/>=\"/; tx; p}" \
		pyproject.toml > "$@"

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
	
ssl_rss_server.key:
	openssl req -x509 -newkey rsa:2048 -nodes -sha256 -days 365 \
		-out ssl_rss_server.crt \
		-keyout ssl_rss_server.key \
		-subj '/CN=localhost' -extensions EXT \
		-config <( \
		printf "[dn]\nCN=localhost\n[req]\ndistinguished_name = dn\n[EXT]\nsubjectAltName=DNS:localhost\nkeyUsage=digitalSignature\nextendedKeyUsage=serverAuth") \
		|| true

$(POETRY_VENV)/bin/python3_443: python3_443
	ln -s $(realpath python3_443) $(POETRY_VENV)/bin/.

python3_443:
	/bin/cp "/usr/bin/python3" "./python3_443"
	/usr/bin/sudo /sbin/setcap CAP_NET_BIND_SERVICE=+eip "./python3_443"


$(DATA_DIR)rss_server-page/less/%.css: \
	$(DATA_DIR)rss_server-page/less/%.less \
	$(DATA_DIR)rss_server-page/less/base.less \
	$(DATA_DIR)rss_server-page/less/plugin_css_invert.js
	$(LESSC) "$<" "$@"

md:
	python3 -m grip -b README.md

.PHONY: clean rss2html.service rss2html_443.service requiremnts.txt
