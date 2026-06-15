# Reply Flow Payments + Commerce System — Session Wrap-up

**Status**: Phases 1–4 delivered + security hardening complete. Remaining: test isolation cleanup + refund-coordination double-path fix.

---

## What Was Delivered

### Phase 1–2: Ledger & Stripe Foundation (Commits: `af310b29`, `53e1ea1b`)
- **Ledger core**: `payment_requests` → `payment_installments` unified model
  - No monthly/status duplication
  - Server-driven reconciliation independent of order state
  - Single source of truth for payment truth
- **Stripe direct-charge flow**
  - Hosted-link-only (zero card data on Reply servers)
  - Capability-tagged providers (charge + refund flags on schema)
  - Webhook reconciliation with order state cross-check
- **Pricing reference-only**
  - Client sends price; server re-resolves canonical price from source (contact/product/discounts)
  - Guards against stale/manipulated prices

### Phase 3: Store Checkout & Hub UI (Commit: `c017b229`)
- **Checkout flow**: cart → payment modal → completion screen
  - Opt-in stop-on-pay (store owner choice, not blanket kill sequences)
  - Sequences resume after payment unless explicitly configured to stop
- **Hub UI consolidation**: Payments + Orders + Revenue + Approvals + Setup merged into single Commerce section
  - Navigation, permission scoping, data freshness aligned
  - Reference structure for future feature additions
- **Order-independent reconciliation**
  - Payment records reconcile against ledger state, not order lifecycle
  - Unblocks future async fulfillment

### Phase 4: Sequences & UX Coherence (Commit: `c017b229`)
- **Sequences integration**
  - Pause → prompt (interactive) or stop (terminal) states
  - Payment triggers work across hub + store checkout
  - Modal state kept in sync with backend
- **Hub refresh cadence**: Initial 5s poll, backoff to 30s after stabilization
  - Prevents thundering herd; balances responsiveness with efficiency

---

## Key Architectural Decisions & Trade-offs

| Decision | Rationale | Trade-off |
|----------|-----------|-----------|
| **Hosted-link-only** | Zero card PII on servers; PCI compliance delegated to Stripe | Client can't custom-theme Stripe form; no offline/fallback capture |
| **Thin ledger** (`payment_requests` + `payment_installments`) | Single source of truth; avoid sync debt (no monthly snapshots) | Requires server-side reconciliation logic; no pre-computed balances |
| **Capability-tagged providers** | Grant only needed permissions (charge XOR refund); limit blast radius | More schema bookkeeping; runtime checks vs. access control |
| **Opt-in stop-on-pay** | Explicit ownership; sequences don't auto-halt globally | Store owner must read docs + enable; default is continue |
| **Reference-only pricing** | Client can't manipulate cost; detects stale/fraud attempts | Server latency on every checkout; requires canonical source |
| **Order-independent reconciliation** | Unblock async fulfillment; payment truth decoupled from orders | Orders and payments can drift if handlers fail; requires monitoring |

---

## Security Hardening (Audit + Fixes)

### Findings Summary (Commit: `02669c2e`)
- **1 Critical (FIXED)**: Plaintext API key in Stripe webhook mock → removed
- **4 High (FIXED)**:
  1. SSRF on payment-resolve endpoint → input validation + domain whitelist
  2. Order-hijack via `payment_requests.order_id` write → gate with authorization check
  3. Reconcile durability (lost payments on retry) → unique constraint + idempotent webhook key
  4. Over-refund (no ledger-sourced cap) → refund amount validated against ledger balance
- **3 Follow-ups (Tracked, not blocking)**:
  1. SSRF on adapter payloads (adapters forward external payment events)
  2. Synthetic external payment legs (audit trail for manual adjustments)
  3. OMS cumulative guard + Gap-2 source-from-ledger (Commit: `33334ae9`)

### Adversarial Verification
- Attempted order hijack → caught by authorization
- Unauthorized refund → caught by ledger balance check
- Stale price injection → caught by server re-resolution
- Webhook replay → caught by unique constraint (idempotent key)
- **Result**: No silent failures; system either rejects cleanly or logs & alerts

---

## Lessons Learned (Process + Technical)

### Process Slip
**Gate-and-push without test validation** (Commerce consolidation merge)
- Merged without confirming tests passed in CI first
- **Fix**: Always run `npm test --workspace=<target>` before `git push`, not after
- **Root**: Assumed vitest runs identically locally and in CI (false assumption)

### Technical Trap: Test Runner Alias Resolution
**`npm test --workspace=client` vs. `npx vitest`**
- Two different behaviors due to alias resolution
- `npm test --workspace=<name>` is correct (uses workspace root); raw `npx vitest` runs wrong suite
- Cost: ~30 min debugging tests that seemed flaky but weren't
- **Mitigation**: CI now explicitly uses `npm test --workspace=<name>`; never raw vitest in scripts

### CI Nondeterminism
**orderDispatcher cross-file mocks**
- Same tests passed locally, failed in CI (non-deterministic)
- Root: Mock state leaked between tests (singleton not reset)
- **Fix**: Explicit cleanup in `afterEach`; isolated test setup per suite
- **Lesson**: Mocks are stateful; isolation is not automatic—must be explicit

---

## Remaining Work (Before Merge to Main)

### Test Isolation Cleanup
1. Fully isolate `orderDispatcher` mocks across all suites
2. Verify no shared state in payment ledger tests
3. Confirm CI runs green 3× consecutively before final merge
4. Add explicit test isolation guards to prevent regression

### Refund-Coordination Fix
**Bug**: Refund can flow via two paths:
1. `reconcile()` (webhook from Stripe)
2. `refund()` (hub UI button click)

**Vulnerability**: Both can execute simultaneously → potential double-refund

**Fix**:
- Mark ledger record as "refund-in-flight" when either path starts
- Gate second attempt with existence check
- Update order state atomically with ledger
- Use idempotent refund key in Stripe + DB unique constraint

**Risk Mitigations**:
- Handle ordering of webhook vs. user action (webhook can arrive after user clicks)
- Make refund idempotent (Stripe idempotency key + DB unique constraint on payment_installment_id + refund_id)

---

## Major Milestone Commits

| Phase | Commit | Focus |
|-------|--------|-------|
| Phase 1 | `af310b29` | Ledger core + test scaffolding |
| Phase 2 | `53e1ea1b` | Stripe webhook + reconcile |
| Payments Hardening | `02669c2e` | 5 security fixes + audit entry |
| Commerce Consolidation | `c017b229` | Orders/Revenue/Approvals merge + hub refresh logic |
| Security Follow-ups | `0854f899` | Gap-1 fixes + adversarial closure |
| Gap-2 (OMS) | `33334ae9` | Source-from-ledger cumulative guard |

---

## Files to Watch

**Ledger/Payments Core:**
- `/api/routes/payments.ts` — reconcile, webhook, refund entrypoints
- `/client/lib/store.ts` — checkout flow, payment modal
- `/api/models/payment-ledger.ts` — schema + queries
- `/api/models/payment-installment.ts` — installment reconciliation logic

**Hub UI:**
- `/client/pages/Commerce.tsx` — merged section (Payments/Orders/Revenue/Approvals/Setup)
- `/client/hooks/useCommerceData.ts` — polling + data freshness (initial 5s, backoff 30s)

**Sequences:**
- `/api/sequences/executor.ts` — pause/stop state handling + payment trigger
- `/client/lib/sequences.ts` — modal state sync

**Tests (watch for flakiness):**
- `__tests__/payment-ledger.test.ts` — ledger isolation critical
- `__tests__/orderDispatcher.test.ts` — mock cleanup critical
- `__tests__/checkout.test.ts` — end-to-end flow
- `__tests__/sequences.test.ts` — payment trigger integration

---

## DB Schema (Key Tables)

- `payment_requests` — top-level payment (order context, external reference)
- `payment_installments` — individual charge + refund records (ledger entries)
- `stripe_webhook_events` — idempotent webhook processing (unique constraint on event_id)
- `orders` — order state (references payment_requests, not payment_installments)

---

## Conventions

1. **Always re-resolve prices server-side** — never trust client price
2. **Refunds must be idempotent** — use Stripe idempotency key + DB unique constraint
3. **Test isolation** — explicit cleanup; no shared mock state
4. **Hub polling** — start at 5s, backoff to 30s; cancel on unmount
5. **Opt-in stop-on-pay** — sequences continue by default unless store owner enables stop
