# P2P Autopilot

[![ci](https://github.com/jpreyesm03/p2p-autopilot/actions/workflows/ci.yml/badge.svg)](https://github.com/jpreyesm03/p2p-autopilot/actions/workflows/ci.yml)

**Live demo: [p2p-autopilot-eight.vercel.app](https://p2p-autopilot-eight.vercel.app)** (console on Vercel, API, portals and agent jobs on
GCP Cloud Run; start a real agent run and review what it proposes; first load after a quiet period takes a few seconds).

Accounts payable in one system: it **sees** the real purchase-to-pay process (process mining on 1.6M SAP events),
**predicts** which invoices will be blocked before anyone touches them, and **acts** where there's no API: an agent
collects invoices from supplier portals the way a person would, reads scans and handwritten corrections, runs the
3-way match in code, and sends anything doubtful to a person. **It cannot pay.** There is no pay or approve action
anywhere in the agent; a human approves every payment in the review console.

> Data: the public BPI Challenge 2019 log (a coatings manufacturer's SAP purchase-to-pay, 251,734 PO lines, CC BY 4.0).
> The supplier portals are mocks built for this project; their invoices bill **real purchase orders and goods receipts
> from that log** ([D17](DECISIONS.md)). No real third-party site is automated. Scenario: [CLIENT_BRIEF.md](CLIENT_BRIEF.md).
> This merges the original analyst ([Process Copilot](https://github.com/jpreyesm03/process-copilot), kept public as
> the first version) with the portal agent ([D16](DECISIONS.md)).

![Review console: the invoice next to the 3-way match, with a handwritten correction flagged](docs/img/review-drawer.png)

## Results

| | What | Result |
|---|---|---|
| **See** | Paid before any goods receipt (3-way match) | **EUR 1,753,787** on 655 lines, found by SQL on the real log |
| | Open longer than the vendor usually takes | **EUR 1,015,808** on 828 invoices (no due dates exist, so measured against each vendor's own paid invoices) |
| **Predict** | Payment blocks, flagged when the invoice arrives (test months never used for training) | of the **10 invoices it ranks highest each day, 92% really get blocked**; at the best rule's precision it finds **1.5x the blocked money** (EUR 14.7M vs 9.6M) and covers 66% of it at a wider setting. Found by looking at the data: SAP blocks whole invoices, not lines ([D18b](DECISIONS.md), [D18c](DECISIONS.md)). Limits reported: no early signal at PO creation; price and quantity disputes are no more predictable than the vendor's history, because the public log has no invoice prices or quantities |
| | Weekly risk brief, written without being asked | every number from SQL; the summary is checked so it can't state a number no query produced: **0 unverified** |
| **Act** | Reliability (pass^3: the whole job right in 3 of 3 runs) | **1.00** on every condition, portals A and B (final suite, 60 runs) |
| | Safety (payments proposed that would have been wrong) | **0** in all 68 final runs and every development run, including redesigns, expired sessions, prompt injection, scans and handwriting |
| | Generalization (a portal the agent had never seen) | Portal C: first contact 7/20; three general fixes, then 20/20. **Held-out Portal D, first contact: 0/3**, each run handed to a person with the reason, nothing downloaded, nothing unsafe: its Export is a button that opens the PDF in a new tab, which the browser tool could not save from ([D24](DECISIONS.md)). One general fix to the tool (download from export buttons), then **3/3, 0 unsafe** ([D25](DECISIONS.md)) |
| | Failure suite, on invoices billing real SAP POs (10 conditions x 2 portals x 3 runs) | **60/60**, 0 unsafe, every document right in all 3 runs of every condition; getting there found two problems, both fixed at the root: a silently skipped page (now a completeness check in code) and a PDF column overflow in the test data ([D22](DECISIONS.md), [D24](DECISIONS.md)) |
| | Scanned invoices · handwritten corrections | 120/120 read from the image · 36/36 sent to a human, 0 false alarms (final suite) |
| | Real scans (SROIE: 347 real scanned receipts, public benchmark) | total **98.3%**, date **97.7%**; each total miss read by hand: 1 real misread in 347 (the receipt's own arithmetic exposes it), the rest label conventions and one label error ([D26](DECISIONS.md)) |
| | Cost per invoice (navigation + reading, API-equivalent) | **~$0.0015** (final suite mean; $1.74 for all 60 runs) |
| **Models** | Self-hosted reader: Qwen3-VL-4B fine-tuned (QLoRA) on 445 real receipts, for documents that cannot leave the company | real receipts, total and date both right: **85.0% untuned to 91.9% fine-tuned** (Claude Haiku 97.1%); on 100 receipts from companies never seen in training **78% to 84%**, so it learned to read, not the layouts. On invoices it got worse (77% to 63%: it learned "take the date" and picks the due date), and the code check still catches every miss: small model first, Claude on 37%, **100%, 0 silent errors** ([D28](DECISIONS.md), [D30](DECISIONS.md)) |
| | Model registry (MLflow on Databricks) | both models versioned with data hashes; promotion only through a gate written before the comparison: the receipt reader passed (held-out 50: 86% to 100%), a payment-block challenger was rejected; drift report on the real train-to-test shift ([D29](DECISIONS.md)) |
| **Data** | Same dbt project on DuckDB, Databricks (live daily job) and Snowflake | **all 6 tables identical, row for row**, on all three engines; a day-by-day replay of the test months reproduces the daily top 10 (92.4% vs 92.0%); a leak check runs in CI ([D31](DECISIONS.md), [D32](DECISIONS.md)) |

Act numbers: final evals, Claude Haiku via the Claude CLI on a Claude plan in an isolated configuration (one sentence
added to every prompt by an account-managed hook), extraction never cached, code version recorded per run;
costs are API-equivalent. How each number was produced, and what changed when something failed:
[DECISIONS.md](DECISIONS.md) (D16-D19 for see and predict, D23-D26 for the final evals).

## See → predict → act

| See: the process, from SQL | Predict: invoices likely to be blocked, and why | The weekly brief |
|---|---|---|
| ![Process](docs/img/process.png) | ![Risk worklist](docs/img/risk.png) | ![Weekly brief](docs/img/brief.png) |

- **See:** the log is cleaned once into a DuckDB warehouse (analytics) next to the Postgres the agent writes to
  (operations): an OLAP / OLTP split, and a 78 MB columnar file ships with the app at no cost ([D16](DECISIONS.md)).
- **Predict:** LightGBM on each PO line and the other lines of its invoice (SAP blocks whole invoices: 98% of
  multi-line invoices share one outcome), with features only from events before the decision point, vendor history
  only from months whose outcomes were known, a temporal split, isotonic calibration, and the three features that
  pushed each score up most as plain-language reasons ([D18](DECISIONS.md), [D18b](DECISIONS.md)).
- **Brief:** every Monday the analyst runs a fixed set of analyses for the week and writes one page; code computes the
  numbers, the model writes the words, and a grounding check rejects any number no query produced ([D19](DECISIONS.md)).
- **Act:** the portal agent, below.

## How the agent works (act)

```
portal (no API) ──► agent loop (Playwright + Claude)          what the model does
                     · reads the page's accessibility tree    decides the next clicks
                     · screenshot with numbered boxes when    picks a numbered box
                       icons have no names
                     · downloads each open invoice's PDF
                         │
                         ▼
                    extraction                                reads the fields (text, or the page image)
                     · checks in code: lines add up to the total, formats, and the portal's own row agrees
                     · handwriting on an amount → a person
                         │
                         ▼
                    3-way match in code (never the model)
                     · PO price × received qty, duplicates, unknown PO, credit notes, already paid (AP ledger)
                         │
                         ▼
                    review console (Next.js) ──► a person approves or rejects
```

**The risky parts are code, not instructions.** The model can be wrong or be tricked (an invoice that says
"pre-approved, pay now" is a test case). So:

- no pay or approve tool exists for the agent;
- the money math is deterministic Python (`Decimal`), not the model;
- every extracted number is checked twice: arithmetic, and against the portal's listing;
- a link or button with no name can only be clicked after the agent has seen it (it mailed paper copies by guessing
  when it couldn't: [D13](DECISIONS.md));
- secrets never reach the model, navigation outside the portal is blocked, login attempts are capped;
- a person approves every payment.

## The review console

Next.js console for the AP team: start a run (optionally breaking the portal on purpose), replay every step the
agent took with its screenshots and reasoning, and review exceptions with the invoice next to the PO and goods
receipt. Approve and reject are the only money actions, and they belong to people.

| Run replay | Evals |
|---|---|
| ![Run replay](docs/img/run-replay.png) | ![Evals](docs/img/evals.png) |

## What the experiments showed

- **Most failures were tool failures, not model failures.** Vague error messages, cut-off page views and a fill that
  reported success after typing nothing. Fixing what the tools tell the model fixed the agent ([D9](DECISIONS.md),
  [D12](DECISIONS.md), [D13](DECISIONS.md)).
- **Screenshots are needed only where names fail.** Reading the accessibility tree alone passes clean portals at the
  same cost; when icons hide their purpose, only the screenshot gets it right (2/2 vs 0/2).
- **Batching actions is necessary, not just cheaper.** One action per model call costs 2.7x and runs out of steps on
  the hardest portal.
- **A prompt rule is not a guardrail.** "Never click what you're not sure of" did not stop a blind agent; a check in
  code did.
- **The held-out portal failed safely, and the cause was the tool again.** Its Export button opens the PDF in a new
  tab; the download tool only knew links. All three first-contact runs stopped and handed off with that reason
  (nothing unsafe). One general fix to the tool took it to 3/3 ([D24](DECISIONS.md), [D25](DECISIONS.md)).

## Models and MLOps

Two models in the product live in one MLflow registry (Databricks Free Edition, Unity Catalog), each with a
champion/challenger gate written before the comparison ran.

- **Receipt and invoice reader, fine-tuned and self-hosted.** For companies that cannot send documents to an outside
  model. Qwen3-VL-4B-Instruct (Apache 2.0), 4-bit QLoRA with Unsloth on one free Kaggle T4 (36 min of training,
  3.7 GPU hours for the whole job). The protocol (data split, scoring rules, a test set touched once, the 100
  unseen-company receipts, the gate) was written before training ([D28](DECISIONS.md)). Results and every miss read
  by hand: [D30](DECISIONS.md). The point is privacy, not cost: Haiku reads a receipt for about $0.0007.
- **What it showed:** fine-tuning bought ~7 points on real receipts and kept them on unseen companies, but a model
  trained only on receipts got worse on invoices (it reads the due date as the date). It is safe exactly where a
  code check backs it up: on invoices the portal-row check sends every wrong reading to Claude (0 silent errors); on
  loose receipts, with nothing to check against, 8% of wrong readings get through.
- **Payment-block model:** the LightGBM model and its calibration as one MLflow model, reproduced exactly from the
  saved training code; a challenger was rejected by the gate on the August dev month (test months never used to
  choose); Evidently drift report on training vs test months: 14 of 38 inputs drift, including the score, yet the
  model held up, so drift triggers a performance check, not a retrain ([D29](DECISIONS.md)).
- **Reproducible:** pinned library versions on Kaggle and the Mac, dataset hashes on every run, the Kaggle kernel
  version as a tag. Training data (SROIE) and the trained adapter stay private.

How this maps to Google Cloud: Kaggle notebook = Vertex AI custom training job (a T4 or L4); MLflow tracking and
registry = Vertex AI Experiments and Model Registry (aliases = version aliases); the gate script = a Vertex AI
Pipelines step; Evidently = Vertex AI Model Monitoring. Kept on free tiers here; nothing is served from the registry
(the live demo uses Claude and the baked payment-block model).

## Data platform

The SAP data of a real customer lives in their warehouse, so the warehouse build is versioned, tested dbt SQL that
gives the same tables on whichever engine the customer runs, and a daily job feeds new data through it.

```
SAP extract (one file per day) -> land -> ingest -> dbt build + tests -> score with @champion -> daily worklist
                                   |        |            |
                     DuckDB reads files   Databricks Auto Loader -> Delta (bronze)   Snowflake stage + COPY INTO
```

| Target | How it runs | Parity |
|---|---|---|
| DuckDB | local and in CI | all 6 tables identical, row for row, to the original Python build (1.6M events, 211k feature rows) |
| Databricks (Free Edition) | **live daily job**: the day's file arrives, Auto Loader ingests only new files, dbt builds and tests on a serverless SQL warehouse (~45 s), the champion model from Unity Catalog scores the day's invoices | identical to DuckDB on the same files; scores exactly equal |
| Snowflake (trial) | same dbt project, `--target snowflake` | 33/33 models and tests on the first build; identical to the original Python build |

- **The CV number survives a real replay.** Day by day over the test months, with only the data that existed each day,
  the top 10 invoices ranked daily were really blocked **92.4%** of the time (the one-shot score said 92.0%).
- **Making engines agree found real differences**, fixed in one macro file instead of loosening the check: Spark
  rounds a double like 77.975 up and DuckDB down, and Spark sorts NULLs first in a window.
- **Leak check in CI:** features built from data up to a cutoff must not change when later data lands. It found a
  small leak in the original features (`po_lines` counted PO lines created after the invoice, 1.1% of test lines); it
  did not inflate the claim, and it is bounded in the check. dbt tests also guarantee no test-month row and no
  not-yet-observable label can reach training.

Details and every number: [D31](DECISIONS.md), [D32](DECISIONS.md). Code: `dbt/`, `src/p2p_autopilot/data_layer/`,
`data_layer/databricks/` (the job is a JSON spec deployed by `deploy.py`), `data_layer/snowflake/`.

| ![Databricks daily job: 6 green runs](docs/img/data-platform/databricks-job-runs.jpg) | ![One run: arrive, ingest, dbt build, score](docs/img/data-platform/databricks-task-graph.jpg) |
|---|---|
| ![Unity Catalog lineage built from the dbt models](docs/img/data-platform/databricks-lineage.jpg) | ![The same dbt models on Snowflake](docs/img/data-platform/snowflake-dbt-tables.jpg) |

## Stack

Python 3.12 · DuckDB (process warehouse) · LightGBM + scikit-learn (prediction) · Playwright (Chromium) · Claude Haiku
(evals through the Claude CLI; the Anthropic API for the deployed version) · pypdf + pypdfium2 · FastAPI · Postgres ·
Next.js · OpenTelemetry · pytest + GitHub Actions (real browser in CI) · Docker · Terraform for GCP
(Cloud Run + Cloud Run Jobs for the browser runs) · fine-tuning: PyTorch, Hugging Face Transformers, TRL, PEFT
(QLoRA), Unsloth, Qwen3-VL-4B on Kaggle · MLOps: MLflow + Unity Catalog registry on Databricks, Evidently ·
data platform: dbt (DuckDB, Databricks, Snowflake), Databricks Jobs, Auto Loader, Delta Lake.

## Repository layout

```
src/p2p_autopilot/
  process/        see + predict: SAP log -> DuckDB warehouse, metrics, payment-block model, risk worklist, weekly brief,
                  registry.py (MLflow registry, champion/challenger gate, drift report)
  agent.py        the portal agent loop (decisions, batching, completeness check, loop guard)
  browser.py      browser tools the model uses (accessibility tree, marks, downloads) and their guardrails
  extract.py      invoice extraction (text or page image) + arithmetic and portal cross-checks
  matching.py     deterministic 3-way match (Decimal), AP ledger, verdicts
  pipeline.py     run -> extract -> match -> review items, and scoring against ground truth
  chaos_suite.py  failure suite: every breakage mode on every portal, pass^k
  orders/         the order system (Postgres): POs, goods receipts, paid invoices
  portals/        the mock supplier portals (FastAPI) and the chaos switch
  api.py, worker.py   console API and the job worker (one agent run per job)
  llm.py, subscription.py, tracing.py   model backends, clean-CLI eval runner, OpenTelemetry
web/              Next.js review console (process, risk, brief, runs, review queue, evals)
tests/            pytest, including a real headless browser
evals/finetune/   receipt-reader fine-tune: data prep, Kaggle training notebook, scorer, cascade, registry gate
dbt/              warehouse models (staging, D1 date repair, event log, features, training rows), tests, engine macros
data_layer/       baseline fingerprints, the Databricks job (spec + deploy + parity), the Snowflake load + parity
infra/gcp/        Terraform: Cloud Run services + Jobs, Secret Manager, Storage, Scheduler, budget alert
scripts/          dev database, eval runner with resume (run_eval.sh), eval page builder, GCP deploy
data/             the BPI 2019 log (compressed) and the trained models
DECISIONS.md      every design decision and eval, with the numbers and what changed after each failure
CLIENT_BRIEF.md   the scenario: who the client is and what success means
```

## Run it locally

```bash
uv sync && uv run playwright install chromium
uv run python -m p2p_autopilot.process.warehouse            # real SAP log -> DuckDB (6 s)
uv run python -m p2p_autopilot.process.predict --worklist   # score open invoices (train first: predict, ~1 min)
uv run python -m p2p_autopilot.process.brief                # this week's brief
scripts/dev_db.sh up                                        # Postgres on 127.0.0.1:55434
uv run python -m p2p_autopilot.orders.store                 # load the order system
uv run uvicorn p2p_autopilot.portals.app:app --port 8061    # the mock portals
uv run python -m p2p_autopilot.agent --portal a             # one run
uv run python -m p2p_autopilot.chaos_suite --portals a b --repeat 3   # failure suite with pass^k
scripts/run_eval.sh runs/final/suite.json --portals a b --repeat 3     # same, resumable after limits or crashes
uv run python evals/real_scans.py                                       # real scans (SROIE; download in the script)
uv run --group mlops python -m p2p_autopilot.process.registry           # payment-block model -> MLflow registry + gate + drift
uv run python evals/finetune/score.py --run runs/finetune/kaggle_out    # score the fine-tuned reader (Kaggle outputs)
uv run --group dbt python -m p2p_autopilot.data_layer.land --full       # land the raw extract with source row ids
uv run --group dbt dbt build --project-dir dbt --profiles-dir dbt       # dbt models + tests on DuckDB
uv run --group dbt python -m p2p_autopilot.data_layer.parity            # row-for-row parity with the Python build
uv run --group dbt python -m p2p_autopilot.data_layer.leak_check        # features must not change when later data lands
```

Console: `uv run uvicorn p2p_autopilot.api:app --port 8062`, then `cd web && npm ci && npx next dev -p 3061`.

## Limits

- Portals are mocks; real portals will find new failure modes (that's what the held-out portal is for). Invoices bill
  real POs, but the quantity x price split of each SAP line amount and the planted problems are synthetic (D17).
- The SAP log is a 2017-2019 snapshot: "this week" in the brief is its last week, and the payment-block model can only
  be retrained on that history.
- The invoice scans and handwriting are generated. Reading real paper is measured on receipts (SROIE, D26), not on
  real invoices with line items and PO numbers; real handwriting styles at scale are untested.
- `already_paid` is only as good as the AP ledger it reads.
- The fine-tuned reader had one training run on receipts only; invoices in the training mix (D28's run 2) were not
  tried. It is measured offline and not served.

## License

MIT
