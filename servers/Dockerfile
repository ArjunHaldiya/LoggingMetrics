FROM python:3.11-slim
RUN pip install fastapi uvicorn prometheus-fastapi-instrumentator prometheus-client
COPY . .
CMD uvicorn ${SERVER_NAME}:app --host 0.0.0.0 --port ${PORT}