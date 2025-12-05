FROM python:3.10-slim

WORKDIR /app

# Install dependencies
# Added: google-cloud-storage
RUN pip install fastapi uvicorn python-multipart google-cloud-firestore google-cloud-tasks google-cloud-storage httpx

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]