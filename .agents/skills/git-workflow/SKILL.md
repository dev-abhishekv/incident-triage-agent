---
name: git-workflow
description: Standard git commit, branching, and pull request workflow following GitHub best practices and Conventional Commits. Use whenever finishing a feature, major refactor, or preparing to submit a PR.
---

# Git & Pull Request Automation Workflow

This skill guides atomic git commits, branch management, and preparing high-quality Pull Requests adhering to GitHub best practices.

## 1. Commit Message Convention (Conventional Commits)
Format: `<type>(<scope>): <short summary>`

Types:
- `feat`: A new feature (e.g., a new triage tool, baseline rule, pipeline step).
- `fix`: A bug fix in pipelines, tools, or injectors.
- `test`: Adding or updating automated tests (e.g., Gherkin contract tests).
- `docs`: Documentation updates, README changes, or architecture diagrams.
- `refactor`: Code change that neither fixes a bug nor adds a feature.
- `chore`: Tooling, dependency, or terraform configuration updates.

Examples:
- `feat(triage): implement Pydantic contracts and TriageStrategy protocol`
- `test(contracts): add pytest coverage for Gherkin contract scenarios`
- `docs(readme): add architecture diagram and phased build roadmap`
- `chore(infra): scaffold BigQuery dataset definitions in terraform`

## 2. Commit Checklist
Before committing:
1. Run linting & formatting: `ruff check .`
2. Run automated test suite: `pytest tests/`
3. Check `git status` to ensure no sensitive files (`.env`, credentials, local caches) are staged.
4. Stage relevant files: `git add <files>`
5. Commit with an informative conventional message.

## 3. Pull Request Guidelines
When raising or proposing a Pull Request:
1. **Branch Naming:**
   - Feature: `feat/week-<number>-<short-description>` (e.g., `feat/week-1-substrate`)
   - Fix: `fix/<issue-description>`
2. **PR Description Structure:**
   - **Summary:** 2-3 sentences explaining what was built and why.
   - **Key Changes:** Bulleted list of components added/modified.
   - **Verification:** Command outputs showing all tests passing.
   - **Next Steps:** What unblocks in the next milestone.

