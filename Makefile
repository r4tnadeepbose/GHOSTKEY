PYTHON ?= python
VENV   ?= .venv

ifeq ($(OS),Windows_NT)
	VENV_PY := $(VENV)/Scripts/python.exe
else
	VENV_PY := $(VENV)/bin/python
endif

.PHONY: help venv install dev run lint format test compile package clean

help:
	@echo "ghostkey :: make targets"
	@echo "  venv     create $(VENV)"
	@echo "  install  install runtime dependencies"
	@echo "  dev      install dev dependencies (ruff, pre-commit, pyinstaller)"
	@echo "  run      launch the dashboard"
	@echo "  lint     ruff check"
	@echo "  format   ruff format"
	@echo "  test     run unit tests"
	@echo "  compile  byte-compile scan.py"
	@echo "  package  build dist/ghostkey source zip"
	@echo "  clean    remove caches and build artifacts"

venv:
	$(PYTHON) -m venv $(VENV)

install: venv
	$(VENV_PY) -m pip install --upgrade pip
	$(VENV_PY) -m pip install -r requirements.txt

dev: venv
	$(VENV_PY) -m pip install --upgrade pip
	$(VENV_PY) -m pip install -r requirements-dev.txt

run:
	$(PYTHON) scan.py

lint:
	$(PYTHON) -m ruff check .

format:
	$(PYTHON) -m ruff format .

test:
	$(PYTHON) -m unittest discover -s tests -v

compile:
	$(PYTHON) -m py_compile scan.py

package:
	$(PYTHON) scripts/package.py

clean:
	$(PYTHON) -c "import shutil,pathlib; [shutil.rmtree(p, ignore_errors=True) for p in pathlib.Path('.').glob('**/__pycache__')]; [shutil.rmtree(p, ignore_errors=True) for p in ('build','dist','.pytest_cache','.ruff_cache')]; [p.unlink() for p in pathlib.Path('.').glob('*.pyc')]"
