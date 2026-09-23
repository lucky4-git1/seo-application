# Billing & entitlements (Step 17 — foundations)

## What exists now

- **Plans**: `organizations.plan` (FREE|PRO|BUSINESS) with `PLAN_LIMITS` in
  `app/entitlements.py`: projects per org, tracked keywords per project,
  crawl pages per run, monthly SERP/keyword/export quotas.
- **Enforcement**: project creation and tracked-keyword creation reject with
  HTTP **402** + upgrade message at the limit; audits clamp `max_pages` to
  the plan (returned as `max_pages_applied`); SERP/keyword/report jobs fail
  honestly when the monthly quota is spent.
- **Metering**: every provider call writes `provider_usage` rows (units +
  optional estimated cost); `GET .../usage` aggregates 30 days;
  `GET .../organizations/{org}/limits` returns plan + limits + current usage,
  rendered as the Plan & limits card in Settings.

## What Stripe will drive (not yet)

Plan changes are currently manual (DB edit). The Stripe integration —
checkout, customer portal, `subscriptions` + `billing_events` tables,
webhook route with signature verification mapping price IDs → plans — is
specified here so it plugs into the existing seam (`plan_of()` is the only
place plan is read):

1. Add `STRIPE_SECRET_KEY`/`STRIPE_WEBHOOK_SECRET` (already in `.env.example`).
2. Checkout Session → subscription → webhook `customer.subscription.updated`
   sets `organizations.plan`.
3. Entitlement checks stay unchanged.

No fake billing UI exists; nothing claims a subscription state the system
doesn't have.
