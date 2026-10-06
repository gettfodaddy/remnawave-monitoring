FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends tzdata ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY digest.py /app/digest.py
ENTRYPOINT ["python", "/app/digest.py"]
