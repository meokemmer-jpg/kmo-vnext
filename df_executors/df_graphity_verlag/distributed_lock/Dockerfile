# Graphity-Verlag Distributed-Lock Dockerfile [CRUX-MK]
# Welle-30 W-30-3: Synaptic-Pattern auf Graphity-Verlag
# Bio-Pattern aus kmo_governance/saga-pattern wiederverwendet

FROM python:3.12-slim

WORKDIR /app

# Pin minimal deps (matches saga-pattern stack)
RUN pip install --no-cache-dir \
        pyyaml==6.0.2 \
        pytest==8.3.4

# Copy production-code + tests
COPY graphity_lock_manager.py /app/
COPY graphity_concurrent_edit_resolver.py /app/
COPY graphity_audit_persister.py /app/
COPY __init__.py /app/
COPY tests/ /app/tests/

# Default secret for Dockerized smoke-tests (override via -e in production)
ENV GRAPHITY_LOCK_SECRET=docker-default-please-override

# Run pytest as smoke-test on container startup
CMD ["python", "-m", "pytest", "-q", "--tb=no", "tests/"]
