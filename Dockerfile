FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY sandbox ./sandbox
COPY samples ./samples
COPY tools ./tools

ENV SANDBOX_HOST=0.0.0.0 SANDBOX_PORT=8099 SANDBOX_DATA_DIR=/data
VOLUME /data
EXPOSE 8099
CMD ["python", "-m", "sandbox.app"]
