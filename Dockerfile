# Build the existing React/Vite dashboard.
FROM node:22-slim AS web
WORKDIR /w
COPY webapp/frontend/package.json webapp/frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY webapp/frontend/ ./
RUN npm run build

# Playwright's image includes the Linux libraries and matching browser runtime.
# Keep the Python Playwright package pinned to the image's browser version.
FROM mcr.microsoft.com/playwright/python:v1.55.0-noble
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 CAREER_AGENT_CLOUD=1 CAREER_AGENT_CLOUD_BROWSER=1
WORKDIR /app
COPY requirements.txt /tmp/req-root.txt
COPY webapp/backend/requirements.txt /tmp/req-backend.txt
RUN pip install --no-cache-dir -r /tmp/req-root.txt -r /tmp/req-backend.txt \
    && pip install --no-cache-dir --no-deps playwright==1.55.0
COPY . /app
COPY --from=web /w/dist /app/webapp/frontend/dist
RUN chmod +x /app/docker-entrypoint.sh
EXPOSE 10000
CMD ["/app/docker-entrypoint.sh"]
