# Multi-stage build: uv for deps, Lambda base for runtime
FROM public.ecr.aws/docker/library/python:3.13-slim AS builder

RUN pip install uv

WORKDIR /build
COPY packages/shared/ /build/packages/shared/
COPY lambdas/pedidos/ /build/lambdas/pedidos/

WORKDIR /build/lambdas/pedidos
RUN uv pip install --system --target /deps pymssql
RUN cp -r src/* /deps/
RUN cp -r /build/packages/shared/src/* /deps/

# Runtime
FROM public.ecr.aws/lambda/python:3.13

COPY --from=builder /deps ${LAMBDA_TASK_ROOT}

# Pre-compile for faster cold start
RUN python -m compileall -q ${LAMBDA_TASK_ROOT}

CMD ["handler.lambda_handler"]
