# Canon audit image: ingest -> resolve -> serve/eval inside the client's environment.
# Ubuntu 24.04: Python 3.12 and tesseract 5.3.4, the same versions CI tests with.
#   docker build -t canon .
#   docker run --rm --network none -v "$PWD/export:/data:ro" -v "$PWD/out:/out" canon resolve
# More in docs/DEPLOY.md.
ARG BASE_IMAGE=ubuntu:24.04
FROM ${BASE_IMAGE}

ENV DEBIAN_FRONTEND=noninteractive
# Behind a TLS-inspecting proxy, pass its CA with --secret id=ca,src=/path/ca.pem (and the proxy
# via the standard http_proxy/https_proxy build args). It is trusted during the build only.
# apt bootstraps ca-certificates without TLS peer checks; packages stay GPG-verified by apt.
RUN --mount=type=secret,id=ca,required=false \
    sed -i 's|http://|https://|g' /etc/apt/sources.list.d/ubuntu.sources \
 && apt-get -o Acquire::https::Verify-Peer=false update \
 && apt-get -o Acquire::https::Verify-Peer=false install -y --no-install-recommends ca-certificates \
 && if [ -s /run/secrets/ca ]; then \
      cp /run/secrets/ca /usr/local/share/ca-certificates/build-proxy.crt && update-ca-certificates; fi \
 && apt-get install -y --no-install-recommends \
      python3.12 python3-pip tesseract-ocr tesseract-ocr-fra tesseract-ocr-ara fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*

ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt PIP_CERT=/etc/ssl/certs/ca-certificates.crt \
    UV_NATIVE_TLS=1 UV_PYTHON_DOWNLOADS=never UV_PYTHON=python3.12 \
    UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH CANON_OUT_DIR=/out CANON_DATA_DIR=/data
RUN pip install --no-cache-dir --break-system-packages uv==0.11.32
WORKDIR /app

# dependencies first (cached layer), then the project itself
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project
COPY canon ./canon
RUN uv sync --locked --no-dev

RUN rm -f /usr/local/share/ca-certificates/build-proxy.crt && update-ca-certificates --fresh >/dev/null \
 && useradd --create-home --uid 10001 canon && mkdir -p /out /data && chown canon /out
USER canon
VOLUME ["/data", "/out"]
EXPOSE 8765
ENTRYPOINT ["canon"]
CMD ["--help"]
