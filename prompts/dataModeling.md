# Data Modeling

Design data models that are correct, scalable, and easy to query. Bad data models are expensive to fix later.

---

## Before You Model

1. What entities exist in this domain?
2. What are the relationships between entities?
3. What are the access patterns? (how will data be read — determines the schema)
4. What are the write patterns? (how will data be created/updated)
5. What are the consistency requirements? (strong vs eventual consistency)

---

## Entity-Relationship Basics

| Relationship | Example | In SQL | In NoSQL |
|-------------|---------|--------|----------|
| One-to-one | User → Profile | Same table or FK | Nested document |
| One-to-many | User → Orders | FK in Orders | Array of order IDs |
| Many-to-many | Students ↔ Courses | Join table | Array of refs both sides |
| Hierarchical | Category → Subcategory | Adjacency list or nested set | Nested documents |

---

## SQL Schema Checklist

For each table:

- [ ] Primary key — UUID (for distributed) or bigint (for single-node)
- [ ] All foreign keys have `ON DELETE` and `ON UPDATE` behavior specified
- [ ] Timestamps: `created_at TIMESTAMPTZ DEFAULT NOW()`, `updated_at TIMESTAMPTZ`
- [ ] Unique constraints where needed (email, username, etc.)
- [ ] Indexes on columns used in WHERE and JOIN clauses
- [ ] Data types: `TIMESTAMPTZ` not `DATE`, `DECIMAL` not `FLOAT`, `TEXT` not `VARCHAR(n)`
- [ ] Check constraints for valid ranges

---

## PostgreSQL Data Type Guide

| Data | Use | Don't use |
|------|-----|-----------|
| Unique ID | `UUID DEFAULT gen_random_uuid()` | `SERIAL` (not global) |
| Money | `DECIMAL(19,4)` | `FLOAT`, `DOUBLE` |
| Timestamps | `TIMESTAMPTZ` (always with timezone) | `DATE`, `TIME`, `TIMESTAMP` |
| Variable text | `TEXT` | `VARCHAR(n)` unless enforcing a hard limit |
| JSON | `JSONB` (indexable) | `JSON` (text) |
| Boolean | `BOOLEAN` | `TINYINT`, `INT` |
| Enum | `ENUM` type | `VARCHAR` with CHECK |

---

## NoSQL / Document Model Checklist

| Decision | Questions to answer |
|----------|--------------------|
| To embed or reference? | Will the nested data be queried on its own? |
| How to handle many-to-many? | Use an array of IDs in one or both documents |
| Denormalization | Is it worth the write complexity for read performance? |
| Schema validation | Are there tools to enforce schema (e.g., Zod, JSON Schema)? |

---

## Indexing Strategy

| Access pattern | Index type |
|---------------|-----------|
| Exact match | `CREATE INDEX ON users (email)` |
| Range query | `CREATE INDEX ON orders (created_at)` |
| Text search | Full-text index: `GIN USING GIN (to_tsvector('english', content))` |
| Sorted results | Composite index: `(status, created_at DESC)` |
| JSON field | GIN index on JSONB: `CREATE INDEX ON products USING GIN (data)` |

**Rules:**
- Index on foreign keys (JOIN columns) first
- Index on columns used in WHERE clauses
- `EXPLAIN ANALYZE` before and after adding an index
- Too many indexes slow down writes

---

## Soft Deletes vs Hard Deletes

| Pattern | When to use | How |
|---------|-------------|-----|
| **Soft delete** (`deleted_at`) | Data must be recoverable, audit trail | `UPDATE SET deleted_at = NOW() WHERE id = X` |
| **Hard delete** | Data is truly temporary, GDPR, privacy | `DELETE FROM users WHERE id = X` |

**Soft delete checklist:**
- [ ] Filter `WHERE deleted_at IS NULL` in every query (or use a view)
- [ ] Unique constraints handle soft-deleted rows (use partial unique indexes)
- [ ] Cascading deletes handled (or the parent row can't be deleted)

---

## Migration Checklist

| Stage | What to do |
|-------|-----------|
| **Before** | Write the rollback — if you can't roll back, don't migrate |
| **Stage 1** | Add new column as nullable (backward compatible) |
| **Stage 2** | Deploy code that writes to both old and new column |
| **Stage 3** | Backfill new column with data from old column |
| **Stage 4** | Make new column NOT NULL |
| **Stage 5** | Remove old column in next release |

---

## Data Model Document Template

```markdown
# Data Model: [System]

## Entities

### User
| Column | Type | Constraints | Notes |
|-------|------|-------------|-------|
| id | UUID | PK | |
| email | TEXT | UNIQUE, NOT NULL | |
| created_at | TIMESTAMPTZ | NOT NULL | |
| deleted_at | TIMESTAMPTZ | NULL | Soft delete |

**Indexes:**
- `users_email_idx` ON (email) — for login lookups
- `users_deleted_at_idx` ON (deleted_at) WHERE deleted_at IS NULL

**Access patterns:**
- Find user by email
- List active users paginated

---

## Relationships

- User 1:N Orders (via `orders.user_id`)
- Order N:M Products (via `order_items` join table)

---

## Constraints

- Email is unique among non-deleted users
- Orders cannot exist for deleted users (cascade delete)
```

---

## Common Failure Modes

| Failure | Why it's bad | Fix |
|---------|--------------|-----|
| Using UUID v1 (MAC + timestamp) | UUIDs expose server location | Use UUID v4 (random) |
| No foreign keys in NoSQL | Data becomes orphaned | Application-level enforcement |
| Over-indexing | Writes slow down | Index only what you query |
| EAV (Entity-Attribute-Value) pattern | Terrible query performance | Proper columns or JSONB |
| Premature normalization | Joins everywhere | Denormalize for read performance |
| No soft delete strategy | Can't recover from mistakes | Add `deleted_at` early |

---

## When to Denormalize

| Signal | Consider denormalizing |
|--------|----------------------|
| Same join in every query | Add `author_name` to `posts` table |
| N+1 query problem | Batch fetch or embed |
| Hot read path | Cache or embed computed values |
| Hierarchical data queried flat | Nested documents or materialized path |

---

## Activation

Proceed with designing a data model for: [describe the system or domain]
