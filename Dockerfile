# Daily Brief Pipeline Docker Image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies (ca-certificates for SSL, fonts for Chinese)
RUN apt-get update && apt-get install -y \
    git \
    curl \
    ca-certificates \
    fonts-noto-cjk \
    fontconfig \
    && update-ca-certificates \
    && fc-cache -fv \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for caching
COPY pyproject.toml ./
COPY src/ ./src/
COPY prompts/ ./prompts/
COPY schemas/ ./schemas/
COPY config/ ./config/
COPY scripts/ ./scripts/
COPY CLAUDE.md ./

# Install Python dependencies
RUN pip install --no-cache-dir -e .

# Create output directories
RUN mkdir -p out data/artifacts data/run_reports

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV TZ=America/New_York
# Fix SSL certificate verification (use system CA bundle)
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
ENV REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
# For httpx (used by OpenAI SDK)
ENV CURL_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
ENV HTTPX_SSL_VERIFY=/etc/ssl/certs/ca-certificates.crt

# Default command: run the pipeline
ENTRYPOINT ["python", "-m", "src.pipeline.run_daily"]
CMD ["--mode", "prod"]
