FROM python:3.13-slim AS builder

RUN pip install uv

WORKDIR /build
COPY packages/shared/ /build/packages/shared/
COPY lambdas/facturas/ /build/lambdas/facturas/

WORKDIR /build/lambdas/facturas
RUN uv pip install --system --target /deps pymssql
RUN cp -r src/* /deps/
RUN cp -r /build/packages/shared/src/* /deps/

FROM public.ecr.aws/lambda/python:3.13

COPY --from=builder /deps ${LAMBDA_TASK_ROOT}
RUN python -m compileall -q ${LAMBDA_TASK_ROOT}

CMD ["handler.lambda_handler"]
