FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY AquaTidy.py storage.py ./
ENV DATABASE_PATH=/data/aquatidy.sqlite3
CMD ["python", "AquaTidy.py"]
