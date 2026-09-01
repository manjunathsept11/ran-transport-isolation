# Multi-stage: build the React dashboard, then serve it from the FastAPI image.
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM python:3.12-slim AS app
ENV PYTHONUNBUFFERED=1 PYTHONUTF8=1 \
    NA_DATA_DIR=/data NA_REPORTS_DIR=/reports
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN uv pip install --system --no-cache -e .
COPY config/ ./config/
COPY notebooks/ ./notebooks/
COPY --from=web /web/dist ./web/dist
RUN mkdir -p /data /reports
EXPOSE 8000
CMD ["uvicorn", "networkanalysis.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
