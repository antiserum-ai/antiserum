.PHONY: install test reproduce scan judge

install:
	python3 -m pip install -e ".[dev]"

test:
	python3 -m pytest

scan:
	antiserum scan corpus/toy

judge:
	antiserum judge corpus/toy --out judgments.json

reproduce: test scan judge
