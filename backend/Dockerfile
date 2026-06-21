FROM mcr.microsoft.com/playwright/python:v1.49.1-jammy

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    FB_API_HOST=0.0.0.0 \
    FB_API_PORT=8003 \
    FB_HEADLESS=true \
    FB_BROWSER_CHANNEL= \
    SENTIMENT_MODE=rule_only \
    GEMINI_ENABLED=False

WORKDIR /app/backend

COPY backend/requirements.txt ./requirements.txt
RUN python -m pip install --upgrade pip \
    && pip install -r requirements.txt

COPY backend/ ./

EXPOSE 8003

CMD ["python", "main.py"]
