---
name: git-workflow
description: Standard git commit, branching, and pull request workflow following GitHub best practices and Conventional Commits. Use whenever finishing a feature, major refactor, or preparing to submit a PR.
---

# Git & Pull Request Automation Workflow

This skill guides atomic git commits, branch management, and preparing high-quality Pull Requests adhering to GitHub best practices.

## 1. Commit Lifecycle & Approval Synchronization
**Why files show as modified after approval:**
When files are generated or modified, the Antigravity editor holds them in review. When the user approves/accepts them, the editor flushes them to disk (often formatting or normalizing line endings).
If `git commit` was run in the same turn before the user accepted the changes, git commits the pre-review disk state, leaving the newly accepted files unstaged.

**The Safe Commit Protocol:**
1. During file creation/editing: Write files, format with `ruff`, run `pytest`. Report the output to the user.
2. At the start of the next turn (after the user has accepted the changes):
   - Run `git status` to detect all accepted changes.
   - Stage all verified files with `git add <files>` or `git add -u`.
   - Run `git commit` with a clean Conventional Commit message.

## 2. Commit Message Convention (Conventional Commits)
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
- `feat(substrate): implement Pipeline B gold join and data quality assertion checks`
- `test(contracts): add pytest coverage for Gherkin contract scenarios`
- `docs(readme): add architecture diagram and phased build roadmap`
- `chore(infra): scaffold BigQuery dataset definitions in terraform`

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
