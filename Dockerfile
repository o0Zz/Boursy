# syntax=docker/dockerfile:1

# ---- Stage 0: version ----
# CI passes APP_VERSION. A local `docker compose build` does not, so it is computed here from .git
# with the same rule as CI: tag vX.Y.Z gives X.Y.Z, branch release/X.Y.Z gives X.Y.Z+<commit count>
# (release/X.Y counts as X.Y.0), any other branch gives 0.0.0-<branch>+<commit count>.
FROM --platform=$BUILDPLATFORM alpine:3.22 AS version
ARG APP_VERSION
RUN apk add --no-cache git
# The wildcard keeps the build working without a .git (a source archive): a COPY whose only source
# is missing fails. A wildcard copies the directory's contents, hence --git-dir below.
COPY backend/pyproject.toml .gi[t] /src/git/
RUN set -eu; \
    g() { git --git-dir=/src/git "$@"; }; \
    version="${APP_VERSION:-}"; \
    if [ -z "$version" ] && g rev-parse -q --verify HEAD >/dev/null 2>&1; then \
        count=$(g rev-list --count HEAD); \
        branch=$(g rev-parse --abbrev-ref HEAD); \
        release=$(printf '%s' "$branch" | sed -nE 's#^release/([0-9]+\.[0-9]+(\.[0-9]+)?).*#\1#p'); \
        if [ -n "$release" ]; then \
            case "$release" in *.*.*) ;; *) release="$release.0" ;; esac; \
            version="$release+$count"; \
        else \
            # Semver pre-release identifiers only allow [0-9A-Za-z-].
            version="0.0.0-$(printf '%s' "$branch" | tr -c '0-9A-Za-z-' '-')+$count"; \
        fi; \
    fi; \
    echo "${version:-0.0.0-dev}" > /version; \
    echo "Version: $(cat /version)"

# ---- Stage 1: React build (static output, so build on the host platform) ----
FROM --platform=$BUILDPLATFORM node:22-bookworm-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# Copied last: a new commit only rebuilds the frontend when the version changes.
COPY --from=version /version /version
RUN APP_VERSION="$(cat /version)" npm run build

# ---- Stage 2: Python runtime (API + scheduler + static files) ----
# Alpine instead of Debian slim: Debian bookworm carried ~98 HIGH/CRITICAL CVEs with no fix
# available (krb5, util-linux, sqlite). `apk upgrade` pulls fixes published after the base tag.
FROM python:3.12-alpine AS runtime
COPY --from=ghcr.io/astral-sh/uv:0.9.21 /uv /usr/local/bin/uv

# pip ships with the base image but is unused (uv installs the deps) and carries its own CVEs.
RUN apk upgrade --no-cache && apk add --no-cache tzdata ca-certificates \
    && python -m pip uninstall -y pip

# Claude Code CLI for the `subscription` AI backend (headless `claude -p`). Native installer,
# pinned version, no auto-update. On Alpine it needs libgcc, libstdc++ and the system ripgrep.
ARG CLAUDE_CODE_VERSION=2.1.322
RUN apk add --no-cache libgcc libstdc++ ripgrep \
    && apk add --no-cache --virtual .claude-install bash curl \
    && HOME=/opt/claude-code bash -c "curl -fsSL https://claude.ai/install.sh | bash -s ${CLAUDE_CODE_VERSION}" \
    && ln -s "$(readlink -f /opt/claude-code/.local/bin/claude)" /usr/local/bin/claude \
    && chmod -R a+rX /opt/claude-code \
    && apk del .claude-install \
    && HOME=/tmp claude --version && rm -rf /tmp/.claude*
ENV USE_BUILTIN_RIPGREP=0 \
    DISABLE_AUTOUPDATER=1

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    TZ=Europe/Paris \
    BOURSY_DATA_DIR=/data \
    BOURSY_STATIC_DIR=/app/static \
    UV_NO_CACHE=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/alembic.ini ./
COPY backend/boursy ./boursy
RUN uv sync --frozen --no-dev
COPY --from=web /web/dist ./static
COPY --from=version /version ./VERSION

RUN addgroup -S -g 1000 boursy && adduser -S -D -u 1000 -h /app -G boursy boursy \
    && mkdir -p /data && chown boursy:boursy /data
USER boursy
# Runtime caches (yfinance cookies and timezones) go to the writable volume.
ENV XDG_CACHE_HOME=/data/cache
VOLUME /data
EXPOSE 8000

HEALTHCHECK --interval=60s --timeout=5s --start-period=30s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"

# One worker only: the scheduler runs inside the app process.
CMD ["uvicorn", "boursy.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
