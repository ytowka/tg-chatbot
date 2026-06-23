FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config.py main.py ./
COPY bot/ ./bot/
COPY llm/ ./llm/
COPY storage/ ./storage/

RUN mkdir -p data

CMD ["python", "main.py"]
