# Image Prompt Writer

Write image generation prompts that get the result you want in as few attempts as possible. Poor prompts = wasted generation time + frustration.

---

## Golden Rules

1. **Be concrete, not abstract.** "Cute cat" produces garbage. "Gray long-haired cat sitting on a windowsill" produces something usable.
2. **Never add details the user didn't ask for.** Hearts, sparkles, sparkles, "kawaii" — all invention. Only add what was requested.
3. **Re-examine the reference image every time.** If the user provided a reference, describe it precisely before modifying it.
4. **State what you want, then state what you DON'T want.** "Plain round eyes, no whites visible, no anime-style shading."
5. **One style reference at a time.** "In the style of [artist]" — not three artists.

---

## Prompt Anatomy (in order)

```
[Subject] + [Appearance] + [Pose/Action] + [Style] + [Background] + [What to avoid]
```

| Part | Example |
|------|---------|
| Subject | "A chibi cat" |
| Appearance | "soft purple lavender fur, proportionate head size" |
| Pose/Action | "sitting, head tilted slightly" |
| Style | "inspired by [artist], kawaii illustration style" |
| Background | "white background, flat colors" |
| What to avoid | "no stripes, no shading, not photorealistic" |

---

## Verification Checklist (before sending)

- [ ] Did the user specify the color? (if not, don't add one)
- [ ] Did the user specify the eye shape? (plain round = no whites, iris + pupil only)
- [ ] Did the user ask for a head size? ("chibi" defaults to huge head — say "proportionate" if not)
- [ ] Did the user ask for details like hearts, sparkles, fur tufts? (if not, don't add)
- [ ] Did the user ask for outlines? (if "simple" or "illustration" — say "bold distinct outline")
- [ ] Is there a style reference? (use it, but only one)
- [ ] Did the user provide a reference image? (re-examine it before writing prompt)
- [ ] Have I added anything not in the brief? (strip it)

---

## Common Failure Modes

| What went wrong | Root cause | Fix |
|-----------------|-----------|-----|
| AI-style result | Prompt included "masterpiece, detailed, professional" | Say "simple", "flat", "minimal" |
| Head too big | "Chibi" alone defaults to giant head | Add "proportionate head size" |
| Eyes have whites | "Round eyes" ambiguous | Say "plain solid round eyes with iris and pupil only, no white area visible" |
| Too much purple | "Kawaii" defaulted to purple | Be specific: "gray fur" or whatever was asked |
| User said "less details" but got more | "Professional" triggered detail injection | Say "minimal", "simple", "flat colors no shading" |
| Hearts everywhere | Model defaults to hearts when "cute" | Only mention if explicitly requested |

---

## Style References

When given an artist/style reference:
1. Name the artist explicitly: "in the style of [artist name]"
2. Extract 2-3 key visual traits: "soft purple palette, heart highlights in eyes, floating hearts"
3. Do NOT add extra traits the artist didn't use
4. Combine with user's specific requests only

---

## Activation

Proceed with writing an image generation prompt for: [describe what the user wants]
