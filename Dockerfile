FROM python:3.12-slim

# Links the image to its (private) repo on ghcr.io, so the package gets the repo's access.
LABEL org.opencontainers.image.source=https://github.com/harkenn-project/flash

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
RUN useradd --system --uid 10001 --home-dir /srv flash

USER 10001
EXPOSE 8000
# Pings keep idle relay connections open through Cloudflare (it drops them after 100 s of silence).
CMD ["uvicorn", "--factory", "app.main:create_app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*", "--ws-ping-interval", "30", "--ws-ping-timeout", "30", \
     "--ws-max-size", "1100000"]
