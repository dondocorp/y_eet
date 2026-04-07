FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# System deps for Playwright + torch
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdbus-1-3 libdrm2 libxcb1 libxkbcommon0 libatspi2.0-0 \
    libx11-6 libxcomposite1 libxdamage1 libxext6 libxfixes3 \
    libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 \
    curl wget \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# Install torch CPU separately to avoid pulling CUDA index
RUN pip install torch==2.3.0 --index-url https://download.pytorch.org/whl/cpu && \
    grep -v "^torch" requirements.txt > /tmp/req_no_torch.txt && \
    pip install -r /tmp/req_no_torch.txt

# Install Playwright browsers (Chromium only)
# install-deps is skipped — system deps are handled above via apt-get
RUN playwright install chromium

COPY . .

RUN mkdir -p /app/data /app/model_cache

# Pre-download sentiment model at build time so runtime doesn't pull it
RUN python -c "from transformers import AutoTokenizer, AutoModelForSequenceClassification; \
    AutoTokenizer.from_pretrained('cardiffnlp/twitter-roberta-base-sentiment-latest', cache_dir='/app/model_cache'); \
    AutoModelForSequenceClassification.from_pretrained('cardiffnlp/twitter-roberta-base-sentiment-latest', cache_dir='/app/model_cache')" \
    || echo "Model pre-download failed — will download at runtime"

EXPOSE 9465

CMD ["python", "scripts/scheduler.py"]

# ── Streamlit variant ─────────────────────────────────────────────────────────
FROM base AS streamlit
EXPOSE 8501
CMD ["streamlit", "run", "dashboard/app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false"]
