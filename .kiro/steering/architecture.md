---
inclusion: always
description: Architecture and conventions for the comersal-integrations monorepo.
---

# Comersal Integrations — Architecture

## Overview

Lambda functions that talk directly to Comersal's NAV SQL Server (via VPC NAT gateway).
Deployed inside the 000-TwdManaged VPC to reach the on-prem database.

## Monorepo Structure

```
comersal-integrations/
├── packages/shared/          # DB connection pool, domain models
│   └── src/
│       ├── db.py             # pymssql connection (env var config)
│       └── models.py         # PedidoEncabezado, PedidoDetalle, FacturaAbierta
├── lambdas/pedidos/          # Order creation Lambda
│   ├── src/handler.py        # Entry point
│   ├── src/numtra.py         # NUMTRA generation (direct SQL)
│   ├── src/service.py        # Validate + insert
│   ├── tests/
│   └── Dockerfile
├── lambdas/facturas/         # Open invoices Lambda
│   ├── src/handler.py        # Entry point
│   ├── tests/
│   └── Dockerfile
├── buildspec.yml             # CodeBuild (build + push + deploy)
├── nx.json                   # Nx workspace config
└── pyproject.toml            # uv workspace root
```

## Key Decisions

1. **Direct SQL Server** — no Athena, no Flask API intermediary. NUMTRA generated via `SELECT MAX`.
2. **VPC-attached** — both Lambdas in 000-TwdManaged VPC subnets with NAT gateway.
3. **Synchronous invocation** — Anima's `confirmar_pedido` tool invokes pedidos Lambda directly (`RequestResponse`). User gets immediate confirmation.
4. **Validations preserved** — stock check, client existence, factor empaque, duplicate detection all run against the DB before INSERT.
5. **No Redis** — cold Lambda runs are infrequent enough that connection pooling isn't needed. Single connection per invocation.

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| SQLSERVER_CONNECTION_STRING | Yes | `mssql+pymssql://user:pass@host:port/database` |
| AWS_REGION | No | Default: us-east-1 |
| LOG_LEVEL | No | Default: INFO |

## Invocation Contracts

### Pedidos (crear)

```json
// Input
{"encabezado": {"cod_cte": "100", "cod_ven": "V01", "val_gra": 10.0, "val_iva": 1.3, "val_tot": 11.3}, "lineas": [...]}

// Output (success)
{"ok": true, "numtra": "PAWS-0000000042", "mensaje": "...", "data": {...}}

// Output (validation error)
{"ok": false, "errores": ["..."]}
```

### Facturas

```json
// Input
{"action": "por_cliente", "cod_cte": "100", "pagina": 1, "por_pagina": 50}
{"action": "obtener", "factura": "0125-000000000097782"}

// Output
{"ok": true, "data": [...], "total": 5, "pagina": 1}
```

## Deployment

- **Infra**: Terraform in `terraform-v2/clients/comersal/000-TwdManaged/` (VPC, subnets, NAT, SG)
- **Lambda resources**: Separate Terraform file or add to existing 000 stack
- **CI/CD**: CodePipeline → CodeBuild (`buildspec.yml`) → ECR → Lambda update
- **Architecture**: arm64 (graviton)
