# Changelog Writer

Maintain a changelog that is actually useful — written for users, not for developers.

---

## Golden Rules

1. **User-facing language.** Write for users, not for developers.
2. **Group by significance.** Not every release is equally important.
3. **Link to docs.** When a change needs explanation, link to it.
4. **Consistent format.** Same structure every entry.
5. **No breaking changes without notice.** Users need migration time.

---

## Changelog Categories

Use consistently:

| Category | What goes here |
|----------|----------------|
| **Added** | New features |
| **Changed** | Changes to existing functionality |
| **Deprecated** | Things that will be removed in a future release |
| **Removed** | Features removed this release |
| **Fixed** | Bug fixes |
| **Security** | Security improvements or patches |
| **Breaking** | Any change that requires users to act |

---

## Entry Format

```markdown
## [Version] — YYYY-MM-DD

### Added
- Dark mode is now available in Settings → Appearance
- New API endpoint: `POST /v2/users/search` for advanced user lookup

### Changed
- CSV export now includes all 50 fields instead of 20
- Login page redirect is 50% faster

### Deprecated
- `GET /v1/users` will be removed in v3.0. Use `GET /v2/users` instead.

### Fixed
- Email notifications no longer fire twice when BCC is used
- CSV download no longer times out for exports over 10,000 rows

### Security
- Updated authentication token expiry from 24h to 1h
- Bumped `lodash` dependency to patch CVE-2024-XXXX

### Breaking
- `name` field is now `first_name` and `last_name` (separate fields)
  Migration: split your `name` value on first space to extract fields
```

---

## What to Include

| Include | Don't include |
|---------|--------------|
| Features users care about | Internal refactors |
| Bug fixes users notice | "Fixed a typo in comments" |
| Breaking changes that require action | Code style changes |
| Performance improvements users feel | Dependency version bumps (unless security) |
| Deprecations with timeline | Git commit hashes |
| Security patches | PR numbers |

---

## Version Naming

- **Major** (v2.0.0): Breaking changes — users must act
- **Minor** (v2.1.0): New features, backward compatible
- **Patch** (v2.1.1): Bug fixes, backward compatible

---

## Semantic Versioning Rules

| Change | Version bump |
|--------|-------------|
| Add new feature | Minor (+0.1.0) |
| Deprecate feature | Minor (+0.1.0) |
| Remove feature | Major (+1.0.0) |
| Fix bug | Patch (+0.0.1) |
| Change how an API works | Major (+1.0.0) |
| Add to API | Minor (additive) |
| Fix security vulnerability | Patch (or Major if severe) |

---

## Breaking Change Rules

Every breaking change needs:
1. **What changed** — exactly what the user will notice
2. **Why it changed** — brief rationale
3. **How to migrate** — concrete steps
4. **How long they have** — deprecation timeline

```markdown
### Breaking: `api_key` parameter renamed to `api_key_id`

The `api_key` parameter has been renamed to `api_key_id` for clarity.

Migration:
1. Find all uses of `api_key=<your_key>`
2. Replace with `api_key_id=<your_key>`

This change takes effect in v3.0. The old parameter will work until
2024-06-01, then return a deprecation warning.
```

---

## Release Checklist

- [ ] Every significant change since last release is documented
- [ ] Entries are categorized correctly
- [ ] Breaking changes have migration instructions
- [ ] Deprecations mention removal date
- [ ] Version number follows semver
- [ ] Date is correct
- [ ] Links work

---

## Common Failure Modes

| Failure | Why it's bad | Fix |
|---------|--------------|-----|
| "Fixed bugs" | Users don't know what was fixed | Name the specific bug |
| Including internal changes | Changelog becomes noise | Only user-visible changes |
| No migration guide for breaking changes | Users break | Write it before merging |
| Inconsistent format | Changelog is hard to scan | Use the template every time |

---

## Activation

Proceed with writing a changelog for: [describe the release or feature set]
