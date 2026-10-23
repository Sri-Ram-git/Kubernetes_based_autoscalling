FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

# Install dependencies for controller and dashboard
COPY dashboard/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Copy application source code
COPY controller/ /app/controller/
COPY dashboard/ /app/dashboard/
COPY policies/ /app/policies/
RUN mkdir -p /app/logs

EXPOSE 5000

CMD ["python", "-m", "dashboard.app"]
