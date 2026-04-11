# Feature Flags

Design and manage feature flags so features can be shipped safely, rolled back instantly, and targeted to specific users.

---

## Before You Add a Flag

1. **Why is this a flag?** (control rollout, kill switch, A/B test, personalization)
2. **Who manages it?** (engineer, PM, marketing, automated)
3. **How long does it live?** (short-lived = code debt, long-lived = complexity)
4. **What's the default?** (on or off for new users)

---

## Flag Types

| Type | Purpose | Example |
|------|---------|---------|
| **Kill switch** | Emergency disable | "Disable payments if Stripe fails" |
| **Rollout** | Gradual enable | "5% → 25% → 100% of users" |
| **A/B test** | Measure preference | "Variant A vs Variant B" |
| **Beta** | Early access | "Enable for beta users only" |
| **Permissions** | User-specific | "Enable for premium users only" |
| **Configuration** | Runtime behavior | "Max retries = 3" |

---

## Naming Convention

```
<type>_<team>_<feature>

Examples:
- rollout_platform_new_checkout
- kill_switch_payment_stripe
- ab_marketing_signup_flow_v2
- beta_ai_image_generator
- config_retry_max_attempts
```

---

## Flag Checklist

### Before Creating

- [ ] Is this a feature flag or a config value? (config values don't need a flag management system)
- [ ] What's the rollout plan? (0% → small → large → 100%)
- [ ] What's the rollback trigger? (define before shipping)
- [ ] Who can toggle this? (define access controls)
- [ ] When does this flag get removed? (must have a removal date)

### Implementation

```python
# Good: clean, readable flag evaluation
if feature_flags.is_enabled("rollout_new_checkout", user_id=request.user.id):
    return new_checkout_flow()
else:
    return legacy_checkout_flow()

# Bad: flag spread throughout codebase, no central management
if os.environ.get("ENABLE_NEW_CHECKOUT") == "true":
    return new_checkout_flow()
```

---

## Rollout Checklist

| Phase | Percentage | What to measure |
|-------|-----------|-----------------|
| 0% (internal) | 0% | Does it work in production? |
| Internal | 100% of team | Functional testing |
| Alpha | 1% random | Initial smoke test |
| Beta | 10% | Error rates, latency |
| Staged | 25% → 50% → 75% | Measure same metrics |
| Full | 100% | Confirm metrics improved |

### Metrics to Watch

| Metric | What it tells you |
|--------|-------------------|
| Error rate | Flag introducing bugs |
| Latency (p50, p99) | Performance impact |
| Conversion rate | Business impact |
| Support tickets | User confusion |

---

## Flag Lifecycle

```
Created → Active (rolling out) → Fully shipped → Deprecated → Removed
```

| Stage | Rules |
|-------|-------|
| **Active** | Can be toggled, monitored |
| **Fully shipped** | Flag code removed, flag deleted |
| **Deprecated** | Flag off for everyone, will be removed |
| **Removed** | Code path deleted |

**Never leave old flags in the codebase.** Each flag is technical debt.

---

## Kill Switch Checklist

Kill switches are for stopping the bleeding — not for gradual rollback.

- [ ] Kill switch is in the right place (at the service boundary)
- [ ] Toggle is fast (no deploy needed — runtime)
- [ ] Circuit breaker pattern used? (auto-toggle on error threshold)
- [ ] On-call knows where the kill switch is and how to use it
- [ ] Killing the feature doesn't leave data in an inconsistent state
- [ ] There's a runbook for post-kill recovery

---

## Flag Storage Options

| Option | When to use | Notes |
|--------|-------------|-------|
| Config file / env var | Kill switches, static flags | No dynamic toggling |
| Redis | Fast toggle, single-region | Not persistent |
| LaunchDarkly / Split.io | Production flag management | Paid, powerful |
| In-app DB table | Simple, self-hosted | More work to build |

---

## Common Failure Modes

| Failure | Why it's bad | Fix |
|---------|--------------|-----|
| Flags never removed | Codebase pollution, confusion | Add removal date when created |
| No access controls | Anyone can toggle anything | Role-based access |
| Flags as config | Config changes shouldn't need flag system | Use config files/env for values |
| Killing flag leaves inconsistent data | Data depends on flag state | Migration before kill |
| Too many flags | Can't track what's active | Regular flag audits |

---

## Flag Audit Checklist

Every quarter:

- [ ] Remove flags that have been "fully shipped" for > 30 days
- [ ] Verify deprecated flags are actually off
- [ ] Check for orphaned flags (code removed but flag still exists)
- [ ] Review who has access to toggle each flag
- [ ] Verify kill switches still work

---

## Activation

Proceed with designing feature flags for: [describe the feature or system]
