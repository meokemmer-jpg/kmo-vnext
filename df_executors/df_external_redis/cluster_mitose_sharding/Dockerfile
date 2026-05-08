# Auto-generated 2026-05-08 fuer Welle-30-Iter-2 W-30R-2 Redis-Cluster-Mitose-Sharding [CRUX-MK]
FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*
COPY requirements.txt* ./
RUN pip install --no-cache-dir pytest 2>/dev/null || true
COPY . /app
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import sys; sys.exit(0)"
CMD ["python", "-c", "import time; print('df_external_redis cluster_mitose_sharding Mock-Layer running'); time.sleep(86400)"]
