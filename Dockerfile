# The model runs on Amazon Bedrock, so this image only holds the server.
# The key comes in as the BEDROCK_API_KEY environment variable.
#   docker build -t mb-server-ai .
#   docker run --env-file mb-server-ai.env -p 8000:8000 mb-server-ai
FROM python:3.12-slim

RUN useradd --create-home --uid 1000 app
WORKDIR /home/app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=app *.py ./
COPY --chown=app data/ ./data/

USER app
ENV PYTHONDONTWRITEBYTECODE=1
EXPOSE 8000
# The proxy in front (Caddy) adds the visitor's address to X-Forwarded-For,
# which limits.py reads.
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
