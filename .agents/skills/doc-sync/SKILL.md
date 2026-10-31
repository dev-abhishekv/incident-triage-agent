---
name: doc-sync
description: Automated documentation and README synchronization workflow. Activates whenever a milestone, component, or architectural change is completed to keep README.md, docs/, and code comments in lockstep with the actual codebase.
---

# Documentation & README Synchronization Workflow

This skill ensures documentation never drifts from code reality.

## Triggers
Run this workflow whenever:
1. A weekly milestone or major task is completed (e.g., Week 1 Substrate, Week 2 Baseline).
2. Contracts (`triage/contracts.py`) or database schemas (`ops/schemas/*.sql`) are modified.
3. A new tool, strategy, or fault injector is added.

## Execution Checklist

### 1. Update `README.md`
- [ ] Check the **Phased Build Roadmap** table in `README.md`. Update status (`🟡 In Progress` -> `✅ Complete` -> `🟡 In Progress` for next week).
- [ ] Update the **Architecture diagram** if components, schemas, or Pub/Sub topics were altered.
- [ ] Check the **Repository Structure** tree in `README.md`. Reflect any new files or directories.
- [ ] Ensure any newly added metrics, environment variables (`.env.example`), or test commands are documented in the setup section.

### 2. Update Specific Architecture & Spec Documents
- If the change affects week-specific specs, update the corresponding file under `docs/` or `Week_X/`.
- Ensure type definitions and sample JSON payloads in documentation match actual Pydantic schema models.

### 3. Verify Code Docstrings
- Ensure every newly created tool in `triage/tools/` has a clear, stranger-readable docstring and explicit `Field(description=...)` attributes on input models.

