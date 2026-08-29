FROM python:3.12-slim

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ && \
    rm -rf /var/lib/apt/lists/*

# Runtime dependencies only. The dev file adds pytest, matplotlib and the R
# reader, none of which a hosted engine has any use for.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY . .

EXPOSE 8000

# Render, Railway and Fly all hand the port in on $PORT and ignore EXPOSE. A
# hardcoded 8000 binds to a port nothing is routed to, and the deployment fails
# its health check with no obvious cause. Shell form so the variable expands.
CMD uvicorn service.app:app --host 0.0.0.0 --port ${PORT:-8000}
