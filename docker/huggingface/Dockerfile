FROM python:3.11-alpine

WORKDIR /app

RUN apk add --no-cache curl

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

EXPOSE 7860

CMD ["python", "main.py"]
