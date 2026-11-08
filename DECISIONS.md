# Decisions

Format: constraint → options → evidence → choice → would change if. Constraints C1–C6 are in CLIENT_BRIEF.md.

## D1. Test environment: our own mock portals, with one held out, plus a public benchmark
- **Constraint:** C2/C3 need reproducible numbers with known right answers; C4 rules out automating real
  third-party portals (terms of service, account lockouts).
- **Options:**
  - A. Build our own legacy-style portals: full control, trivial failure injection, light enough for Lambda; risk:
    "you built the site yourself, that's easy mode".
  - B. Host a real open-source ERP (e.g. Dolibarr) as the portal: realistic; heavier (PHP + MySQL), failure
    injection needs a proxy, hard to host serverless.
  - C. Hybrid A + B.
- **Choice (2026-11-08):** A, plus two answers to "easy mode":
  1. **Three portals with different structures; one is held out** (never seen while tuning prompts or tools) and
     only used in the final eval, like a test set.
  2. A small **read-only subset of Online-Mind2Web** (public benchmark of tasks on real websites) for external
     validity.
- **Would change if:** a client cares about real legacy software specifically → add
  Dolibarr as a local test run (option C).

## D3. Order system: Postgres tables behind an `OrderSystem` interface; Odoo adapter possible later
- **Constraint:** C1/C6 need exact money (NUMERIC, Decimal) and an auditable source of truth; the live demo must
  deploy serverless (D5); the project's point is computer use, not ERP integration.
- **Options:** A. plain Postgres tables (~20 min, easy to deploy on Neon) · B. Odoo Community in Docker (real ERP,
  heavy, slow to seed, hard to host, its API is off-topic work) · C. A behind an interface, Odoo adapter later.
- **Choice (2026-11-08):** C, the recommended option; to be revisited if the evals argue otherwise.
  The matcher only depends on three methods (`get_po`, `received_qty`, `supplier_name`): the same two-backends
  pattern as my Order Ops Agent (tau2 vs. Shopify).
- **Would change if:** the client is ERP-heavy (e.g. SAP/Odoo integrators) → write the Odoo adapter.

## Open (decision cards before or during the build)
- D2. How the agent sees and acts: DOM tools (Playwright selectors, read the HTML) vs. vision (Claude computer use on
  screenshots) vs. hybrid (DOM first, vision as fallback).
- D4. Model per step: one model everywhere vs. a cheap model for navigation and a stronger one for extraction.
- D5. Hosting the live demo: Lambda container with headless Chromium (default), ECS Fargate per run (fallback), or a
  hosted browser service.
- D6. What counts toward the headline success number (clean runs only vs. including injected failures).
