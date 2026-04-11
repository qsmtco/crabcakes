# User Documentation Writer

Write user-facing documentation that is clear, accurate, and actually useful. Not what the code does — what the user needs to accomplish.

---

## Before You Write

1. Who is the reader? (technical skill level, role, goal)
2. What do they already know? (don't explain what they already know)
3. What task are they trying to complete?
4. What's the simplest way to explain this?

---

## Document Types

| Type | When | Length |
|------|------|--------|
| **Quickstart** | First time user | 5–10 steps |
| **How-to guide** | Accomplishing a specific task | Focused, 1 topic |
| **Reference** | Looking up facts | Dense, complete |
| **Explanation** | Understanding why something works | Conceptual |
| **Troubleshooting** | Fixing something broken | Problem → solution |

---

## Quickstart Template

```
# [Product] Quickstart

Get [outcome] in 5 minutes.

## Step 1: [Prerequisite]
[One clear action]

## Step 2: [Install / Sign up]
[Link or inline instruction]

## Step 3: [First action]
[Screenshot if helpful]

## Step 4: [Verify it worked]
[How to confirm]

## Next steps
- [Link to how-to for deeper feature]
- [Link to configuration]
```

**Rules:**
- One action per step
- No jargon
- No "simply" or "just" (nothing is simple to someone who doesn't know)
- Screenshot if it helps more than words

---

## How-To Guide Template

```
# How to: [Accomplish X]

Do [specific outcome] using [tool/method].

## Before you start
[Prerequisites, accounts needed, etc.]

## Steps

### 1. [First step]
[What to do and why]

### 2. [Second step]
...

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| [Error message] | [Why] | [How to fix] |

## Related
- [Link to related how-tos]
- [Link to reference docs]
```

---

## Writing Rules

### Clarity

**Good:** "Click File → Save As. Name the file `config.json`. Click Save."

**Bad:** "The file should be persisted using the appropriate save mechanism from the file menu."

### Numbering

- Steps = numbered list (1, 2, 3)
- Options = bullet list (- or *)
- Related links = bullet list

### Screenshots

- Use only when words aren't enough
- Include a caption explaining what's shown
- Don't screenshot things that are easy to describe
- Keep them current — an outdated screenshot is worse than none

### Tone

- Second person: "you" not "the user"
- Active voice: "Click Save" not "Save is initiated by the user"
- Present tense: "the app starts" not "the app will start"
- No condescension: "this is easy" is patronizing if it's not easy for them

---

## Review Checklist

- [ ] Can a new user follow this from start to finish without asking for help?
- [ ] Are all prerequisites listed?
- [ ] Are all terms defined or linked?
- [ ] Is every step actionable — does the user know exactly what to do?
- [ ] Are error states covered?
- [ ] Is it free of jargon or is jargon defined?
- [ ] Is it tested? (actually followed the steps myself)
- [ ] Is the formatting consistent throughout?

---

## What to Leave Out

- Implementation details (users don't care about your database)
- Options you don't recommend (confuses without helping)
- Historical context ("we built this feature in 2023...")
- Future plans ("coming soon...")
- Content that belongs in a different doc type

---

## Common Failure Modes

| Failure | Why it's bad | Fix |
|---------|--------------|-----|
| Writing for the wrong audience | Tech docs assume too much knowledge | Write for the actual user, not the developer |
| Outdated screenshots | Worse than no screenshot | Update or remove |
| Walls of text | Nobody reads them | Break into steps |
| Assuming success | "just click OK" hides failure cases | Show error states too |
| "It's intuitive" | Only to someone who already knows | Document it |

---

## Activation

Proceed with writing user documentation for: [describe the feature, product, or task]
