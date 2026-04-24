# Prompt Library — Fresh Collective

Reusable Claude Code prompt templates for future build sessions. Copy, adapt, and use these to keep sessions short and consistent. The docs hold the context — you do not need to re-explain the brief each time.

---

## 1. Starting a New Session

Use this at the beginning of any build session to orient Claude.

```
Read CLAUDE.md and docs/[relevant-doc].md before we begin.

We are currently on Phase [N] of the roadmap. Today's task is: [one sentence description].

Do not build anything outside this phase. Ask before installing any new packages.
```

**Which doc to cite per phase:**

| Phase | Docs to read |
|---|---|
| 1 — Framework setup | `docs/roadmap.md` |
| 2 — Public site | `docs/platform-structure.md`, `docs/design-principles.md` |
| 3 — Member area | `docs/platform-structure.md`, `docs/product-brief.md` |
| 4 — REAL Journey | `docs/platform-structure.md`, `docs/product-brief.md` |
| 5 — The Heart | `docs/platform-structure.md`, `docs/product-brief.md` |
| 6 — The Rooms | `docs/platform-structure.md`, `docs/product-brief.md` |
| 7 — Community | `docs/platform-structure.md` |
| 8 — Payments | `docs/platform-structure.md`, `docs/roadmap.md` |

---

## 2. Planning a Feature

Use before building something new to get an implementation plan without touching code yet.

```
Read CLAUDE.md and docs/platform-structure.md.

I want to plan the [feature name] feature. Do not write any code yet.

Tell me:
1. Which files you will create or edit
2. What each file will contain
3. Any dependencies or decisions to make first
4. Any risks or things to clarify before building

Wait for my approval before starting.
```

---

## 3. Building a Feature

Use when you are ready to build and have already planned.

```
Read CLAUDE.md and docs/platform-structure.md.

Build the [feature name] for the [page/section].

Requirements:
- [List key requirements from the platform-structure doc]
- Mobile responsive
- Matches the design principles in docs/design-principles.md
- No overbuilding — keep it scoped to what is listed

After building:
- Run npm run type-check
- Tell me what files were changed
- Tell me what I should test manually
```

---

## 4. Improving Visual Design

Use when a page or component exists but needs design refinement.

```
Read docs/design-principles.md before starting.

Review [page or component name] against the design principles.

Look for:
- Spacing that feels cramped or ungenerous
- Typography hierarchy issues
- Colour or contrast problems
- Anything that feels cluttered, cold, or overwhelming
- Mobile layout issues

Fix what you find. Do not change functionality, only visual presentation.
After changes, tell me what you changed and why.
```

---

## 5. Fixing Errors

Use when there is a bug, type error, or broken behaviour.

```
There is an error in [file or feature name].

Error message:
[paste error here]

Steps to reproduce:
[describe what you did]

Do not introduce new features while fixing this. Fix only the described error.
Run npm run type-check after fixing and confirm it passes.
```

---

## 6. Committing Changes

Use when a feature or fix is complete and ready to commit.

```
The following work is complete and ready to commit:
[brief description of what was built or fixed]

Please:
1. Run git status and git diff to confirm what has changed
2. Stage the relevant files (not unrelated files)
3. Write a clear, concise commit message
4. Create the commit

Do not push to remote unless I ask.
```

---

## 7. Summarising Progress

Use at the end of a session or to catch up at the start of a new one.

```
Read CLAUDE.md and docs/roadmap.md.

Summarise where the project is right now:
1. Which phase are we on?
2. What has been built so far?
3. What was the last thing completed?
4. What is the logical next step?

Keep the summary brief — three to five bullet points.
```

---

## 8. Reviewing for Overbuilding

Use before or after a feature build to check scope creep.

```
Review [feature name or file name] against the v1 scope in docs/product-brief.md.

Check:
- Is anything here not in the v1 priorities list?
- Is anything here explicitly in the "Do not build in v1" list?
- Is there any complexity that is not needed for the current phase?
- Are there any abstractions added speculatively for future features?

Report what you find. Do not make changes yet — just report.
```

---

## Usage Notes

- Always cite the relevant doc by filename — do not paste the brief into the prompt.
- Keep prompts short and specific. The docs do the heavy lifting.
- One task per session where possible. Focused sessions produce better results.
- If Claude produces something that does not match the brand feel, reference `docs/design-principles.md` explicitly in a follow-up.
