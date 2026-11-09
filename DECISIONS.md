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
- **Vision fallback built (2026-11-08): `look` = set-of-marks.** A screenshot with a numbered box on every
  interactive element + a legend; the model answers with `"mark": N` and code clicks that exact element (no guessed
  pixels; unknown marks are errors). Tested with the `icon_links` chaos mode: each document gets two **unlabeled**
  icons, "request paper copy" (mails a letter, a real side effect the portal counts) and "PDF", so the accessibility
  tree shows two nameless links. Results: **A 20/20, 13 calls; B 20/20, 44 calls (vs 20 without icons); 0 side
  effects on both.** The cost doubling on B (one look per pop-up) is why vision stays a fallback, not the default.
  Failure suite now **14/14** (7 situations x 2 portals).

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

## D8. Reading PDFs: the model extracts, code checks, the portal row is a second source
- **Constraint:** C1/C2 (no wrong amounts reach AP, failures surfaced) and C3 (must work on the held-out supplier).
- **Options:** A. model extraction alone (generalizes, can misread) · B. a parser per supplier layout (exact, but
  classic RPA brittleness; useless on a new supplier) · C. model + checks in code.
- **Choice (2026-11-08):** C, as production invoice-processing systems do (extract → validate → human review).
  Checks: required fields, plain decimals, ISO dates, qty x price adds up to the total. A failed check gets ONE
  retry with the errors spelled out, then goes to a human. **Second source:** the portal's own listing row (or
  details pop-up) captured at download time must agree on total, PO and date; disagreement goes straight to a
  human, never retried.
- **Evidence (Haiku via CLI):** Portal A: 20/20 extracted, 20/20 agree with the portal row, 1 retry (the credit
  note failed the arithmetic check on the first read and passed on the retry). Portal B (European formats, details
  pop-up as the second source): 20/20 agree. End to end on both: 20/20 verdicts, 20/20 payable amounts, 7 to a
  human (= the 7 planted problems), 0 unsafe proposals.
- **Would change if:** suppliers send scanned paper PDFs (no text layer) → OCR or the vision path for extraction.

## D9. Tool feedback is part of the prompt: say exactly what happened and what to do next
- **Constraint:** C2 (recover when possible, never fail silently) and C5 (cost).
- **Evidence (failure suite, Haiku via CLI, 2026-11-08):** first full suite 11/12. The model was fine in both
  problem cases; the tool's messages weren't:
  | Case | Tool message before | Before | Tool message after | After |
  |---|---|---|---|---|
  | B, session expiry (page still shows the list; only downloads get the login page) | "not a PDF (HTTP 200); the session *may* have expired" | retried 4x, handed off after 1/20 docs (safe, but no recovery) | "session expired: the portal sent its login page (/b/login) ... log in again and continue" | **20/20, 28 calls, PASS** |
  | A, layout redesign ("View PDF" became "Open", a link opening a new tab) | new tab silently ignored ("clicked") | 20/20 but **31 calls, 389 s** | "it opened a new tab at ... (closed); to save a document use download on that link" | **20/20, 11 calls, 142 s** |
- **Choice (2026-11-08):** tool results name the cause and the next step; tools close stray tabs and
  inspect where a failed download landed. Generic feedback, no portal-specific hints (held-out test stays fair).
- **Also found by the suite (my bugs, fixed, now covered by real-browser tests):** a `goto` to a file crashed the
  run; Playwright rejected a built-in method as an event handler. Any browser error is now a failed action, the
  suite isolates and saves every run, and 3 headless-Chromium tests cover the tool guardrails in CI.
- **Final failure-suite result: 12/12** (5 failure modes + clean, portals A and B; CAPTCHA = handoff in 1 call).

## Open (decision cards before or during the build)
- D5. Hosting the live demo: Lambda container with headless Chromium (default), ECS Fargate per run (fallback), or a
  hosted browser service.
- D6. What counts toward the headline success number (clean runs only vs. including injected failures).
