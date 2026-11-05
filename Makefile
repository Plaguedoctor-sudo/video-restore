VENV ?= .venv
PYTHON ?= $(VENV)/bin/python
PYTEST ?= $(VENV)/bin/pytest
RESTORE ?= $(VENV)/bin/restore
UVICORN ?= $(VENV)/bin/uvicorn

.PHONY: test run web lint
test:
	$(PYTEST) -q
run:
	$(RESTORE) run $(SRC) -o $(OUT) --preset standard
web:
	$(UVICORN) restore.web:app --host 0.0.0.0 --port 8800
lint:
	$(PYTHON) -m compileall -q restore tests

