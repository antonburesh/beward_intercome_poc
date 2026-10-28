FROM node:22-bookworm-slim AS web

WORKDIR /src
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web ./
RUN npm run build

FROM python:3.12-slim-bookworm

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY phone ./phone
COPY --from=web /src/dist ./web/dist

ENV PYTHONUNBUFFERED=1
CMD ["python3", "-u", "phone/app.py"]
