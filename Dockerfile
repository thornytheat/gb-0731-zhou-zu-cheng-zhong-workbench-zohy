FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /srv/weigh
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app app
COPY sample_data sample_data
COPY tests tests
COPY pytest.ini .
RUN mkdir var
EXPOSE 18420
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "18420"]
