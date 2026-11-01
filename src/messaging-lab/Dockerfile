FROM python:3.14-slim@sha256:cd89c30eda26ee911a4611b18680086e0ea42e6f5f8cbe653d07fa7958c9cec8
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY lab.py .
USER 10001:10001
ENV PYTHONDONTWRITEBYTECODE=1
CMD ["python", "-c", "import time; time.sleep(2147483647)"]
