.PHONY: typecheck lint format test check clean help features features-glm features-openrouter

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

# Feature tests (3rd party integration tests - require API keys in .env.local)

features: features-glm features-openrouter ## Run all feature tests

features-glm: ## Run GLM feature tests (requires GLM_API_KEY)
	uv run python features/glm/glm_node.py
	uv run python features/glm/glm_chat_node.py

features-openrouter: ## Run OpenRouter feature tests (requires OPENROUTER_API_KEY)
	uv run python features/openrouter/openrouter_node.py
	uv run python features/openrouter/openrouter_chat_node.py
