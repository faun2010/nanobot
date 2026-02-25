SHELL := /usr/bin/env bash
.DEFAULT_GOAL := install-venv

VENV ?= .venv
PYTHON ?= python3
VENV_PY := $(VENV)/bin/python
VENV_PIP := $(VENV_PY) -m pip

.PHONY: help venv install install-venv install-venv-dev

help:
	@echo "Available targets:"
	@echo "  make install         # install current nanobot code + dependencies into .venv"
	@echo "  make install-venv    # same as install"
	@echo "  make install-venv-dev# install with dev extras (.[dev])"

venv:
	@test -x "$(VENV_PY)" || $(PYTHON) -m venv "$(VENV)"

install: install-venv

install-venv: venv
	@if command -v uv >/dev/null 2>&1; then \
		uv pip install --python "$(VENV_PY)" --editable .; \
	else \
		$(VENV_PIP) install --editable .; \
	fi

install-venv-dev: venv
	@if command -v uv >/dev/null 2>&1; then \
		uv pip install --python "$(VENV_PY)" --editable ".[dev]"; \
	else \
		$(VENV_PIP) install --editable ".[dev]"; \
	fi
