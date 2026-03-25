# Cursor Context & Skills Improvement — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Minimize always-injected context, ensure subagents receive Python standards, add coverage-testing and business-logic doc update skills.

**Architecture:** Cursor rules (`.mdc`) for always-present context, Cursor skills (`SKILL.md`) for on-demand workflows.

**Tech Stack:** Cursor rules, Cursor skills (markdown only — no code changes)

---

### Task 1: Slim `business-logic.mdc` and create `orchestration.mdc`

**Files:**
- Modify: `.cursor/rules/business-logic.mdc`
- Create: `.cursor/rules/orchestration.mdc`

- [ ] **Step 1: Replace `business-logic.mdc` content**

Replace the entire file with:

```markdown
---
description: Points to business logic documentation
alwaysApply: true
---

# Business Logic

Full domain spec (entities, enums, state machines, permissions, API routes): `docs/business-logic.md`

Read it when you need domain model details, validation rules, order lifecycle, or permission logic.
External integrations: Dadata (org data by INN).
```

- [ ] **Step 2: Create `orchestration.mdc`**

Create `.cursor/rules/orchestration.mdc`:

```markdown
---
description: Instructions for orchestrating subagents and workflows
alwaysApply: true
---

# Orchestration

## Python Subagents
When dispatching subagents for Python implementation, read `.cursor/rules/python-conventions.mdc` and include its full content in the subagent prompt.

## Business Logic Changes
When brainstorming introduces new entities, changes workflows, or modifies permissions:
1. After design is approved by user, before writing the implementation plan
2. Update `docs/business-logic.md` to reflect the target state
3. Dispatch a reviewer subagent to verify the doc changes
4. Ask user to review before proceeding to implementation plan
```

- [ ] **Step 3: Commit**

```bash
git add .cursor/rules/business-logic.mdc .cursor/rules/orchestration.mdc
git commit -m "refactor: slim business-logic rule, add orchestration rule"
```

---

### Task 2: Create `coverage-testing` skill

**Files:**
- Create: `.cursor/skills/coverage-testing/SKILL.md`

- [ ] **Step 1: Create skill file**

Create `.cursor/skills/coverage-testing/SKILL.md`:

```markdown
---
name: coverage-testing
description: Use when implementation is complete and you want to check test coverage for the modules you worked on, identify untested code paths, and decide whether additional tests are needed
---

# Coverage-Driven Testing

Run tests with coverage for specific modules, analyze gaps, and decide if additional tests are worth adding.

## When to Use

- After completing implementation of a feature
- When asked to check test coverage
- Before finishing a development branch

## Process

1. **Run coverage for target modules**

Identify which `app/` subpaths were modified, then run:

```bash
task test -- --cov=app/<path/to/modified/part> --cov-report=term-missing
```

Always omit `app/main.py` from analysis — it's the entrypoint, not business logic.

For multiple modules, combine `--cov` flags:

```bash
task test -- --cov=app/users --cov=app/organizations --cov-report=term-missing
```

2. **Parse the report**

Focus on the `Missing` column — these are untested line numbers. Note the `Cover%` per file for context.

3. **Read untested lines**

For each file with missing lines, read the file at those line ranges. Understand what the untested code actually does.

4. **Categorize each gap**

| Category | Action | Examples |
|----------|--------|----------|
| Error handling / business logic branches | Write test | Validation edge cases, permission checks, state transitions |
| Trivial / boilerplate | Skip | `__repr__`, simple property accessors, obvious delegation |
| Already covered by integration tests | Skip | Code exercised by higher-level test paths |

5. **Act on "worth testing" gaps**

Write focused unit or integration tests for gaps that matter. Each test should target a specific untested branch or error path.

6. **Report**

Summarize what was tested, what was skipped, and why. Example:

```
Coverage: app/users/services.py 72% → 89%
- Added: test for duplicate email error path (line 45-48)
- Added: test for password validation edge case (line 62-67)
- Skipped: __repr__ (line 12) — trivial
- Skipped: get_by_id happy path (line 30) — covered by integration tests
```

## Key Principle

Don't chase 100%. Test what matters. Explain skip decisions.
```

- [ ] **Step 2: Commit**

```bash
git add .cursor/skills/coverage-testing/SKILL.md
git commit -m "feat: add coverage-testing skill"
```

---

### Task 3: Create `update-business-logic-docs` skill

**Files:**
- Create: `.cursor/skills/update-business-logic-docs/SKILL.md`

- [ ] **Step 1: Create skill file**

Create `.cursor/skills/update-business-logic-docs/SKILL.md`:

```markdown
---
name: update-business-logic-docs
description: Use when a PR has been merged or is ready and docs/business-logic.md needs to reflect the changes introduced in that PR
---

# Update Business Logic Documentation

Update `docs/business-logic.md` to reflect changes introduced in a specific PR.

## When to Use

- User provides a PR number and asks to update business-logic docs
- After a PR lands that changed domain models, business rules, or API endpoints
- To reconcile docs when implementation diverged from the planned target state

This skill handles **post-PR** doc updates. Pre-implementation doc updates (during brainstorming) are handled by the orchestration rule in `.cursor/rules/orchestration.mdc`.

## Process

1. **Get PR context**

```bash
gh pr view <number>
gh pr diff <number>
```

2. **Analyze what domain concepts changed**

Map PR changes to doc sections:

| Change type | Doc section to update |
|-------------|----------------------|
| New/modified models | Data Model Reference (section 6) + entity-specific section |
| New/modified API endpoints | API Summary tables in the relevant section |
| Changed business rules | Business Rules subsections |
| New/modified enums | All Enums (section 6.2) |
| Changed state machine | Order State Machine (section 5.2) |
| New entity relationships | Entity Relationships (section 6.1) |

3. **Read current `docs/business-logic.md`**

4. **Apply targeted updates**

- Update only sections affected by the PR
- Preserve existing formatting, table structure, and section numbering
- Add new sections if the PR introduces entirely new entities
- Do not reorganize or reformat unrelated sections

5. **Self-review checklist**

- [ ] All PR changes are reflected in the doc
- [ ] No existing documentation was accidentally removed
- [ ] Internal consistency: new fields appear in both model tables and relevant API sections
- [ ] Enum values match what the code defines
- [ ] Section numbering is intact

6. **Commit**

```bash
git add docs/business-logic.md
git commit -m "docs: update business-logic.md for PR #<number>"
```

## Edge Cases

- **PR has no domain changes** (pure refactor, test-only, infra): report "No business-logic doc updates needed for PR #N" and stop.
- **PR is very large**: process section by section, committing after each major section update.
- **Ambiguous changes**: flag them and ask the user rather than guessing.
```

- [ ] **Step 2: Commit**

```bash
git add .cursor/skills/update-business-logic-docs/SKILL.md
git commit -m "feat: add update-business-logic-docs skill"
```
