.PHONY: install
install:
		pipx install --force .

.PHONY: run
run:
		dockmon --verbose
