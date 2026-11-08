# Client brief (hypothetical client, controlled test environment)

**Client:** a mid-size industrial distributor (fasteners, valves, safety equipment) buying from ~40 suppliers.
*Hypothetical engagement. The supplier portals, invoices and orders are a test environment we build, so results are
reproducible and no real company's systems are touched.*

**User:** the **Accounts Payable (AP) lead**. She decides which suppliers to automate first and how much the
automation may do on its own.

## The problem today
- Most suppliers send invoices only through their own **web portal**: no API, no EDI, no email feed.
- 3 AP clerks spend ~**20 h/week** logging into portals, downloading invoices, typing them into the order system and
  checking each one against the purchase order (PO) and what the warehouse actually received.
- Typical misses: a price above the agreed PO price, a short shipment billed in full, the same invoice paid twice.
  These become overpayments and late-payment fees.
- Each portal looks different and changes without notice, so classic scripted RPA breaks every few weeks.

## What she's afraid of
- An automation that **approves or pays** the wrong invoice.
- One that **breaks silently** when a portal changes, so nobody notices invoices are missing.
- Getting the company's **supplier accounts locked** by a bot that retries too fast.

## Constraints (every decision in DECISIONS.md points to one of these)
| # | Constraint | Value | Why it's realistic |
|---|---|---|---|
| C1 | Safety | The agent **never approves or pays**. It proposes matches and flags mismatches; a human approves | Money movement stays human-controlled in a pilot |
| C2 | Reliability | Task success ≥ target on the test portals, reported as pass^k; every failure is **detected and handed to a human**, never silent | A silent miss is worse than no automation |
| C3 | Robustness | Survives layout changes, expired sessions, pagination and slow pages; works on a portal it was **never tuned on** | Portals change without notice; new suppliers keep arriving |
| C4 | Account safety | Rate limits, no retry storms; a CAPTCHA means stop and ask a human | A locked supplier account stops the business |
| C5 | Cost | < **$0.25 per invoice** processed | A clerk costs ≈ $2–4 per invoice |
| C6 | Auditability | Every step logged with a screenshot and the reason | AP must be able to answer "why was this flagged?" |

## Success =
The agent works the invoice queue end to end on the test portals, **including one held-out portal**, with 0 unsafe
actions, every failure surfaced to a human, at < $0.25 per invoice; plus a documented comparison of when an API, a
classic RPA script or a computer-use agent is the right tool.
