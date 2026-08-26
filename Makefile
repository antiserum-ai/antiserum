.PHONY: install test reproduce scan

install:
	python3 -m pip install -e ".[dev]"

test:
	python3 -m pytest

scan:
	antiserum scan corpus/toy

reproduce: test scan
