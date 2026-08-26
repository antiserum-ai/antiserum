.PHONY: install test lint ci reproduce scan judge demo reference

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

# One-command proof: scan the reference mix and fail if a plant is missed.
reproduce:
	antiserum reproduce corpus/reference

reference:
	python3 scripts/build_reference.py

scan:
	antiserum scan corpus/toy

judge:
	antiserum judge corpus/toy --out judgments.json

# Two-minute demo on the tiny mix. Not the reference score.
demo: scan judge
