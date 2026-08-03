# Claude Workload Identity Federation Setup

The **Generate Session Notes** workflow authenticates to the Claude API with
[workload identity federation](https://platform.claude.com/docs/en/manage-claude/workload-identity-federation)
instead of a static `ANTHROPIC_API_KEY` secret. GitHub Actions requests a
short-lived OIDC token from GitHub, and the `anthropic` Python SDK exchanges it
for a Claude API access token that expires within minutes. No long-lived
credential is stored anywhere.

## One-time setup

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

### 3. Verify, then retire the old key

1. Trigger **Generate Session Notes** via *Run workflow* (workflow_dispatch).
   The "Check workload identity configuration" step fails fast with a clear
   message if a variable is missing.
2. Once a run succeeds, delete the `ANTHROPIC_API_KEY` repository secret and
   revoke the key in the Claude console under **Settings → API keys**.

## How the workflow uses it

- The workflow's `permissions` include `id-token: write`, which lets the job
  request an OIDC token from GitHub.
- A step fetches that token with audience `https://api.anthropic.com` and
  writes it to `$RUNNER_TEMP/claude-oidc-token`.
- The `anthropic` Python SDK reads `ANTHROPIC_FEDERATION_RULE_ID`,
  `ANTHROPIC_ORGANIZATION_ID`, `ANTHROPIC_SERVICE_ACCOUNT_ID`, and
  `ANTHROPIC_IDENTITY_TOKEN_FILE` from the environment and performs the
  JWT-bearer exchange (`POST /v1/oauth/token`) automatically when
  `anthropic.Anthropic()` is constructed without an API key — no code changes
  were needed in `scripts/automate_session.py`.

Note: if `ANTHROPIC_API_KEY` is set it takes precedence over federation, so
don't set both in the workflow.

## Local development

Nothing changes locally — `scripts/automate_session.py` still works with an
`ANTHROPIC_API_KEY` exported in your shell (use a personal key, separate from
the revoked CI key), or with `--local` for subscription billing.

## References

- [Workload identity federation overview](https://platform.claude.com/docs/en/manage-claude/workload-identity-federation)
- [WIF with GitHub Actions](https://platform.claude.com/docs/en/manage-claude/wif-providers/github-actions)
- [WIF reference (env vars, errors)](https://platform.claude.com/docs/en/manage-claude/wif-reference)
