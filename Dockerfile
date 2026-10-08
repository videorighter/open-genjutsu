FROM node:24-bookworm-slim AS web
WORKDIR /build
COPY package.json package-lock.json ./
RUN --mount=type=secret,id=build_ca,target=/tmp/build-ca.pem,required=false \
    if [ -s /tmp/build-ca.pem ]; then NODE_EXTRA_CA_CERTS=/tmp/build-ca.pem npm ci; else npm ci; fi
COPY . ./
RUN npm run build

FROM python:3.12-slim-bookworm AS service
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/backend
WORKDIR /app
COPY backend/requirements.txt ./requirements.txt
RUN --mount=type=secret,id=build_ca,target=/tmp/build-ca.pem,required=false \
    apt-get update && apt-get install -y --no-install-recommends ffmpeg curl && \
    rm -rf /var/lib/apt/lists/* && \
    if [ -s /tmp/build-ca.pem ]; then cat /tmp/build-ca.pem >> /etc/ssl/certs/ca-certificates.crt; fi && \
    PIP_CERT=/etc/ssl/certs/ca-certificates.crt pip install --no-cache-dir --timeout 30 --retries 2 -r requirements.txt && \
    useradd --uid 10001 --create-home app && mkdir /data && chown app:app /data
COPY --chown=app:app backend ./backend
COPY --from=web --chown=app:app /build/package.json ./package.json
ARG RELEASE_VERSION
ARG BUILD_REVISION=unknown
LABEL org.opencontainers.image.title="Open Genjutsu" \
      org.opencontainers.image.source="https://github.com/videorighter/open-genjutsu" \
      org.opencontainers.image.version=$RELEASE_VERSION \
      org.opencontainers.image.revision=$BUILD_REVISION
ENV GENJUTSU_BUILD_REVISION=$BUILD_REVISION
RUN python -c 'import json,os; v=os.environ.get("RELEASE_VERSION", ""); assert not v or v == json.load(open("package.json"))["version"], "Release version mismatch"'
COPY --from=web --chown=app:app /build/dist ./dist
USER app
EXPOSE 8000
CMD ["uvicorn", "genjutsu.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--limit-concurrency", "64"]
