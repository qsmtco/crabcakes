# Pull Request Review Checklist

Review PRs methodically. Don't skim. Don't rubber-stamp. Approving a PR means you're confident it's correct, tested, and maintainable.

---

## Before You Start

- [ ] Read the PR description fully
- [ ] Understand the problem it's trying to solve
- [ ] Check the ticket/issue it links to
- [ ] Know what "done" means for this PR

---

## Correctness

- [ ] Does the code do what the description says?
- [ ] Are edge cases handled? (empty input, null, first/last item, concurrent calls)
- [ ] Are errors handled explicitly, not swallowed?
- [ ] Are return values checked where they matter?
- [ ] Are there any obvious bugs: off-by-one, wrong variable, missing null check?
- [ ] Does it break any existing functionality?

---

## Security

- [ ] Any user input is validated and sanitized?
- [ ] Any SQL — ORM used correctly, no raw interpolation?
- [ ] Any secrets, API keys, tokens — do they come from env/config, not hardcoded?
- [ ] Any new auth checks — are they correct and in the right place?
- [ ] Any new endpoints — do they require proper authorization?
- [ ] Any file paths constructed from user input — is path traversal prevented?

---

## Testing

- [ ] Does the PR add or update tests?
- [ ] Are the tests testing behavior, not implementation?
- [ ] Are happy path AND sad path covered?
- [ ] Are the tests actually passing in CI?
- [ ] Is the test coverage meaningful (not just `assert True`)?
- [ ] If there's a bug fix — is there a regression test for that bug?

---

## Design

- [ ] Is the change at the right layer (not leaky abstractions)?
- [ ] Does it follow existing patterns in the codebase?
- [ ] Is it too clever? Can you understand it in 6 months?
- [ ] Is the interface/API clean and hard to misuse?
- [ ] If refactoring — is the behavior unchanged?

---

## Performance

- [ ] Any new queries in loops? (N+1 problem)
- [ ] Any large data structures held in memory that could be streamed?
- [ ] Any expensive operations on hot paths?

---

## Code Quality

- [ ] Are function/variable names descriptive?
- [ ] Is there dead code left behind?
- [ ] Are comments explaining why, not what?
- [ ] Are logs at the right level (no `console.log` in prod)?
- [ ] Is there excessive duplication?
- [ ] Any TODO comments that are actually bugs?

---

## UX / Product

- [ ] Does the change match the expected behavior from the ticket?
- [ ] If there's a UI change — does it look reasonable?
- [ ] Any error messages — are they helpful to the user?

---

## CI/CD

- [ ] Do CI checks pass?
- [ ] Any new environment variables needed?
- [ ] Any new dependencies — do they have acceptable licenses?

---

## What to Comment On

**Approve with suggestions:** Minor improvements, optional enhancements.

**Request changes:** Logic bugs, missing tests, security issues, unclear code.

**Comment (no approval/lgtm):** Questions, "nit" suggestions, style nits, "might want to consider later."

---

## Response Templates

**Approve:**
> Looks good. Tested [X, Y, Z]. Left a few nits inline, non-blocking.

**Request changes:**
> Needs changes before approval. Specifically:
> 1. [Bug] Line 47: the null check is missing — will panic if `user` is None
> 2. [Test] Missing test for the empty list case
> 3. [Security] API key is hardcoded at line 112

**Comment:**
> Nit: could use `dict.get()` here instead of the try/except.
> Non-blocking suggestion: consider moving this to a helper function for reuse.

---

## Activation

Proceed with reviewing the pull request at: [URL or describe the PR]
