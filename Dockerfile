# sloptriage CLI with its tree-sitter grammars preinstalled.
#   docker run --rm ghcr.io/b0yko/sloptriage:0.1.0 demo
FROM python:3.12-slim@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704 AS build
WORKDIR /src
COPY . .
RUN pip install --no-cache-dir build==1.3.0 && python -m build --wheel --outdir /dist

FROM python:3.12-slim@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704
RUN apt-get update \
 && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 10001 app
COPY --from=build /dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm /tmp/*.whl
USER app
WORKDIR /home/app
ENV PYTHONDONTWRITEBYTECODE=1
ENTRYPOINT ["sloptriage"]
CMD ["--help"]
