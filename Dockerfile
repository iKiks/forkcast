FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt azure-identity azure-eventhub

COPY forkcast ./forkcast
COPY scripts ./scripts
COPY web ./web
COPY docs ./docs

# Pre-fit the fork model for the default fixture so the first match starts instantly.
RUN python -c "from forkcast.forks import load_or_fit; load_or_fit('kes', 'amb')"

EXPOSE 8000
CMD ["uvicorn", "forkcast.server:app", "--host", "0.0.0.0", "--port", "8000"]
