.PHONY: install test lint ci reproduce scan judge

# Suite measures ~85% today. Floor is a bit under that so a small refactor
# does not flake; override with COV_FAIL_UNDER=… if you need to.
COV_FAIL_UNDER ?= 80

install:
	python3 -m pip install -e ".[dev]"

lint:
	python3 -m ruff check src tests

test:
	python3 -m pytest --cov=antiserum --cov-report=term-missing --cov-fail-under=$(COV_FAIL_UNDER)

ci: lint test

scan:
	antiserum scan corpus/toy

judge:
	antiserum judge corpus/toy --out judgments.json

reproduce: test scan judge
