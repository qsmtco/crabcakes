# Accessibility Audit

Audit a UI for accessibility (a11y) — screen readers, keyboard navigation, color contrast, and more. ~15% of people have a disability. An inaccessible product excludes them.

---

## Standards

| Standard | What it covers |
|----------|---------------|
| **WCAG 2.1 AA** | Minimum standard for most products |
| **WCAG 2.2 AA** | Current standard (adds 9 criteria to 2.1) |
| **Section 508** | US federal compliance |
| **ADA** | US civil rights law for digital |

For most products: **WCAG 2.1 AA** is the target.

---

## Quick Audit (10 minutes)

Start here before a deep audit:

- [ ] Can you tab through the entire page with just a keyboard?
- [ ] Do all images have alt text?
- [ ] Can you identify all form labels?
- [ ] Is the text readable without a screen reader (no color-only indicators)?
- [ ] Run `axe` browser extension — how many violations?

---

## Keyboard Navigation Audit

Every interactive element must be keyboard-accessible:

| Test | Pass criteria |
|------|--------------|
| Tab order | Logical, top-to-bottom, left-to-right |
| Focus visible | Bright outline (not `outline: none`) on focusable elements |
| Skip links | "Skip to main content" link at top of page |
| Escape key | Closes modals, dropdowns, tooltips |
| Arrow keys | Navigate within menus, tabs, sliders |
| Enter/Space | Activate buttons, checkboxes, links |
| No keyboard traps | Tabbing through never gets stuck |

**Test:** Unplug your mouse. Use only Tab, Shift+Tab, Enter, Space, Arrow keys.

---

## Screen Reader Audit

| Element | What to check |
|---------|---------------|
| Images | `alt` text — describes content, not "image of X" |
| Buttons | Read as buttons, not as links or generic text |
| Form fields | Label associated with input (`<label for>` or `aria-label`) |
| Headings | Logical hierarchy (h1 → h2 → h3, not skipped) |
| Modals | Focus trapped inside, `aria-modal="true"`, announced on open |
| Dynamic content | `aria-live` region announces updates without page reload |
| Empty buttons | `aria-label` provides context |

**Test:** Use NVDA (Windows), VoiceOver (Mac), or TalkBack (Android).

---

## Color Contrast Audit

| Element | Minimum ratio (AA) | Minimum ratio (AAA) |
|---------|-------------------|-------------------|
| Normal text | 4.5:1 | 7:1 |
| Large text (18pt+) | 3:1 | 4.5:1 |
| UI components (buttons, inputs) | 3:1 | N/A |

**Tools:** `axe` browser extension, WebAIM contrast checker, Figma contrast plugin.

---

## Color-Only Information

**Fail:** "Red text indicates an error" — someone who can't see red gets no information.

**Pass:** Error text includes the word "Error" or an icon with `aria-label="Error"`.

---

## Forms Audit

| Check | How |
|-------|-----|
| Labels | Every input has a visible label |
| Autocomplete | `autocomplete="email"` for email, `autocomplete="tel"` for phone |
| Error messages | Inline, associated with field via `aria-describedby` |
| Required fields | `aria-required="true"` AND visible indicator |
| Focus | Error field receives focus on submission error |

---

## Motion and Animation

| Check | Standard |
|-------|----------|
| Respects `prefers-reduced-motion` | WCAG 2.3.1 |
| No flashing content > 3 times/second | WCAG 2.3.1 |

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
  }
}
```

---

## Audit Report Template

```markdown
# Accessibility Audit: [Page/System]

**Auditor:** [Name]
**Date:** YYYY-MM-DD
**Standard:** WCAG 2.1 AA

## Summary
[Overall assessment: how many violations, severity]

## Violations

| # | WCAG criterion | Element | Issue | Severity | Fix |
|---|---------------|---------|-------|----------|-----|
| 1 | 1.1.1 Non-text content | img.logo | Missing alt text | Critical | Add `alt="Acme Corp logo"` |

## Severity

- **Critical:** Screen reader cannot access content
- **Serious:** Key functionality unusable
- **Moderate:** Significant barriers to access
- **Minor:** Inconveniences but not blockers

## Keyboard Issues
[Specific failures and fixes]

## Screen Reader Issues
[Specific failures and fixes]

## Color Contrast Issues
[Specific failures and fixes]

## Passing Tests
[List what passed well]
```

---

## Common Violations

| Violation | WCAG | Fix |
|-----------|------|-----|
| Missing alt text | 1.1.1 | Add `alt` to all `<img>` |
| Empty link text | 2.4.4 | `aria-label` for icon-only links |
| Missing form labels | 1.3.1 | Associate `<label>` with `<input>` |
| Focus not visible | 2.4.7 | Add `focus-visible` outline style |
| Missing heading hierarchy | 1.3.1 | Fix h1→h2→h3 sequence |
| Modal not focus-trapped | 2.1.2 | Trap focus, return on close |
| No skip link | 2.4.1 | Add "Skip to main content" link |

---

## Tools

| Tool | What it does |
|------|-------------|
| axe browser extension | Automated violation scanning |
| WAVE browser extension | Visual a11y feedback |
| Lighthouse (Chrome DevTools) | Basic a11y report |
| NVDA (Windows) | Free screen reader |
| VoiceOver (Mac) | Built-in screen reader |
| Colour Contrast Analyser | Check contrast ratios |

---

## Activation

Proceed with an accessibility audit of: [describe the page or system]
