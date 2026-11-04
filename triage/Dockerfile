FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir tzdata
COPY --chmod=644 app.py .
RUN useradd -m triage
USER triage
CMD ["python", "-u", "app.py"]
