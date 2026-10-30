FROM python:3.10-slim

# تثبيت FFmpeg
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# تثبيت مكتبة requests
RUN pip install --no-cache-dir requests

COPY . /app

CMD ["python", "main.py"]
