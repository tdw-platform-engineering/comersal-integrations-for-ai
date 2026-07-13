# comersal-integrations

## Purpose

This repo provides **API integrations for Comersal's internal services**, exposing them as standalone, invocable endpoints. The primary consumers are AI agents (Anima) and internal tools that need programmatic access to Comersal's on-premise systems (NAV/SQL Server).

The goal is to decouple service access from the legacy monolithic Flask API (`comersal-api-services-connect`) and provide clean, single-responsibility functions that can be composed by any consumer — chatbots, back-office apps, scheduled jobs, or other services.

**All integrations are designed to run as AWS Lambda functions** deployed inside a VPC with NAT gateway access to the on-premise database. This gives us:
- Pay-per-use (no idle EC2/ECS cost)
- Independent scaling per service
- Isolated deployments (update pedidos without touching facturas)
- Direct SQL Server access without intermediate HTTP hops

## Lambdas

| Lambda | Purpose | Invocation |
|--------|---------|-----------|
| **pedidos** | Create orders (validate stock/prices + generate NUMTRA + INSERT) | Synchronous — returns result immediately |
| **facturas** | Query open invoices by client or invoice number | Synchronous — read-only |

## Architecture

```
Consumer (Anima agent / back-office / script)
  → Lambda invoke (RequestResponse)
  → Lambda (VPC-attached, private subnet)
  → NAT Gateway (000-TwdManaged)
  → SQL Server (on-premise NAV)
```

Each Lambda owns its domain logic end-to-end: input validation, business rules, DB access, and response formatting. No shared web framework, no shared state — just a function that does one thing.

## Quick Start

```bash
uv sync --all-packages
uv run pytest lambdas/pedidos/tests/ lambdas/facturas/tests/ -q
uv run ruff check lambdas/ packages/
```

## Repo Structure

```
comersal-integrations/
├── packages/shared/          # DB connection, domain models (reused across lambdas)
├── lambdas/pedidos/          # Order creation
├── lambdas/facturas/         # Invoice queries
├── buildspec.yml             # CI/CD (CodeBuild → ECR → Lambda)
├── nx.json                   # Nx workspace
└── pyproject.toml            # uv workspace root
```

## Infra

Both Lambdas live in the **000-TwdManaged VPC** (private subnets + NAT gateway) to reach the on-premise SQL Server. Terraform for Lambda resources is managed in the `terraform-v2` repo.

## Adding a New Integration

1. Create `lambdas/<name>/` with `src/handler.py`, `tests/`, `Dockerfile`, `pyproject.toml`, `project.json`
2. Reuse `packages/shared/src/db.py` for DB connections
3. Add models to `packages/shared/src/models.py` if shared, or keep them local
4. Add the Docker build to `buildspec.yml`
5. Create the Lambda + ECR in Terraform
