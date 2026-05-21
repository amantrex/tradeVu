tradeVu is a lightweight, self‑contained AI‑driven trading bot that can run 24 × 7 on any Ubuntu‑based cloud VM.
It stitches together:

Component	Role
Python core (config.py, worker.py, agent/…)	Market data ingestion, signal generation, order execution logic
Dashboard (dashboard/app.py)	Live web UI showing positions, performance charts, and logs
Docker Compose (docker-compose.yml)	One‑click orchestration of the Python services, Redis cache, and optional PostgreSQL persistence
deploy.sh	Automates provisioning of a fresh Ubuntu VM, clones the repo, installs dependencies, and starts the Docker stack
