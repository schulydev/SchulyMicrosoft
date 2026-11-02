FROM python:3.13-slim

ARG DEBIAN_FRONTEND=noninteractive
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd --create-home --shell /bin/bash app && chown -R app:app /app
USER app

EXPOSE 8010

HEALTHCHECK --interval=10s --timeout=3s --start-period=30s --retries=3 \n  CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8010/health/ready', timeout=2)"

CMD ["python", "asgi.py"]
