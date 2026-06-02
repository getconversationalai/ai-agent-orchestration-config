# [Project Name] — Project Scope

## Structure

```
# Describe your project's directory structure here
src/
├── ...
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | |
| Backend | |
| Database | |
| Hosting | |

## Key Database Tables

<!-- List your main tables, e.g.: users, organizations, projects, ... -->

## Project Structure Conventions

<!-- Describe how code is organized: feature folders, naming patterns, barrel exports, etc. -->

## Code Style Rules

<!-- List the conventions agents must follow, e.g.:
- Use existing UI components before creating custom ones
- Use [ORM] for all DB queries — no raw SQL
- Use [validation lib] for all input validation
-->

## Documentation Guide

| Document | Purpose | When to Read |
|----------|---------|-------------|
| `plans/phase-*.md` | Task breakdowns, schemas, acceptance criteria | Primary reference — read before any work |
| `Product-And-Tech-Spec.md` | Requirements, API contracts, UX specs | When you need exact field definitions |

## Hub Files (Parallel Agent Coordination)

<!-- These files are modified by nearly every feature. When running parallel agents, handle these centrally:
- src/app/routes.ts
- src/types/index.ts
- ...
-->

## Migration File Naming

<!-- If using parallel agents with DB migrations:
Each agent must use a unique migration prefix (e.g., Agent A gets 0010_, Agent B gets 0020_).
Include this in the agent's prompt. Never let agents auto-number — they'll collide.
-->
