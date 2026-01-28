# Alfred Prime & Daemon Dockerfile

FROM python:3.11-slim as base

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy project files
COPY pyproject.toml .
COPY src/ src/

# Install dependencies
RUN pip install --no-cache-dir -e .

# Alfred Prime target
FROM base as prime

EXPOSE 8000

CMD ["python", "-m", "alfred.prime.main"]

# Alfred Daemon target
FROM base as daemon

# Install daemon extras (playwright for browser automation)
RUN pip install --no-cache-dir -e ".[daemon]"

EXPOSE 8001

CMD ["python", "-m", "alfred.daemon.main"]
