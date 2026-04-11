# Load Testing

Test a system's behavior under realistic and stress conditions. Find the breaking point before users do.

---

## Before You Test

1. What are you testing? (API endpoint, full system, database)
2. What does "success" look like? (specific latency, error rate, throughput)
3. What is the expected load? (users, requests/second, concurrent connections)
4. What are the failure thresholds? (at what point does it break badly)
5. What tools do you have? (k6, Locust, Gatling, wrk, ab)

---

## Common Load Testing Tools

| Tool | When to use | Language |
|------|-------------|----------|
| **k6** | Best DX, good metrics, scriptable | JavaScript |
| **Locust** | Python scripts, distributed | Python |
| **Gatling** | Complex scenarios, good reports | Scala |
| **wrk** | Quick one-liner benchmarks | LuaJIT scripts |
| **ab** | Apache Benchmark — quick and dirty | None (CLI) |
| **hey** | Simpler than ab, HTTP/2 | Go |

**Recommendation:** k6 for most use cases.

---

## Test Types

| Type | What it does | Duration |
|------|-------------|----------|
| **Smoke test** | Light load, verify it works at all | 1–5 min |
| **Load test** | Expected normal load | 15–60 min |
| **Stress test** | Gradually increase past normal to find breaking point | Until failure |
| **Soak test** | Sustained normal load — find memory leaks | 4–8+ hours |
| **Spike test** | Sudden burst — how does it recover? | 10–30 min |
| **Scalability test** | Does it scale linearly with resources? | Variable |

---

## k6 Script Template

```javascript
// load-test.js
import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  // Gradual ramp up to find breaking point
  stages: [
    { duration: '2m', target: 100 },   // ramp to 100 users
    { duration: '5m', target: 100 },   // hold at 100
    { duration: '2m', target: 200 },   // ramp to 200
    { duration: '5m', target: 200 },   // hold at 200
    { duration: '2m', target: 0 },     // ramp down
  ],
  thresholds: {
    http_req_duration: ['p(95)<500'],    // 95% under 500ms
    http_req_failed: ['rate<0.01'],       // < 1% error rate
  },
};

const BASE_URL = __ENV.BASE_URL || 'https://api.example.com';

export default function () {
  // Home page
  const homeRes = http.get(`${BASE_URL}/`);
  check(homeRes, { 'homepage loaded': (r) => r.status === 200 });

  // API endpoint
  const apiRes = http.get(`${BASE_URL}/api/v1/users`);
  check(apiRes, {
    'api returned 200': (r) => r.status === 200,
    'response time < 300ms': (r) => r.timings.duration < 300,
  });

  sleep(1);
}
```

---

## Key Metrics

| Metric | What it measures | What "good" looks like |
|--------|-----------------|----------------------|
| `http_req_duration` p50 | Median latency | < 100ms for APIs |
| `http_req_duration` p95 | 95th percentile | < 500ms |
| `http_req_duration` p99 | 99th percentile | < 1s |
| `http_req_failed` | Error rate | < 1% |
| `vus` | Virtual users | Scales with target |
| `iteration_duration` | Time per user loop | Consistent |

---

## Test Checklist

### Before the test

- [ ] Test environment mirrors production (or close enough)
- [ ] Database is populated with realistic data (not empty)
- [ ] Monitoring in place (CPU, memory, disk, network)
- [ ] Baseline metrics captured (before load)
- [ ] Test data is independent per VU (not sharing login credentials)
- [ ] Ramp-up is gradual, not instant

### During the test

- [ ] Monitor error rates — don't ignore errors
- [ ] Watch memory — does it grow unbounded?
- [ ] Watch CPU — is it CPU-bound or I/O-bound?
- [ ] Watch connection pools — are they exhausted?
- [ ] Check for dropped requests — 500 errors vs timeouts

### After the test

- [ ] Confirm system returned to normal (not still degraded)
- [ ] Compare to baseline metrics
- [ ] Identify bottleneck (CPU, memory, database, network)
- [ ] Document findings and recommendations

---

## Common Bottlenecks

| Bottleneck | Symptoms | Fix |
|-----------|----------|-----|
| CPU-bound | 100% CPU, throughput flat | Optimize queries, scale horizontally |
| Memory leak | Memory grows indefinitely | Profile, fix leak |
| Connection pool exhaustion | Latency spikes to timeout | Increase pool size, fix connection leak |
| Database lock contention | Queries queue up | Optimize indexes, reduce lock scope |
| Disk I/O | High iowait | Use SSDs, reduce disk writes |
| External API rate limit | 429 errors spike | Add backoff, stay under limit |

---

## Stress Test Specifics

Run until the system breaks — find the limit:

1. Start at 50% of expected load
2. Increase by 20% every 5 minutes
3. Watch for: increasing latency, increasing errors, resource exhaustion
4. Note: **the breaking point + the failure mode**
5. Confirm the system recovers when load returns to normal

---

## Results Template

```markdown
# Load Test Results: [System]

**Date:** YYYY-MM-DD
**Tool:** k6 / Locust / etc.
**Duration:** X hours Y minutes

## Configuration
- Virtual users: X
- Test environment: [staging / prod-mirrored]
- Test data: [X records]

## Results Summary

| Metric | Value | Threshold | Pass/Fail |
|--------|-------|-----------|-----------|
| p95 latency | 320ms | < 500ms | ✅ Pass |
| Error rate | 0.3% | < 1% | ✅ Pass |
| Max VUs | 200 | — | — |

## Breaking Point
- **Broke at:** ~250 concurrent users
- **Failure mode:** Database connection pool exhausted
- **Recovery:** Auto-scaled at 300 users, latency returned to normal

## Recommendations
1. Increase database pool from 50 to 150
2. Add read replica for SELECT queries
3. Implement circuit breaker for external API calls
```

---

## Common Failure Modes

| Failure | Why it's bad | Fix |
|---------|--------------|-----|
| Testing on empty database | Query plans different with real data | Seed realistic data |
| Same credentials for all VUs | Rate limits hit immediately | Per-VU credentials |
| No baseline comparison | Can't measure impact | Capture before metrics |
| Instant ramp-up | Not realistic | Gradual stages |
| Ignoring errors | Failure is a symptom | Treat errors as first-class metrics |

---

## Activation

Proceed with load testing for: [describe the system, endpoints, or expected load]
