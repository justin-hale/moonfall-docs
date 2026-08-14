# Claude Workload Identity Federation Setup

The **Generate Session Notes** workflow authenticates to the Claude API with
[workload identity federation](https://platform.claude.com/docs/en/manage-claude/workload-identity-federation)
instead of a static `ANTHROPIC_API_KEY` secret. GitHub Actions requests a
short-lived OIDC token from GitHub, and the `anthropic` Python SDK exchanges it
for a Claude API access token that expires within minutes. No long-lived
credential is stored anywhere.

For a smooth handoff, the workflow also supports a **fallback API key**
(`ANTHROPIC_FALLBACK_API_KEY` secret). Auth mode is selected per run:

1. If the three federation repository variables are set → **federation** (the
   fallback key is not exposed to the script at all).
2. Otherwise, if `ANTHROPIC_FALLBACK_API_KEY` is set → **API key**, with a
   warning in the run log.
3. Neither configured → the run fails fast with instructions.

This means the pipeline keeps working before the console-side setup is done,
and rolling back from federation is just deleting the three repo variables.

## One-time setup

### 0. Create the prod and dev keys (handoff safety net)

In the Claude console under **Settings → API keys**, create two **new** keys
(don't reuse the old CI key):

| Console key name | Purpose | Where it lives |
|---|---|---|
| `topherhooper-moonfall-prod` | CI fallback for the Generate Session Notes workflow | GitHub repository secret `ANTHROPIC_FALLBACK_API_KEY` (**Settings → Secrets and variables → Actions → Secrets**) |
| `topherhooper-moonfall-dev` | Local development / testing scripts by hand | Your shell only (`export ANTHROPIC_API_KEY=...`) — never added to GitHub |

Separate keys mean CI and local usage are distinguishable in console usage
reports, and either can be revoked without affecting the other.

Then delete the old `ANTHROPIC_API_KEY` repository secret and revoke that old
key in the console — the workflow no longer references it.

### 1. Create the federation rule in the Claude console

Go to <https://platform.claude.com/settings/workload-identity-federation> and
click **Connect workload**, then:

1. Select the **GitHub Actions** tile (pre-fills the issuer).
2. Confirm/enter these values:
   - **Issuer URL:** `https://token.actions.githubusercontent.com`
   - **JWKS source:** `discovery`
   - **Subject prefix:** `repo:justin-hale/moonfall-docs:ref:refs/heads/main`
     (the workflow only runs on pushes to `main` and manual dispatches from
     `main`, so this locks tokens to that)
   - **Audience:** `https://api.anthropic.com`
   - **Claim `repository_owner`:** `justin-hale` (defense in depth)
   - **Scope:** `workspace:developer`
   - **Token lifetime:** `600` seconds is plenty for a session-notes run
3. Optionally click **Verify issuer**, then **Create**.
4. Note the IDs the wizard shows:
   - Federation rule ID (`fdrl_...`)
   - Service account ID (`svac_...`)
   - Your organization ID (UUID) is under **Settings → Organization**.

### 2. Set the repository variables on GitHub

These are identifiers, not secrets, so they go in **Variables** (not Secrets):

**Settings → Secrets and variables → Actions → Variables → New repository variable**

| Variable | Value |
|---|---|
| `ANTHROPIC_FEDERATION_RULE_ID` | `fdrl_...` from step 1 |
| `ANTHROPIC_ORGANIZATION_ID` | organization UUID |
| `ANTHROPIC_SERVICE_ACCOUNT_ID` | `svac_...` from step 1 |

(If the federation rule covers multiple workspaces, also add
`ANTHROPIC_WORKSPACE_ID` and pass it through in the workflow.)

### 3. Verify federation, then retire the fallback

1. Trigger **Generate Session Notes** via *Run workflow* (workflow_dispatch)
   and confirm the "Select Claude API auth mode" step logs
   `Auth mode: workload identity federation`.
2. Once federation runs are proven out, delete the
   `ANTHROPIC_FALLBACK_API_KEY` secret and revoke the
   `topherhooper-moonfall-prod` key in the console — or keep them around as a
   break-glass fallback; the key is only used when the federation variables
   are absent. The `topherhooper-moonfall-dev` key is unaffected either way.

To **roll back** to the fallback key at any point, delete (or blank) the three
federation repository variables — the next run automatically uses the key.

## How the workflow uses it

- The "Select Claude API auth mode" step picks federation when the three repo
  variables are set, otherwise the fallback key, and fails fast if neither is
  configured.
- The workflow's `permissions` include `id-token: write`, which lets the job
  request an OIDC token from GitHub.
- In federation mode, a step fetches that token with audience
  `https://api.anthropic.com` and writes it to `$RUNNER_TEMP/claude-oidc-token`.
- The `anthropic` Python SDK reads `ANTHROPIC_FEDERATION_RULE_ID`,
  `ANTHROPIC_ORGANIZATION_ID`, `ANTHROPIC_SERVICE_ACCOUNT_ID`, and
  `ANTHROPIC_IDENTITY_TOKEN_FILE` from the environment and performs the
  JWT-bearer exchange (`POST /v1/oauth/token`) automatically when
  `anthropic.Anthropic()` is constructed without an API key — no code changes
  were needed in `scripts/automate_session.py`.

Note: an `ANTHROPIC_API_KEY` env var takes precedence over federation in the
SDK, so the generate step exposes exactly one mechanism to the script: in
federation mode the fallback key is never exported; in fallback mode the
federation variables are unset.

## Local development

Nothing changes locally — `scripts/automate_session.py` still works with an
`ANTHROPIC_API_KEY` exported in your shell. Use the `topherhooper-moonfall-dev`
key for this (never the prod/CI key), or `--local` for subscription billing.

## References

- [Workload identity federation overview](https://platform.claude.com/docs/en/manage-claude/workload-identity-federation)
- [WIF with GitHub Actions](https://platform.claude.com/docs/en/manage-claude/wif-providers/github-actions)
- [WIF reference (env vars, errors)](https://platform.claude.com/docs/en/manage-claude/wif-reference)
