.PHONY: venv test smoke migrate seed run lint
PY ?= $(HOME)/.han-venvs/han/bin/python

venv:
	python3 -m venv $(HOME)/.han-venvs/han && $(HOME)/.han-venvs/han/bin/pip install -r requirements-dev.txt

test:
	$(PY) -m pytest

migrate:
	$(PY) -m alembic upgrade head

seed:
	$(PY) -m app.seed

run:
	$(PY) -m uvicorn app.main:app --reload --port 8000

smoke:
	$(PY) ../scripts/smoke_e2e.py
