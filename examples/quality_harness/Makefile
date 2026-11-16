.PHONY: install test lint check run clean

install:
	pip install -r requirements.txt
	pip install -e ".[dev]"

test:
	pytest tests/ -v

lint:
	ruff check src/ tests/

check: lint test

run:
	python -m bodhan_eval --dataset data/demo.jsonl --langs hi,ta,bn --out ./report --calibration data/calibration_labels.jsonl

clean:
	rm -rf .bodhan_cache report outputs/*.wav .pytest_cache
