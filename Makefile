.PHONY: typecheck lint format test check clean help features features-glm features-openrouter

# Color definitions
CYAN := \033[36m
GREEN := \033[32m
RED := \033[31m
YELLOW := \033[33m
RESET := \033[0m
BOLD := \033[1m

help: ## Show this help message
	@echo "Available commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(CYAN)%-12s$(RESET) %s\n", $$1, $$2}'

typecheck: ## Run mypy type checking
	@echo "$(CYAN)━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━$(RESET)"
	@echo "$(BOLD)$(CYAN)▶ Running typecheck (mypy)$(RESET)"
	@echo "$(CYAN)━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━$(RESET)"
	@uv run mypy src/ && echo "$(GREEN)✓ typecheck passed$(RESET)" || (echo "$(RED)✗ typecheck failed$(RESET)" && exit 1)

lint: ## Run ruff linter (check only, no formatting)
	@echo "$(CYAN)━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━$(RESET)"
	@echo "$(BOLD)$(CYAN)▶ Running lint (ruff check)$(RESET)"
	@echo "$(CYAN)━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━$(RESET)"
	@uv run ruff check . --fix && echo "$(GREEN)✓ lint passed$(RESET)" || (echo "$(RED)✗ lint failed$(RESET)" && exit 1)

format: ## Run ruff formatter
	@echo "$(CYAN)━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━$(RESET)"
	@echo "$(BOLD)$(CYAN)▶ Running format (ruff format)$(RESET)"
	@echo "$(CYAN)━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━$(RESET)"
	@uv run ruff format . && echo "$(GREEN)✓ format passed$(RESET)" || (echo "$(RED)✗ format failed$(RESET)" && exit 1)

test: ## Run pytest tests
	@echo "$(CYAN)━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━$(RESET)"
	@echo "$(BOLD)$(CYAN)▶ Running tests (pytest)$(RESET)"
	@echo "$(CYAN)━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━$(RESET)"
	@uv run pytest && echo "$(GREEN)✓ test passed$(RESET)" || (echo "$(RED)✗ test failed$(RESET)" && exit 1)

check: ## Run all checks (lint + format + typecheck + test)
	@echo ""
	@echo "$(BOLD)$(YELLOW)╔════════════════════════════════════════════════════════════════════════════╗$(RESET)"
	@echo "$(BOLD)$(YELLOW)║                          Running all checks                                ║$(RESET)"
	@echo "$(BOLD)$(YELLOW)╔════════════════════════════════════════════════════════════════════════════╗$(RESET)"
	@echo ""
	@$(MAKE) lint
	@echo ""
	@$(MAKE) format
	@echo ""
	@$(MAKE) typecheck
	@echo ""
	@$(MAKE) test
	@echo ""
	@echo "$(BOLD)$(GREEN)╔════════════════════════════════════════════════════════════════════════════╗$(RESET)"
	@echo "$(BOLD)$(GREEN)║                       ✓ All checks passed!                                 ║$(RESET)"
	@echo "$(BOLD)$(GREEN)╚════════════════════════════════════════════════════════════════════════════╝$(RESET)"
	@echo ""

clean: ## Clean up cache files
	rm -rf .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

# Feature tests (3rd party integration tests - require API keys in .env.local)

features: ## Run all feature tests
	@echo ""
	@echo "$(BOLD)$(YELLOW)╔════════════════════════════════════════════════════════════════════════════╗$(RESET)"
	@echo "$(BOLD)$(YELLOW)║                        Running feature tests                               ║$(RESET)"
	@echo "$(BOLD)$(YELLOW)╚════════════════════════════════════════════════════════════════════════════╝$(RESET)"
	@echo ""
	@$(MAKE) features-glm
	@echo ""
	@$(MAKE) features-openrouter
	@echo ""
	@echo "$(BOLD)$(GREEN)╔════════════════════════════════════════════════════════════════════════════╗$(RESET)"
	@echo "$(BOLD)$(GREEN)║                    ✓ All feature tests passed!                             ║$(RESET)"
	@echo "$(BOLD)$(GREEN)╚════════════════════════════════════════════════════════════════════════════╝$(RESET)"
	@echo ""

features-glm: ## Run GLM feature tests (requires GLM_API_KEY)
	@echo "$(CYAN)━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━$(RESET)"
	@echo "$(BOLD)$(CYAN)▶ Running GLM feature tests$(RESET)"
	@echo "$(CYAN)━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━$(RESET)"
	@uv run python features/glm/glm_node.py && echo "" && uv run python features/glm/glm_chat_node.py && echo "$(GREEN)✓ GLM tests passed$(RESET)" || (echo "$(RED)✗ GLM tests failed$(RESET)" && exit 1)

features-openrouter: ## Run OpenRouter feature tests (requires OPENROUTER_API_KEY)
	@echo "$(CYAN)━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━$(RESET)"
	@echo "$(BOLD)$(CYAN)▶ Running OpenRouter feature tests$(RESET)"
	@echo "$(CYAN)━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━$(RESET)"
	@uv run python features/openrouter/openrouter_node.py && echo "" && uv run python features/openrouter/openrouter_chat_node.py && echo "$(GREEN)✓ OpenRouter tests passed$(RESET)" || (echo "$(RED)✗ OpenRouter tests failed$(RESET)" && exit 1)
