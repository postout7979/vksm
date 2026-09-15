FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

# HEALTH_FILE is touched on every successful report loop iteration;
# used by the Deployment's livenessProbe (see k8s/supervisor-agent.yaml).
ENV HEALTH_FILE=/tmp/agent-healthy

CMD ["python", "main.py"]
