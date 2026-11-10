# AETHER integration contract

VERUM exposes a versioned, read-only integration surface for AETHER Multi-Chain Intelligence.

## Base URL

    https://YOUR_VERUM_API_DOMAIN/api/v1/integration

## Authentication

Use a Supabase Auth access JWT in the Authorization: Bearer <access_token> header.

For production, authenticate AETHER server-to-server using a dedicated integration identity or the same VERUM user identity that owns the paper records. Store access and refresh tokens in AETHER's server-side secret manager. Never place tokens in browser code, source control, logs or public configuration.

The API uses the Supabase publishable key only as the project API identifier. Row Level Security scopes private research and paper records to the authenticated user. Do not use a Supabase service-role key in AETHER.

## Read-only endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | /signals | Latest qualified or rejected signal assessments |
| GET | /tokens/{mint} | Token security, market and evidence provenance |
| GET | /strategies/performance | Saved strategy research and holdout metrics |
| GET | /paper/results | Authenticated user's paper positions and trade results |

All responses include timestamps and source provenance where available. UNKNOWN, INSUFFICIENT_DATA, WAIT and BLOCKED are meaningful states. Consumers must not convert them into BUY or SAFE.

## Signal response principles

- status: BUY, WAIT, BLOCKED or INSUFFICIENT_DATA.
- confidence: evidence-derived score, not a win probability.
- evidence_coverage: fraction of required evidence fields observed.
- strategy_validation: VALIDATED or UNVALIDATED.
- quote_at / data_freshness: quote and source freshness.
- provenance: source, status and fetch timestamp.
- reasons: deterministic reasons for qualification or rejection.

## Security model

- GET-only integration routes are exposed for AETHER.
- There is no live-trading endpoint in this release.
- Paper-trade creation and closure remain separate user-authenticated application routes.
- RLS isolates paper_accounts, paper_positions, paper_trades, research_runs, alerts and user_settings.
- The AETHER identity sees only rows permitted by its authenticated Supabase user ID.

## Versioning and errors

The API prefix is /api/v1. Additive response fields may be introduced without changing existing field meanings. Breaking schema changes require a new version prefix.

Common errors:
- 401: missing or invalid Supabase Auth session.
- 403: RLS denies access.
- 409: risk guard or account-state conflict.
- 422: invalid mint, wallet or request parameters.
- 503: database/provider unavailable.
- 504: upstream timeout.

## Initial connection checklist

1. Create or designate a Supabase Auth identity for AETHER.
2. Ensure the identity is associated with the paper data it is meant to read.
3. Authenticate on AETHER's backend and obtain an access token.
4. Store the refresh token securely and renew access tokens server-side.
5. Call the GET endpoints with the bearer token.
6. Treat every non-PASS security assessment and every stale quote as non-actionable.
