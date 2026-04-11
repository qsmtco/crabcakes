# SQL Writer

Write SQL queries, schemas, and migrations that are correct, performant, and hard to misuse.

---

## Before You Write Anything

1. What database? (PostgreSQL, MySQL, SQLite, etc.)
2. Are there existing tables to reference or join against?
3. What does "done" look like? (specific output shape or side effect)
4. Is this a one-off query or production code? (production needs transactions, error handling)

---

## Query Checklist

For every query you write:

- [ ] Does this assume any implicit type coercion? (string vs number)
- [ ] Are all JOINs explicit? (no implicit cross-join)
- [ ] Are all columns named explicitly? (no `SELECT *` in production)
- [ ] Is there a `LIMIT` or `WHERE` to prevent runaway result sets?
- [ ] Are all filters on indexed columns (or is the absence intentional)?
- [ ] Is pagination handled correctly? (OFFSET vs cursor — OFFSET is wrong for large tables)
- [ ] Are NULLs handled correctly? (NULL !== NULL, use IS NULL not = NULL)

---

## Query Anatomy

```sql
SELECT
    u.id,
    u.email,
    u.created_at
FROM users u
WHERE u.active = true
  AND u.created_at >= '2024-01-01'
ORDER BY u.created_at DESC
LIMIT 100;
```

- Explicit column names, never `*`
- Table aliases that mean something (`u` = users)
- Date literals quoted correctly for the DB
- Uppercase keywords (readability standard)
- Comments for non-obvious decisions

---

## Schema Design Checklist

For CREATE TABLE:

- [ ] Primary key defined? (use `GENERATED ALWAYS AS IDENTITY` for auto-increment, not sequences)
- [ ] All foreign keys have `ON DELETE` / `ON UPDATE` behavior?
- [ ] Unique constraints where needed?
- [ ] Indexes on columns used in WHERE, JOIN, ORDER BY?
- [ ] `created_at DEFAULT NOW()` and `updated_at` with trigger or application-level update?
- [ ] Appropriate data types: `TIMESTAMPTZ` not `DATE` for timestamps, `DECIMAL` not `FLOAT` for money?
- [ ] `CHECK` constraints for valid ranges?
- [ ] Partitioning strategy if table > 100M rows?

---

## Migration Checklist

For every schema migration:

1. **Always write the rollback first.** If you can't roll back, you don't ship it.
2. **Backward compatible?** The app needs to work with both old and new schema during deployment.
3. **Destructive changes** (DROP COLUMN, DROP TABLE) — always `ALTER` → `DELETE old data` → `DROP` in separate deploys.
4. **Locks:** Will this table lock block reads or writes? Use `CONCURRENTLY` for index creation on large tables.

```sql
-- Good migration pattern
BEGIN;

ALTER TABLE users ADD COLUMN last_login_at TIMESTAMPTZ;

-- Backward compatible: app still works without this column

COMMIT;

-- Later, separate migration to backfill:
UPDATE users SET last_login_at = created_at WHERE last_login_at IS NULL;
```

---

## Common Failure Modes

| Failure | Fix |
|---------|-----|
| `SELECT *` in production | Name columns explicitly |
| `OFFSET 100000` on large table | Use cursor-based pagination |
| `NULL = NULL` returning no rows | `WHERE col IS NULL` not `= NULL` |
| No index on foreign key | `CREATE INDEX CONCURRENTLY` |
| Long-running migration locking table | Use `CONCURRENTLY`, split into smaller steps |
| Losing data on rollback | Test rollback on staging first |

---

## Performance Rules

1. **EXPLAIN ANALYZE before and after.** Never guess.
2. **Avoid JOINs on large tables in loops** — use a single query with IN or a temp table.
3. **Don't use `LIKE '%pattern%'` on large columns** — use a GIN index or full-text search.
4. **Batch inserts** — `INSERT INTO ... VALUES (...), (...), (...)` is far faster than individual inserts.

---

## Activation

Proceed with writing SQL for: [describe what you need]
