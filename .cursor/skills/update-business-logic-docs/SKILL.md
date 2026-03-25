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
