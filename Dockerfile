# MarketProbe Pipeline — Cloud Run Jobs container
# Uses Playwright base image for form automation (Chromium included)

FROM mcr.microsoft.com/playwright/python:v1.50.0-noble

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers
RUN playwright install --with-deps chromium

# Copy application code
COPY scripts/ scripts/
COPY templates/ templates/
COPY run.py .

# Create data directories
RUN mkdir -p data/lp_content data/logs credentials

# Default entrypoint: run.py reads SCRIPT_NAME env var
CMD ["python", "run.py"]
