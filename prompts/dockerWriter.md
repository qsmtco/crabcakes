# Docker Writer

Write Dockerfiles and docker-compose files that are correct, minimal, and secure.

---

## Dockerfile Checklist

### Structure

- [ ] Start with the most specific base image (not `ubuntu:latest`, use `python:3.12-slim`)
- [ ] Pin versions — `python:3.12-slim` not `python:slim`
- [ ] One instruction per layer — each `RUN`, `COPY`, `ENV` is its own layer
- [ ] Run as non-root unless there's a specific reason not to
- [ ] No secrets in the image — use `--secret` or runtime env vars
- [ ] Clean up in the same layer it was created (use `&&` chains, not separate RUN)

### Layer Order (Build Cache Optimization)

```
1. Base image
2. System deps (apt-get install)
3. Python/Node/etc. deps (requirements.txt, package.json)
4. App source code
5. Entrypoint / CMD
```

Put things that change most often LAST so build cache isn't busted on every edit.

### Minimal Dockerfile Pattern

```dockerfile
FROM python:3.12-slim

# System deps only
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Python deps — separate layer for caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY . .

# Non-root user
RUN useradd --create-home appuser
USER appuser

CMD ["python", "app.py"]
```

### Security Hardening

- [ ] Use `python:3.12-slim` not `python:3.12` (smaller attack surface)
- [ ] `--no-install-recommends` on apt-get
- [ ] `--no-cache-dir` on pip
- [ ] `USER` directive — never run as root in production
- [ ] No `ADD . .` — use `COPY` with explicit paths
- [ ] `.dockerignore` to exclude: `.git`, `__pycache__`, `*.pyc`, `node_modules`, `.env`

---

## docker-compose.yml Checklist

### Service Definition

- [ ] Pin image tags — `postgres:16` not `postgres:latest`
- [ ] Explicit `restart:` policy (`unless-stopped` for services, `no` for one-offs)
- [ ] Named volumes for persistent data — not bind mounts in prod
- [ ] Health checks for long-running services
- [ ] Resource limits (`mem_limit`, `cpus`) — prevent one service from eating the host
- [ ] `depends_on` for startup order (but note: doesn't wait for "healthy")
- [ ] `networks` — separate networks for app / db / redis

### Environment Variables

```yaml
services:
  app:
    env_file:
      - .env.production  # never .env with real secrets
    environment:
      - NODE_ENV=production
      - LOG_LEVEL=info
    secrets:
      - db_password   # use docker secrets, not env vars for real secrets
```

### Data Persistence

```yaml
volumes:
  db_data:
    driver: local

services:
  db:
    volumes:
      - db_data:/var/lib/postgresql/data  # named volume, not bind mount
```

---

## Multi-Stage Builds

For compiled languages or front-end assets:

```dockerfile
# Stage 1: Build
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

# Stage 2: Run
FROM node:20-alpine
WORKDIR /app
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/node_modules ./node_modules
CMD ["node", "dist/index.js"]
```

**Benefits:** Final image has no source code, no build tools, no compiler.

---

## Common Failure Modes

| Failure | Fix |
|---------|-----|
| Image too large | Use slim/alpine variants, multi-stage builds |
| Secrets in env vars | Use Docker secrets or a secret manager |
| `ADD` instead of `COPY` | `ADD` auto-extracts tar files — usually not what you want |
| No health check | Container looks "running" even if the app is dead |
| `latest` tag | Pin to specific version — `latest` changes over time |
| Missing `.dockerignore` | Large images, build cache pollution, secret leakage |

---

## docker-compose Commands

| Command | When to use |
|---------|-------------|
| `docker compose up -d` | Start all services |
| `docker compose down -v` | Stop and remove volumes (destructive!) |
| `docker compose logs -f [service]` | Tail logs |
| `docker compose exec [service] sh` | Shell into a running container |
| `docker compose build --no-cache` | Force rebuild without cache |

---

## Activation

Proceed with writing a Dockerfile or docker-compose for: [describe the project]
