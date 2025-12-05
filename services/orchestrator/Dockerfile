FROM python:3.10-slim

WORKDIR /app

# Install FFMPEG for splitting/stitching [cite: 644]
RUN apt-get update && apt-get install -y ffmpeg

RUN pip install fastapi uvicorn google-cloud-storage google-cloud-firestore google-cloud-tasks requests

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]