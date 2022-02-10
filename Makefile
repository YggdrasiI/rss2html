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
# PIP_PACKAGES=$(shell cat "requirements.txt" | sed "s/.*/\"\0\"/")

# Template releated
# JINIJA_2_10=https://files.pythonhosted.org/packages/56/e6/332789f295cf22308386cf5bbd1f4e00ed11484299c5d7383378cf48ba47/Jinja2-2.10.tar.gz

# Translation releated
SUPPORTED_LANGS=en_US de_DE  # Space between entries

# Normal variant
#PYBABEL=$(shell echo -n "PYTHONPATH='$(SITE_PACKAGES)' ./site-packages/bin/pybabel")
# Venv-variant
PYBABEL=$(shell echo -n "./venv/bin/pybabel")

LESSC=$(shell which lessc)
#LESSC=$(echo -n "PYTHONPATH='$(SITE_PACKAGES)' ./site-packages/bin/lesscpy")

help:
	@echo -e "Common targets:\n" \
		"make create_environment  -- Install dependencies in ./venv\n" \
		"[USER=…] make run        -- Start daemon from ./venv.\n" \
		"                            Quit with Ctl+C.\n" \
		"\n" \
		"[USER=…] make install_service     -- Install systemd service for automatic start\n" \
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
		"[USER=…] make run_local  -- Start daemon without virutal environment.\n" \
		"                            Quit with Ctl+C.\n" \
		"                            Optional USER selects other user.\n" \
		"make install_deps_local  -- Install dependencies locally for this user\n" \
		"make install_deps_global -- Install dependencies global on system\n" \
		"" \

# Activates venv, but run rss2html from its source folder
run: check_environment
	sudo -u $(USER) PYTHONPATH='$(SRC_PACKAGES)' \
		./venv/bin/python3 -m rss2html

# Using python binary with capability to bind on port 443.
run_443: ./venv/bin/python3_443 ssl
	sudo -u $(USER) PYTHONPATH='$(SRC_PACKAGES)' \
		./venv/bin/python3_443 -m rss2html -p 443 --ssl=1

# Without venv
run_local: check_packages
	sudo -u $(USER) PYTHONPATH='$(SRC_PACKAGES):$(SITE_PACKAGES)' \
		$(PYTHON_BIN) -m rss2html

create_service_file: rss2html.service

check_environment:
	@test -d venv || make create_environment
	@source venv/bin/activate && \
		python3 -c "import jinja2; $(shell grep -v '\(Jinja2\|#.*\|^$$\)' requirements.txt | sed -e 's/[>=].*//' -e 's/.*/import \0;/')" \
		2>/dev/null \
		&& echo "All Python package found in virtual environment"

check_packages:
	@PYTHONPATH='$(SITE_PACKAGES)' $(PYTHON_BIN) \
		-c "import jinja2; $(shell grep -v '\(Jinja2\|#.*\|^$$\)' requirements.txt | sed -e 's/[>=].*//' -e 's/.*/import \0;/')" \
		2>/dev/null \
		|| make install_deps_local \
		|| make print_pip_upgrade
	@echo "All Python package dependencies fulfilled."

install_service: rss2html.service check_environment
	@test -d "./venv/lib/python3.8/site-packages/rss2html" \
		|| ( echo "Copy rss2html into venv" && \
		cp -r src/rss2html ./venv/lib/python3.8/site-packages/rss2html )
	sudo cp "$(FOLDER)/$<" "$(SYSTEMD_INSTALL_DIR)/$<"
	sudo systemctl daemon-reload
	sudo systemctl enable "$<"
	@echo "Service enabled, but not started. " \
		"Call 'systemctl start $<' to start service."

uninstall_service: rss2html.service
	sudo systemctl stop "$<"
	sudo systemctl disable "$<"
	sudo rm "$(SYSTEMD_INSTALL_DIR)/$<"

start_service: rss2html.service
	sudo systemctl start "$<"

# No %.service-syntax here because of .PHONY
rss2html.service: rss2html.service.template
	@echo "Create service file for user '$(USER)'."
	@test "$(USER)" != "root" \
		|| (echo "Selected user for template is root. Aborting creation." && false)
	@sed -e "s#{USER}#$(USER)#g" \
		-e "s#{FOLDER}#$(FOLDER)/venv#g" \
		-e "s#{PYTHON_BIN}#$(PYTHON_BIN)#g" \
		-e "s#{SITE_PACKAGES}#$(SITE_PACKAGES)#g" \
		$< > $(basename $<)


# creates whl-file in ./dist
build: check_environment babel_compile
	$(PYTHON_BIN) -m build

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
create_environment: requirements.txt
	test -d venv || $(PYTHON_BIN) -m venv venv
	source venv/bin/activate && \
		python3 -m pip install -U -r requirements.txt

# No separate environment, but bundle all packages in local folder
install_deps_local: requirements.txt
	$(PYTHON_BIN) -m pip install -U --target $(SITE_PACKAGES) -r requirements.txt

install_deps_global: requirements.txt
	sudo $(PYTHON_BIN) -m pip install -U -r requirements.txt

# ====================================================
# Required for developers, only

# Create redundant requiremnts.txt from setup.cfg
requirements.txt:
	sed -n "/^install_requires =$$/{g; :x; $$!N; s/  //; tx; p}" \
		setup.cfg > "$@"

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

./venv/bin/python3_443: python3_443
	ln -s $(realpath python3_443) venv/bin/.

python3_443:
	/bin/cp "/usr/bin/python3" "./python3_443"
	/usr/bin/sudo /sbin/setcap CAP_NET_BIND_SERVICE=+eip "./python3_443"


$(DATA_DIR)rss_server-page/less/%.css: \
	$(DATA_DIR)rss_server-page/less/%.less \
	$(DATA_DIR)rss_server-page/less/base.less \
	$(DATA_DIR)rss_server-page/less/plugin_css_invert.js
	$(LESSC) "$<" "$@"

md:
	PYTHONPATH=site-packages python3 -m grip README.md

.PHONY: clean rss2html.service
