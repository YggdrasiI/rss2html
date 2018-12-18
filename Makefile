FOLDER=$(realpath .)
USER=$(shell whoami)
PYTHON_BIN=$(shell which python3 || which python)

help:
	echo "Available targets: " \
		"make run               -- Start background daemon" \
		"make install_service   -- Install systemd service for automatic start." \
		"make uninstall_service -- Uninstall systemd service" \
		"" \
	

run:
	python3 rss_server.py

rss_server.service: create_service_file

create_service_file: rss_server.service.template
	@echo "Create systemd service file for startup."
	sed -e "s#{USER}#$(USER)#g" \
		-e "s#{FOLDER}#$(FOLDER)#g" \
		-e "s#{PYTHON_BIN}#$(PYTHON_BIN)#g" \
		$< > $(basename $<)

install_service: rss_server.service
	sudo systemctl link "$(FOLDER)/$<"
	sudo systemctl daemon-reload
	sudo systemctl enable "$(FOLDER)/$<"

uninstall_service: rss_server.service
	sudo systemctl disable "$<"
