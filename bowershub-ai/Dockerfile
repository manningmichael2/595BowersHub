# ============================================================
# Stage 1: Build React frontend
# ============================================================
FROM node:20-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --ignore-scripts 2>/dev/null || npm install
COPY frontend/ ./
RUN npm run build

# ============================================================
# Stage 2: Python backend + compiled frontend
# ============================================================
FROM python:3.12-slim
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY backend/ ./backend/

# Copy default-icon generator script — referenced by `branding_store.revert_to_default`
# (R2.6) when an admin asks to restore the built-in icon set. Pillow is already in
# requirements.txt so no extra deps needed.
COPY scripts/generate_icons.py ./scripts/generate_icons.py

# Copy compiled frontend from Stage 1
COPY --from=frontend-build /app/frontend/dist ./static/

# Copy default configs
COPY patterns.json ./patterns.json

# Expose port
EXPOSE 5003

# Run with uvicorn
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "5003", "--workers", "1", "--log-level", "info"]
