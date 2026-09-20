.PHONY: check format lint type test

check: format lint type test

format:
	python -m black --check --line-length 100 corpus infra pages verify

lint:
	python -m ruff check core corpus infra pages verify tests

type:
	python -m mypy --ignore-missing-imports core corpus

test:
	python -m pytest -q
