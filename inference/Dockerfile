FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HF_HOME=/models/.hf
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py .
RUN useradd --create-home --uid 10001 han && mkdir -p /models && chown -R han /models /srv
USER han
EXPOSE 9000
HEALTHCHECK CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:9000/healthz')" || exit 1
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "9000"]
