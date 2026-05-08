FROM python:3.12-slim
WORKDIR /app
COPY . /app/df_executors/df_external_k8s/namespace_apoptosis_isolation/
RUN pip install --no-cache-dir pytest
CMD ["python3", "-m", "pytest", "df_executors/df_external_k8s/", "-q", "--tb=no"]
