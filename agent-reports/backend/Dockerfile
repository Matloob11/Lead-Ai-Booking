FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY backend/scripts ./scripts
COPY panel /panel
ENV PYTHONUNBUFFERED=1
ENV PANEL_DIR=/panel
ENV STORAGE_DIR=/data/reports
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8090"]
