# Build the sync engine. Same Debian release as the runtime image, so glibc matches.
# rustup installs the version in rust-toolchain.toml if the image's differs.
FROM rust:1.99-slim-trixie AS engine
# The repo's layout, because sync/ includes ../schema.sql and rustup reads ../rust-toolchain.toml.
WORKDIR /repo/sync
COPY rust-toolchain.toml schema.sql /repo/
COPY sync/Cargo.toml sync/Cargo.lock ./
# Build dependencies alone first so code changes don't rebuild them.
RUN mkdir src && echo "fn main() {}" > src/main.rs && touch src/lib.rs \
    && cargo build --release --locked && rm -rf src
COPY sync/src ./src
RUN touch src/main.rs src/lib.rs && cargo build --release --locked

FROM python:3.14.8-slim-trixie

COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /usr/local/bin/uv

# UV_PYTHON_DOWNLOADS=never: if this image's Python stops matching .python-version, the
# build fails instead of quietly downloading another one.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_NO_CACHE=1 \
    PATH=/app/.venv/bin:$PATH \
    DATA_DIR=/app/data

WORKDIR /app
COPY .python-version pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev

COPY --from=engine /repo/sync/target/release/eng-health /usr/local/bin/eng-health
COPY schema.sql ./
COPY eng_health ./eng_health
COPY main.py dashboard_main.py ./
# UID 1000 matches the usual host user, so the ./data bind mount stays writable.
RUN useradd --create-home --uid 1000 app && mkdir -p /app/data && chown app /app/data
USER 1000

EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')"]
CMD ["streamlit", "run", "dashboard_main.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
