# Build the sync engine. Same Debian release as the runtime image, so glibc matches.
FROM rust:1-slim-trixie AS engine
WORKDIR /src
COPY sync/Cargo.toml sync/Cargo.lock ./
# Build dependencies alone first so code changes don't rebuild them.
RUN mkdir src && echo "fn main() {}" > src/main.rs && touch src/lib.rs \
    && cargo build --release --locked && rm -rf src
COPY sync/src ./src
RUN touch src/main.rs src/lib.rs && cargo build --release --locked

FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DATA_DIR=/app/data

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY --from=engine /src/target/release/eng-health /usr/local/bin/eng-health
COPY eng_health ./eng_health
COPY main.py dashboard_main.py ./
# UID 1000 matches the usual host user, so the ./data bind mount stays writable.
RUN useradd --create-home --uid 1000 app && mkdir -p /app/data && chown app /app/data
USER app

EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')"
CMD ["streamlit", "run", "dashboard_main.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
