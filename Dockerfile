FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Install package dependencies
COPY pyproject.toml README.md ./
COPY config/ config/
COPY ops/ ops/
COPY substrate/ substrate/
COPY triage/ triage/
RUN mkdir -p eval && touch eval/__init__.py

RUN pip install --no-cache-dir .

ENTRYPOINT ["python", "-m", "substrate.entrypoint"]

