FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ app/
COPY run.py .

EXPOSE 8000

# config.yaml is volume-mounted at runtime, NOT baked into the image.
# ANTHROPIC_API_KEY is passed as an environment variable.
CMD ["python", "run.py"]
