# Prompt Refiner

Takes a vague, wrong, or poorly-structured prompt and iteratively improves it until the output is exactly what was asked for. Every iteration should be narrower than the last.

---

## When to Use

- User gives a vague instruction: "make it look better"
- First attempt failed
- The task has contradictory constraints
- The user keeps saying "not what I wanted"
- You don't know where to start

---

## Process

### Step 1: Clarify — Ask the Right Questions

Before writing anything, confirm the specifics. Do not guess.

Template:
> Before I write this, I need to confirm:
> 1. [X] — is it A, B, or C?
> 2. [Y] — should it do X or avoid X?
> 3. [Z] — do you mean [this interpretation] or [that one]?

### Step 2: State What Success Looks Like

Write one concrete sentence describing the exact expected output. No abstractions.

**Bad:** "A nice looking image of a cat"
**Good:** "A gray cat sitting, no visible stripes, plain round eyes with iris and pupil only, white background"

### Step 3: Write the Narrowest Possible Prompt

Start with the minimum viable prompt. Add elements only when confirmed.

```
Subject + exact appearance + style constraint + what to avoid
```

### Step 4: Identify What NOT to Include

Explicitly list things that were in prior attempts that caused problems.

### Step 5: Verify Before Sending

- [ ] Does this match the exact brief?
- [ ] Have I added anything not explicitly requested?
- [ ] Is there any ambiguity left?
- [ ] What assumption am I making that could be wrong?

### Step 6: On Failure — Diagnose First

When the user says "not what I wanted":

1. **Re-read** their feedback verbatim — what specifically is wrong?
2. **Don't change multiple things at once.** Change one thing per iteration.
3. **Ask if unsure** — "is the problem X or Y?" before guessing.

---

## Refinement Log

Keep a running log of what was tried and what failed:

```
Attempt 1: Added hearts in eyes → User said "ugly eyes"
Attempt 2: Changed to oval eyes → User said "still bad, no whites"
Attempt 3: Plain round solid iris + pupil, no white → User said "proportionate head" ✓
```

This prevents repeating failed approaches.

---

## Quick Refinement Templates

### Too vague → Specific
**User:** "make it look better"
**Refined:** "The head is too large. Make it proportionate to the body. The eyes should be simple solid circles with no internal detail."

### Too detailed → Minimal
**User:** (11 elements requested + 6 style requirements)
**Refined:** "I'll focus on [the 3 most important elements]. Tell me which of the rest are critical vs nice-to-have."

### Contradiction
**User:** "simple but detailed, minimalist but colorful, cute but not childish"
**Refined:** "Help me prioritize: simple OR detailed? minimalist OR colorful? Can you show me a reference for 'cute but not childish'?"

### Wrong medium/style
**User:** "make it look like an oil painting"
**Refined:** "Do you mean: realistic-style subject matter, OR actual oil painting texture and brush strokes?"

---

## Common Refinement Triggers

| Trigger phrase | What it means | Response |
|---------------|---------------|----------|
| "too AI-looking" | Over-detailed, perfect symmetry, plastic texture | Strip details, add "imperfect", "hand-drawn", "organic lines" |
| "not what I wanted" | Nothing specific | Ask: "What specifically is wrong? The color, shape, style, or something else?" |
| "make it simpler" | Too many elements | Remove one element, ask what's most important |
| "add more X" | Missing something | Add X only — don't add anything else |
| "change the eyes" | Specify how: shape? color? size? | Ask: "plain circles? oval? almond? larger?" |

---

## Activation

Proceed with refining a prompt for: [describe what the user initially asked for and what's gone wrong so far]
