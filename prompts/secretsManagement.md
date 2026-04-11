# Secrets Management

Design and implement a strategy for handling API keys, tokens, passwords, certificates, and other sensitive data. Secrets leaked = breach.

---

## Golden Rules

1. **Never hardcode secrets.** Not in code, not in config files committed to git.
2. **Secrets should be easy to rotate.** If rotating is painful, it won't happen.
3. **Least privilege.** Each service gets only the secrets it needs, not all of them.
4. **Audit access.** Know who accessed what, when, and why.

---

## Secret Types and Their Handling

| Secret type | Examples | How to store |
|------------|----------|--------------|
| API keys (external) | Stripe, Twilio, AWS | Env vars or secret manager |
| Database credentials | PostgreSQL password | Env vars + secret manager |
| JWT signing keys | RS256 private key | Secret manager, never filesystem |
| TLS certificates | SSL cert + key | cert-manager, not plain files |
| User credentials | Passwords, 2FA seeds | Hash with bcrypt/argon2, never plaintext |
| Encryption keys | AES keys, envelope keys | HSM or KMS |

---

## .env Files

For local development only:

```bash
# .env.example (committed to git, no real values)
DATABASE_URL=postgres://user:password@host:5432/db
API_KEY=your_api_key_here
SECRET_KEY=your_secret_key_here
```

```bash
# .env (NOT committed to git)
DATABASE_URL=postgres://appuser:actual_password@prod-db:5432/appdb
API_KEY=sk_live_abcdef123456
SECRET_KEY=super_secret_rotating_key_2024
```

**Rules for .env:**
- [ ] `.env.example` lists every variable (committed to git)
- [ ] `.env` has real values (NOT committed)
- [ ] `.gitignore` includes `.env`
- [ ] `.env.production` uses different values from `.env`
- [ ] No secrets in `.env.production` committed to git

---

## Secret Rotation Checklist

| Secret type | Rotation frequency | How |
|-------------|-------------------|-----|
| Database password | Every 90 days | Update secret manager, update env, rolling restart |
| API keys (external) | Every 90 days or on suspected compromise | Generate new, deploy, revoke old |
| JWT signing key | Every 6 months | Generate new, deploy, revoke old |
| TLS certs | Before expiry (automated) | cert-manager with Let's Encrypt |
| User passwords | On demand / breach | bcrypt hash, user must reset |

---

## Environment Variable Safety

| Pattern | Risk | Better approach |
|---------|------|-----------------|
| `password=foo` in Dockerfile | Visible in image layers | Runtime env var or `--secret` |
| `echo $API_KEY` in logs | Leaks to log files | Redact before logging |
| `print(f"token={token}")` | Leaks to stdout | Mask: `token=***` |
| `api_key` in URL query param | Leaks to logs, browser history | POST body or header |
| `cat secrets.json \| jq .` | Leaks to shell history | `secrets.json` excluded from history |

---

## Git Pre-commit Hook

Scan for leaked secrets before committing:

```bash
# .git/hooks/pre-commit
#!/bin/bash
# Scan for potential secrets
git diff --staged -- . | \
  grep -iE "(api[_-]?key|token|secret|password|credential)" && \
  echo "ERROR: Potential secret detected. Remove before committing." && \
  exit 1
```

Or use a tool: `git-secrets`, `TruffleHog`, or `Gitleaks`.

---

## Secret Manager Options

| Manager | When to use | Notes |
|---------|-------------|-------|
| **HashiCorp Vault** | Production, many services | Most powerful, steep learning curve |
| **AWS Secrets Manager / SSM** | AWS-hosted infrastructure | Native integration with ECS, Lambda, EC2 |
| **Docker secrets** | Docker Swarm | Encrypted at rest, only accessible to running containers |
| **Kubernetes secrets** | K8s workloads | Encrypted at rest (since K8s 1.13), not a secret manager |
| **Doppler /envkey** | Small teams, developer-friendly | Good DX, integrates with GitHub Actions |
| **1Password CLI** | Local development | `op run --` prefix for secrets |

---

## Common Failure Modes

| Failure | Result | Fix |
|---------|--------|-----|
| Secrets in git history | Can't undo, must rotate all | Run `git-secrets` pre-commit, rotate exposed keys |
| Secrets in Docker image | Anyone with image can read them | Runtime env vars, --secret flag |
| No rotation policy | Old keys never rotated | Schedule rotation, automate what you can |
| Same secret everywhere | One breach = all breaches | Per-service credentials |
| Secrets in CI logs | Exposed in build output | Mask env vars in CI config |

---

## Secrets in CI/CD

```yaml
# GitHub Actions example
jobs:
  deploy:
    steps:
      - name: Fetch secrets from Vault
        uses: hashicorp/vault-action@v2
        with:
          secrets: |
            secret/data/prod/api_key api_key
            secret/data/prod/db_password DB_PASSWORD
      - name: Deploy
        env:
          API_KEY: ${{ env.API_KEY }}
          DB_PASSWORD: ${{ env.DB_PASSWORD }}
```

**Never do this:**
```yaml
# BAD — secrets in workflow files
env:
  API_KEY: sk_live_abc123  # Never committed
```

---

## Activation

Proceed with auditing secrets handling for: [describe the project or system]
