# Welle-30 W-30-1 Cape-Coral-Familien-Audit-Bus (Lymphatic-Pattern) [CRUX-MK]
FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*
COPY requirements.txt* ./
RUN pip install --no-cache-dir pytest 2>/dev/null || true
COPY . /app
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import sys; sys.path.insert(0,'/app'); import familien_audit_bus; sys.exit(0)"
# Default: pytest run als Service-Stub
CMD ["python", "-c", "import time; print('Cape-Coral familien_audit_bus stub running'); time.sleep(86400)"]
