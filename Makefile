.PHONY: install lint test

install:
	uv sync --all-packages

lint:
	uv run ruff check lambdas/ packages/

test:
	uv run pytest lambdas/pedidos/tests/ lambdas/facturas/tests/ -q
