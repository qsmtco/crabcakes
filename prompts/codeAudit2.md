You are a senior full-stack engineer conducting a thorough, adversarial code audit of the ManoPea tattoo booking SaaS project. Your goal is to find every real bug, security vulnerability, documentation inaccuracy, architectural problem, and edge case failure before it reaches production.

IMPORTANT: We are not in a race. Slow but 100% correct is better than fast but wrong. Be thorough, be methodical, be exhaustive.

Project location: /home/q/projects/manopea/

---

## PHASE 1: PROJECT MAPPING

Before writing a single line of code review, build a complete map of the project:

1. List every file in the project (excluding node_modules, .git, build artifacts)
2. Identify the tech stack fully: frontend framework, backend framework, database ORM, cache, queue, deployment stack
3. List all environment variables the project uses (search for process.env references)
4. Identify all API routes (both backend route files)
5. List all frontend pages
6. Identify all third-party integrations (Stripe, Twilio, SendGrid, Telegram, etc.)
7. Map the authentication/authorization system end-to-end

---

## PHASE 2: DOCUMENTATION AUDIT

For every document in docs/ and at the project root:

1. Read each document fully
2. Ask: does this document describe the current state of the code, or an older state?
3. Flag any document that:
   - Claims a feature is done when it isn't
   - Claims a feature isn't done when it is
   - Describes a file structure that no longer matches reality
   - References a file or path that no longer exists
   - Contains conflicting information with another document
4. Check every "Last Updated" date — flag stale documents
5. Check the OpenAPI spec for paths that don't match actual routes
6. Identify any documentation that is clearly superseded or redundant

---

## PHASE 3: SECURITY AUDIT

For every authentication and authorization point:

1. Trace the full auth flow: login → token generation → storage → transmission → validation
   - Are tokens in httpOnly cookies or localStorage?
   - Are cookies set with Secure, SameSite flags?
   - Is the JWT secret strong and properly environment-isolated?
2. Check every middleware that protects routes — does it correctly verify ownership?
3. For every endpoint that takes an ID parameter (userId, appointmentId, shopId, etc.):
   - Can one user access/modify another user's data by guessing IDs? (IDOR test)
   - Are there endpoints with no authorization check that should have one?
4. Check for sensitive data exposure:
   - Any endpoint that returns health information, PII, or internal IDs to unauthorized clients?
   - Any error messages that leak internal system information?
   - Any data stored in logs or console output that shouldn't be?
5. Check input validation:
   - Are all user inputs sanitized before database queries? (SQL injection)
   - Are file uploads validated? (path traversal, file type)
   - Are API rate-limited?
6. Check the Prisma schema for:
   - Missing unique constraints that could cause duplicate records
   - Missing required fields that could cause partial/invalid data
   - Cascade delete rules that could cause data loss

---

## PHASE 4: API DESIGN AUDIT

1. For every API route:
   - Does it return appropriate HTTP status codes? (201 for create, 404 for not found, 403 for forbidden, 400 for bad input)
   - Does it validate all required inputs before hitting the database?
   - Does it handle errors gracefully without leaking stack traces?
   - Does it return consistent JSON response shapes?
2. Check for consistency between similar endpoints (do they follow the same patterns?)
3. Check for API versioning — if v1 and v2 both exist, which is canonical? Are they both mounted?
4. Check webhook handlers — do they verify signatures? Are they idempotent?
5. Check for missing endpoints that should exist based on the feature set

---

## PHASE 5: FRONTEND AUDIT

1. For every API call from the frontend:
   - Does the TypeScript type match what the backend actually returns?
   - Are errors handled, or just console.logged and ignored?
- Is sensitive data displayed to unauthorized users?
2. Check the auth context:
   - How are tokens stored? Are they ever written to localStorage?
   - Is there protection against XSS?
   - Does the app handle token expiry gracefully?
3. Check form submissions:
   - Are required fields validated client-side AND server-side?
   - Are file uploads validated for type and size?
4. Check for hardcoded URLs, API keys, or secrets in frontend code
5. Check that all frontend pages have correct route guards (protected vs public)

---

## PHASE 6: DATA INTEGRITY AUDIT

1. For every database write operation:
   - Are transactions used where needed? (e.g., creating a user AND their profile)
   - Are foreign key relationships enforced correctly?
   - Could partial failures leave the database in an inconsistent state?
2. Check soft delete usage — is deleted data handled consistently?
3. Check for race conditions:
   - Concurrent appointment bookings for the same slot
   - Duplicate user registration
   - Double-submit on forms
4. Check date/time handling:
   - Timezone consistency between frontend and backend
   - Date parsing that could be exploited (e.g., "2025-02-30" parsing as "2025-03-02")

---

## PHASE 7: ERROR HANDLING AUDIT

1. For every try/catch block:
   - Is the error actually handled, or just swallowed?
   - Is the error logged server-side for debugging?
   - Does the client get a useful error message?
2. Check for unhandled promise rejections
3. Check for uncaught exceptions at the Express level
4. Check for missing 404 handlers — does the API return a proper 404 or a 500?
5. Check the payment/error flows — when Stripe/Twilio/etc. fail, is the error handled gracefully?

---

## PHASE 8: DEPENDENCY AUDIT

1. List all npm packages used and their versions
2. Check for known CVEs in any dependency
3. Check for packages that are no longer maintained but still used
4. Check for duplicate packages (different versions of the same package)
5. Check for unused packages (installed but never imported)
6. Check that all environment variables used by dependencies are documented

---

## PHASE 9: ARCHITECTURE CONSISTENCY AUDIT

1. Are all controllers using the same error handling pattern?
2. Are all services using the same Prisma query patterns?
3. Are there duplicated logic across files that should be extracted?
4. Are there dead code paths (code that can never be executed)?
5. Check for magic numbers or strings that should be constants
6. Check naming consistency across the codebase
7. Check that TypeScript strictness is applied consistently

---

## OUTPUT FORMAT

Produce a structured report with:

### CRITICAL (Fix Immediately)
- [ ] Each issue with: file, line number, description, proof, recommended fix

### HIGH (Fix Before Production)
- [ ] Same format

### MEDIUM (Fix Soon)
- [ ] Same format

### DOCUMENTATION INACCURACIES
- [ ] For each: document name, what it says, what reality is, severity of misinformation

### ARCHITECTURAL DEBT
- [ ] Patterns that are inconsistent, duplicated logic, dead code

### LOW PRIORITY / NICE TO HAVE
- [ ] Minor issues

For each issue, include:
- Exact file path and line number
- The problematic code (actual snippet)
- Why it's a problem
- A concrete recommended fix

Be adversarial. Assume the previous developer made mistakes. The goal is to find problems, not confirm that things are working fine.

