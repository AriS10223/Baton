# BATON.md — Living Project Onboarding Document

> Test fixture for the Baton test suite.

```yaml
baton_version: "1.0"
last_updated: "2026-06-04"
last_session_tool: "claude-code"

project:
  name: "TestProject"
  purpose: "Solve the context-loss problem for vibe coders"
  target_user: "independent developers"
  stage: "prototype"

architecture:
  overview: "Simple Flask API with SQLite backend."
  key_directories:
    - path: "src/"
      purpose: "Application source code"
    - path: "tests/"
      purpose: "Test suite"
  entry_point: "app.py"
  data_flow: "HTTP request → Flask router → service layer → SQLite"

stack:
  - tool: "Flask"
    version: "3.0.0"
    why: "Simple REST API, team knows it well"
    gotchas: "Don't upgrade past 3.0 — breaks custom middleware"
  - tool: "SQLite"
    version: "3.x"
    why: "Zero-config local storage, same SQL dialect as Postgres"
    gotchas: ""

laws:
  - "Never use TypeScript. This is a Python-only project."
  - "All database writes must go through the service layer."

current_sprint:
  goal: "Build the filter sidebar component"
  done:
    - feature: "User authentication"
      confidence: "stable"
      notes: "Uses Supabase, do not touch"
  in_progress:
    - feature: "Filter sidebar"
      owner: "Aryan on Claude Code"
      last_touched: "2026-06-04"
      context: "Building the UI component, halfway done"
      blockers: []
  blocked: []
  next:
    - feature: "Dashboard view"
      priority: "high"
      dependencies: ["filter-sidebar"]

decisions:
  - id: "d001"
    what: "Using SQLite for local dev, Postgres in prod"
    why: "Simpler local setup, same SQL dialect"
    made: "2026-06-04"
    made_in: "claude-code"

anti_decisions:
  - id: "a001"
    rejected: "TypeScript frontend"
    why: "Scope too large for MVP, team is Python-first"
    ruled_out: "2026-06-04"

landmines:
  - location: "auth/callback.py"
    looks_like: "Broken redirect with missing return statement"
    actually: "Intentional for OAuth PKCE flow — redirect via header"

open_questions:
  - id: "q001"
    question: "Should filters be multi-select or single-select?"
    context: "Multi-select is more powerful but adds UI complexity"
    raised: "2026-06-04"
    raised_by: "Claude Code session"
    status: "open"
    discussion: "Leaning multi-select but need to validate with users"
    resolution: ""
    resolved_date: ""
    blocking:
      - "filter-sidebar"

sessions: []
```
