# Execution image for student code. No network at runtime (enforced by `docker run --network none`).
FROM python:3.12-slim
RUN pip install --no-cache-dir numpy==2.2.6 && useradd --uid 10001 --no-create-home runner
COPY runner.py /runner/runner.py
USER 10001
WORKDIR /tmp
ENTRYPOINT ["python", "-I", "/runner/runner.py"]
