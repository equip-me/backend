# Cursor Context & Skills Improvement — Design Spec

## Goal

Make project context minimal and targeted. Ensure dev subagents always receive Python coding standards. Add two new skills: coverage-driven testing and PR-based business-logic doc updates.

## Problem

1. `business-logic.mdc` is `alwaysApply: true` and duplicates ~40 lines from `docs/business-logic.md` — wastes context tokens and creates a sync problem.
2. `python-conventions.mdc` is glob-scoped (`**/*.py`) — subagents dispatched via Task tool don't have open files, so they never receive coding standards.
3. No process for updating `docs/business-logic.md` when brainstorming introduces domain changes — the doc drifts from reality.
4. No skill to update `docs/business-logic.md` after a PR lands.
5. No skill to run targeted coverage analysis and decide which untested spots deserve tests.

## Changes

### 1. Slim `business-logic.mdc`

**File:** `.cursor/rules/business-logic.mdc`

Replace 47-line duplicated summary with a minimal pointer.

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

**Rationale:** The full spec lives in `docs/business-logic.md` (636 lines). Duplicating a summary wastes context and drifts. A pointer costs ~5 lines and always stays accurate.

### 2. New `orchestration.mdc` (always-apply)

**File:** `.cursor/rules/orchestration.mdc`

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

**Rationale:** `python-conventions.mdc` stays glob-scoped (auto-attaches when `.py` files are open for direct work), but the orchestrator now also injects it into Task subagent prompts. Business-logic-first update ensures the doc is the source of truth before implementation begins.

### 3. New skill: `coverage-testing`

**File:** `.cursor/skills/coverage-testing/SKILL.md`

**Trigger:** After implementation is complete, or when user asks to check coverage.

**Process:**
1. Run coverage for modified modules: `task test -- --cov=app/<path/to/modified/part> --cov-report=term-missing` (always omit `app/main.py` from coverage analysis)
2. Parse the report — focus on `Missing` column (untested line numbers)
3. Read each file at the missing line ranges
4. Categorize each gap:
   - **Error handling / business logic branches** — worth testing
   - **Trivial/boilerplate** (`__repr__`, simple properties) — skip
   - **Already covered by integration tests** — skip
5. For "worth testing" gaps, write focused tests
6. Report what was skipped and why

**Key principle:** Don't chase 100%. Test what matters. Explain skip decisions.

### 4. New skill: `update-business-logic-docs`

**File:** `.cursor/skills/update-business-logic-docs/SKILL.md`

**Trigger:** User provides a PR number and asks to update business-logic docs.

**Relationship to orchestration rule (change #2):** The orchestration rule updates `docs/business-logic.md` *before* implementation (target state, during brainstorming). This skill updates it *after* a PR lands — for PRs that didn't go through the brainstorming workflow, or to reconcile if implementation diverged from the planned target state.

**Process:**
1. Get PR diff: `gh pr diff <number>` (or `gh pr view <number>` for summary)
2. Analyze what domain concepts changed:
   - New/modified models → Data Model sections
   - New/modified endpoints → API Summary tables
   - Changed business rules → Business Rules sections
   - New/modified enums → Enums section
   - Changed state machine → Order State Machine
3. Read current `docs/business-logic.md`
4. Apply targeted updates to affected sections only
5. Self-review: verify all PR changes reflected, no accidental deletions, internal consistency
6. Commit: `docs: update business-logic.md for PR #<number>`

### 5. `python-conventions.mdc` — no changes

Stays as-is. Glob-scoped `**/*.py`, content unchanged. Orchestration rule (change #2) handles subagent injection.

## Files Changed

| File | Action |
|------|--------|
| `.cursor/rules/business-logic.mdc` | Replace content (slim to pointer) |
| `.cursor/rules/orchestration.mdc` | Create new (always-apply) |
| `.cursor/skills/coverage-testing/SKILL.md` | Create new skill |
| `.cursor/skills/update-business-logic-docs/SKILL.md` | Create new skill |
| `.cursor/rules/python-conventions.mdc` | No change |
| `.cursor/rules/project.mdc` | No change |

## Out of Scope

- Changing the superpowers skills themselves (brainstorming, subagent-driven-development, etc.)
- Modifying `docs/business-logic.md` content
- CI enforcement rules (user decided agent knows better)
