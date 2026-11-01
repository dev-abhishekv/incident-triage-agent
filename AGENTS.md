# Agent Guidelines for Incident Triage Agent

This repository implements an autonomous Incident Triage Agent for data pipelines benchmarked against a deterministic baseline.

## Operating Rules for the Agent

1. **Automatic Documentation Maintenance (`doc-sync` skill):**
   - After completing any major milestone, pipeline stage, or architectural contract change, automatically review and synchronize `README.md` and related docs.
   - Keep the Phased Roadmap progress updated in `README.md`.
   - Never let docstrings or schemas drift from implementation.

2. **Automated Git Commits & PRs (`git-workflow` skill):**
   - Synchronize with the user's review lifecycle: do not execute premature `git commit` within the exact same turn that writes the files if pending user review exists.
   - At the beginning of each turn or after verification, inspect `git status`, stage accepted modifications, and commit with a clean Conventional Commit message (e.g. `feat(substrate): ...`, `test(gold): ...`).
   - Ensure tests pass (`pytest`) and code passes linting (`ruff check`) before committing.
   - When completing a phase/milestone, create a feature branch (e.g. `feat/week-1-substrate`) and format a GitHub-ready PR summary.

3. **Core Architectural Non-Negotiables (`triage-agent-conventions` skill):**
   - Enforce Pydantic boundary models (`extra="forbid"`) on all tool inputs, outputs, and triage results.
   - All diagnosis methods must implement `TriageStrategy`.
   - `ops.*` BigQuery schemas are immutable contracts; never widen columns without explicit design review.
   - Tools are strictly read-only and return structured evidence.
