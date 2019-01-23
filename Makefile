FOLDER=$(realpath .)
USER=$(shell whoami)
PYTHON_BIN=$(shell which python3 || which python)
SYSTEMD_INSTALL_DIR=/etc/systemd/system

DEBUG?=1

# Fallback position for packages which are not installed.
SITE_PACKAGES=site-packages
PIP_PACKAGES='Jinja2>=2.10' \
			 'httplib2' \
			 'babel>=2.6' \
#			 'webassets-babel>=0.3' \

# Template releated
# JINIJA_2_10=https://files.pythonhosted.org/packages/56/e6/332789f295cf22308386cf5bbd1f4e00ed11484299c5d7383378cf48ba47/Jinja2-2.10.tar.gz

# Translation releated
SUPPORTED_LANGS=en_US de_DE  # Space between entries

# Use installed pybabel if available
PYBABEL=$(shell which pybabel || echo -n "PYTHONPATH='$(SITE_PACKAGES)' ./site-packages/pybabel")

help:
	@echo "Common targets:\n" \
		"make run               -- Start daemon. Quit with Ctl+C.\n" \
		"make install_service   -- Install systemd service for automatic start\n" \
		"                          Service will started as user '${USER}'\n" \
		"make uninstall_service -- Uninstall systemd service\n" \
		"" \

run: check_env
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
	PYTHONPATH='$(SITE_PACKAGES)' $(PYTHON_BIN) -c "import jinja2; import babel" \
			   || make install_deps_local
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

# ====================================================
clean:
	@echo "This will clean the following files:"
	@git clean -n -d .
	@echo "Continue?" && read RSS_READER_CLEAN \
		&& test -n "$${RSS_READER_CLEAN}" -a "$${RSS_READER_CLEAN}" != "no" \
		&& git clean -f -d .

install_deps_local:
	$(PYTHON_BIN) -m pip install -t $(SITE_PACKAGES) $(PIP_PACKAGES)

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

babel_update:
	@for SLANG in $(SUPPORTED_LANGS) ; do \
		$(PYBABEL) update -l $${SLANG} -d ./locale -i ./locale/messages.pot ;\
		done

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
	
