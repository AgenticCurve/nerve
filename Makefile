.PHONY: typecheck lint format test check clean help

help: ## Show this help message
	@echo "Available commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

typecheck: ## Run mypy type checking
	uv run mypy src/

lint: ## Run ruff linter (check only, no formatting)
	uv run ruff check . --fix

format: ## Run ruff formatter
	uv run ruff format .

test: ## Run pytest tests
	uv run pytest

check: lint format typecheck test ## Run all checks (lint + format + typecheck + test)

clean: ## Clean up cache files
	rm -rf .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
