FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY outputs ./outputs
COPY work ./work
COPY data ./data

EXPOSE 4173

CMD ["python", "work/cloud-runner.py", "--port", "4173", "--live-interval", "15", "--news-interval", "300", "--learning-interval", "60"]
