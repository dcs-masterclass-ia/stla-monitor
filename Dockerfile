FROM python:3.11-slim

RUN apt-get update && apt-get install -y     libglib2.0-0 libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0     libcups2 libdrm2 libdbus-1-3 libxkbcommon0 libxcomposite1     libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2     libpango-1.0-0 libcairo2     && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .

RUN pip install playwright==1.44.0 PyGithub requests urllib3
RUN python -m playwright install chromium

CMD ["python", "stla_monitor.py"]
