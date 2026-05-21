FROM python:3.10-slim

# Install system dependencies required by Playwright
RUN apt-get update && apt-get install -y wget xvfb && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browser and dependencies
RUN playwright install --with-deps chromium

# Copy project files
COPY . .

# Set environment variables
ENV PYTHONUNBUFFERED=1

# By default, we will run both the worker and the dashboard. 
# We use a simple shell script to run both.
RUN echo '#!/bin/bash\npython worker.py &\npython dashboard/app.py\n' > start.sh
RUN chmod +x start.sh

EXPOSE 8080

CMD ["./start.sh"]
