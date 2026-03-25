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
