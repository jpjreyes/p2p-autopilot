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

## D2. How the agent sees and acts: hybrid, accessibility tree first, screenshots as fallback
- **Constraint:** C3 (survive redesigns, generalize to the held-out portal) and C5 (< $0.25 per invoice).
- **Options:** A. DOM/HTML tools: cheap, precise, brittle to structure changes · B. vision (computer use on
  screenshots): works anywhere, ~5-10x cost per step, slower, misclicks · C. hybrid.
- **Choice (2026-11-08):** C. Refinement: the DOM side reads Playwright's **accessibility
  tree** (`aria_snapshot`: roles + names of buttons, links, fields, tables), ~10x smaller than raw HTML and stable
  under cosmetic redesigns. Elements are addressed by role + accessible name, not CSS selectors. Vision only when an
  element can't be found after a retry or the page has nothing actionable.
- **Would change if:** the held-out portal or Online-Mind2Web shows the accessibility tree missing key controls
  (canvas UIs, unlabeled icons) → raise the vision share and measure the cost.

## D4. Models: Haiku first, upgrade only the steps that fail; development on the Claude CLI
- **Constraint:** C5 cost; the rule: "start with cheap models; if they can't do the task properly, then decide
  which tasks need a better model."
- **Choice (2026-11-08):** Haiku everywhere by default. The model sits behind a backend interface:
  `claude-cli` (development, runs `claude -p` on a Claude plan with no tools, no hooks, no MCP, a custom system
  prompt and JSON-schema output; ~2.6k tokens of overhead, ~1.8 s per call) and `anthropic` (the API, for the
  deployed demo and its parity check; superseded for the final evals by D23). The eval ablation decides which steps (navigation,
  extraction, vision fallback) get upgraded, with numbers.
- **Would change if:** a step's success on Haiku is below target and a stronger model fixes it at acceptable cost.

## D7. Action batching: up to 5 actions per model call, stop at the first failure
- **Constraint:** C5 (cost) and latency; the step budget.
- **Evidence (Haiku via CLI, 2026-11-08):** Portal B needs 3 actions per document (Details, Download, Close).
  One action per call: 70 calls, budget exhausted at 19/20 docs, 358 s. Batches of up to 5: **20/20 in 20 calls,
  176 s.** Portal A, one action per call: 20/20 in 28 calls, 301 s.
- **Choice (2026-11-08):** the model may batch up to 5 actions when every target is already visible; code
  executes them in order and **stops at the first failure** so the model looks again; `done`/`handoff` must be alone.
  Generic (no portal-specific hints), so it doesn't compromise the held-out test.
- **Would change if:** batching raises wrong-target errors in the chaos suite (stale page after a navigation) →
  cap the batch at actions that don't navigate.

## Earlier fix worth telling: ambiguous targets are errors
- Portal A's login boxes have no labels (common on old sites), so both are named ''. The first version silently
  took the first match and typed the password into the username box; Haiku then **handed off instead of retrying**
  (account-lockout risk, C4). Now: several matches without `nth` → error, never a silent guess.

## Open (decision cards before or during the build)
- D5. Hosting the live demo: Lambda container with headless Chromium (default), ECS Fargate per run (fallback), or a
  hosted browser service.
- D6. What counts toward the headline success number (clean runs only vs. including injected failures).
