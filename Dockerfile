FROM python:3.12-slim-bookworm

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY phone ./phone

ENV PYTHONUNBUFFERED=1
CMD ["python3", "-u", "phone/app.py"]
