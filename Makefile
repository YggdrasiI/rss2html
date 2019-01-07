FOLDER=$(realpath .)
USER=$(shell whoami)
PYTHON_BIN=$(shell which python3 || which python)
SYSTEMD_INSTALL_DIR=/etc/systemd/system

help:
	@echo "Available targets:\n" \
		"make run               -- Start daemon. Quit with Ctl+C.\n" \
		"make install_service   -- Install systemd service for automatic start\n" \
		"                          Service will started as user '${USER}'\n" \
		"make uninstall_service -- Uninstall systemd service\n" \
		"" \

run:
	python3 rss_server.py

%.service: %.service.template
	@echo "Create systemd service file for startup."
	sed -e "s#{USER}#$(USER)#g" \
		-e "s#{FOLDER}#$(FOLDER)#g" \
		-e "s#{PYTHON_BIN}#$(PYTHON_BIN)#g" \
		$< > $(basename $<)

create_service_file: rss_server.service

install_service_buggy: rss_server.service
	sudo systemctl link "$(FOLDER)/$<"
	sudo systemctl daemon-reload
	sudo systemctl enable "$(FOLDER)/$<"

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

