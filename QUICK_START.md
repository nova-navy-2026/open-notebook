# Quick Start Guide

## Prerequisites

- Python 3.11+, Node.js 18+, Docker

## 1. Start SurrealDB

```bash
docker run -d --name surrealdb -p 8000:8000 \
  surrealdb/surrealdb:latest start -u root -p root
```

## 2. Install Dependencies

```bash
# Backend
pip install -e .

# Frontend
cd frontend && npm install && cd ..
```

## 3. Configure Environment

Create a `.env` file in the project root (see [CONFIGURATION.md](CONFIGURATION.md) for all options):

```bash
SURREALDB_URL=ws://localhost:8000
ADMIN_PASSWORD=admin
```

## 4. Start the App

**Terminal 1 — API:**

```bash
python run_api.py
# Runs at http://localhost:5055
# Migrations run automatically on startup
```

**Terminal 2 — Frontend:**

```bash
cd frontend
npm run dev
# Runs at http://localhost:3000
```

## 5. Open the App

Go to `http://localhost:3000` and log in with the password set in `.env`.

## Useful Links

| Resource                | URL                                  |
| ----------------------- | ------------------------------------ |
| App                     | http://localhost:3000                |
| API Docs (Swagger)      | http://localhost:5055/docs           |
| Configuration Reference | [CONFIGURATION.md](CONFIGURATION.md) |
| Full Documentation      | [docs/](docs/index.md)               |
| Contributing            | [CONTRIBUTING.md](CONTRIBUTING.md)   |
