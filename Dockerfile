# Docker's official images, from AWS's public mirror of them: Docker Hub limits anonymous pulls
# per IP address, and CI runners share theirs, so builds there failed at random with 429.
#
# Build the sync engine. Same Debian release as the runtime image, so glibc matches.
# rustup installs the version in rust-toolchain.toml if the image's differs.
FROM public.ecr.aws/docker/library/rust:1.99-slim-trixie AS engine
# The repo's layout, because rustup reads ../rust-toolchain.toml.
WORKDIR /repo/sync
COPY rust-toolchain.toml /repo/
COPY sync/Cargo.toml sync/Cargo.lock sync/schema.sql ./
# Build dependencies alone first so code changes don't rebuild them.
RUN mkdir src && echo "fn main() {}" > src/main.rs && touch src/lib.rs \
    && cargo build --release --locked && rm -rf src
COPY sync/src ./src
RUN touch src/main.rs src/lib.rs && cargo build --release --locked

FROM public.ecr.aws/docker/library/python:3.14.8-slim-trixie

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
# uv is mounted for this step only: the image doesn't need it to run.
RUN --mount=from=ghcr.io/astral-sh/uv:0.12.23,source=/uv,target=/bin/uv \
    uv sync --locked --no-dev

COPY --from=engine /repo/sync/target/release/eng-health /usr/local/bin/eng-health
COPY sync/schema.sql ./sync/
COPY eng_health ./eng_health
COPY main.py dashboard_main.py ./
# UID 1000 matches the usual host user, so the ./data bind mount stays writable.
RUN useradd --create-home --uid 1000 app && mkdir -p /app/data && chown app /app/data
USER 1000

EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')"]
CMD ["streamlit", "run", "dashboard_main.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
