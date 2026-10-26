# Accounts, notifications, and explanation fixes

## Round 2: admin access, real email, root-cause categories

### Admin access
An **admin** is an account that is owner of every workspace. Admins get an
**Admin console** (sidebar, last item) listing every registered account. From
there they can make someone admin, operator, or viewer in all workspaces at
once, or remove their access. There are three ways to get an admin:

1. **Server-configured admin (recommended).** Put these in the repository-root
   `.env` (now loaded automatically) and restart the API:
   ```
   CAPSTONE_ADMIN_EMAIL=admin@yourdomain.com
   CAPSTONE_ADMIN_PASSWORD=choose-a-strong-password
   ```
   The account is created if missing, or promoted if it already exists (its
   password is then left alone). Sign in with it on the normal sign-in screen.
2. **Promote an existing account from a terminal** (repository root, same
   environment as the API):
   ```
   python -m scripts.manage_users promote you@example.com
   python -m scripts.manage_users list
   python -m scripts.manage_users reset-password you@example.com
   ```
3. The **first account registered** on a fresh database becomes admin.

Safeguards: you cannot remove your own admin access, and every workspace
always keeps at least one owner.

### Email
* **From the dashboard:** Settings → *Alert email account*. Choose Gmail,
  Outlook, or another SMTP server, enter the sender address and password, and
  save. Then use **Send test** on the EMAIL channel; the test goes only to you.
  Settings are per workspace. The password is encrypted at rest (Fernet) and
  never returned by the API. Only owners can change it.
* **Gmail** needs an *App Password*, not your normal password: turn on 2-Step
  Verification, then create one at https://myaccount.google.com/apppasswords.
* **From `.env`:** `DEMO_EMAIL_SENDER`, `DEMO_EMAIL_PASSWORD`, plus optional
  `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURITY` (`starttls` | `ssl` | `none`) and
  `SMTP_USERNAME`. Workspace settings take priority.
* **Recipients:** real alerts go to the workspace's saved recipient list if
  one is set, otherwise to every member of the workspace.
* `.env` is now gitignored. It previously was not, so credentials placed there
  could have been committed.

### Root-cause analysis
RCA used to return **UNKNOWN** for most attack scenarios. The score rules need
a final score ≥ 0.75, and the security rules look for indicator names the
generator never produces. The hypothesis engine now also uses the threat
signature match. A MEDIUM or HIGH match adds a ranked candidate with a real
category (mapping in `phase3/rca/hypothesis_rules.yaml` → `threat_categories`),
and the score-based candidate is kept alongside it. Eleven categories were
added to the knowledge base (`kb_version` 2.2.0), e.g. IDENTITY_MISUSE,
UNUSUAL_DATA_TRANSFER, CROSS_RESOURCE_ACCESS, RESOURCE_ABUSE,
DESTRUCTIVE_ACTIVITY, SERVICE_DISRUPTION. Category names never echo the
scenario name, which the existing tests require.

Incidents stored before this change are backfilled when read. If their
evidence matches a signature, the category is shown; nothing stored is
rewritten. To regenerate everything cleanly, use *Reset demo tenant to
baseline* on the Live demo page and inject again.

---

## Round 1

This change adds real multi-user sign-in, makes notifications actually deliver
(or say plainly why they can't), and repairs the incident explanation. It also
fixes the trained model failing to load on any machine other than the one that
wrote the model manifest.

## Run it

```bash
# backend (from the repository root)
export PLATFORM_JWT_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
python -m uvicorn phase3.api.app:app --host 127.0.0.1 --port 8001

# frontend
cd frontend && npm install && npm run dev
```

On Windows PowerShell use `$env:PLATFORM_JWT_SECRET = "<a long random string>"`.
If you skip it, the API generates `.capstone_dev_jwt_secret` (gitignored) so
sessions survive restarts on your machine.

Open http://127.0.0.1:5173. You land on the sign-in screen.

1. **Create account.** The first account becomes **OWNER** of the five demo
   workspaces (Google, Microsoft, Amazon, Oracle, Acme).
2. Every later account joins as **VIEWER** (change with `CAPSTONE_SIGNUP_ROLE`).
3. An owner promotes people on **Users** (owner / operator / viewer).

| Role | Can do |
|---|---|
| Owner | Everything below, plus add/remove members and change roles |
| Operator | Acknowledge/resolve/reopen incidents, send test notifications |
| Viewer | Read alerts, incidents, explanations |

An existing database keeps working: the old `demo-user` stays in place for
data, but it cannot sign in. Register a real account instead.

## What changed

### Authentication (backend)
* `POST /auth/register` and `POST /auth/login` hash passwords with bcrypt and
  return a signed JWT. Before this, `/auth/login` ignored the password and
  returned a fixed `demo-access-token`. `GET /auth/me` returns the user and
  their memberships.
* Every tenant-scoped route now derives the user from
  `Authorization: Bearer <token>`. The `X-User-Id` header used to be trusted on
  its own, so anyone could claim any user. Sending a header that disagrees with
  the token is rejected (403).
* `/stats/summary`, `/alerts/recent`, `/demo/pause|resume|status` and the
  legacy explain endpoint had **no** membership check at all; they now do.
* `/tenants` returns only the workspaces the user belongs to.
* New member endpoints: `GET/POST /members`, `PATCH/DELETE /members/{user_id}`
  (owner only). The last owner of a workspace cannot be demoted or removed.
* The live WebSocket takes `?token=` and only forwards alerts for the user's
  workspaces. Previously every browser received every tenant's alerts.
* `AuthService.register` generated ids by counting an in-memory dict; with a
  database that was always `user-1`, so the second sign-up crashed. A malformed
  stored hash now counts as a wrong password instead of a 500.

### Authentication (frontend)
* New sign-in / create-account screen with validation and server error messages.
* `AuthProvider` restores and revalidates the session on load. An expired or
  tampered token sends the user back to sign-in with a notice.
* Sidebar shows the signed-in email and role; top bar switches workspace.
* **Users** page: real member list, role changes, add by email, remove.
* All API calls go through one client that attaches the token and tenant.
  Onboarding calls previously sent no tenant header, so they failed against the
  real API.

### Notifications
* **Email** goes to every member of the workspace (or `DEMO_EMAIL_RECIPIENT`).
  It used to go to made-up `*.internal` addresses that can never receive mail.
  SMTP now runs off the event loop, so a slow Gmail handshake no longer freezes
  the API, and the email links straight to the incident.
* **Slack** posts to `SLACK_WEBHOOK_URL`. It used to report "posted to
  #security-alerts" without sending anything.
* **Webhook** (HMAC-signed) and **PagerDuty** can be configured too.
* Unconfigured channels show **Not configured** and are never reported as sent.
* `GET /notifications/channels` and `POST /notifications/test` power a channel
  panel on Settings, Connections, and the onboarding *Notification setup* /
  *Test notification* steps (which used to be "mark complete" only).
* The chosen channel's real result is saved on the incident, so the
  **Response** tab shows it.
* **In-app:** a bell in the top bar with unread count, toasts for new alerts in
  the active workspace, and optional desktop notifications.

Environment variables (see `.env.example`):

| Variable | Channel |
|---|---|
| `DEMO_EMAIL_SENDER`, `DEMO_EMAIL_PASSWORD` | Email (Gmail app password; see `docs/email_setup.md`) |
| `DEMO_EMAIL_RECIPIENT` | Optional override for email recipients |
| `SLACK_WEBHOOK_URL` | Slack incoming webhook |
| `ALERT_WEBHOOK_URL`, `ALERT_WEBHOOK_SECRET` | Generic signed webhook |
| `PAGERDUTY_ROUTING_KEY` | PagerDuty Events v2 |
| `CAPSTONE_DASHBOARD_URL` | Link target used in emails and Slack |

### Explanation
* **Category vs. explanation mismatch.** The page showed the RCA category as
  "Category" next to a threat-pattern explanation, e.g. *Category: UNKNOWN*
  above *Possible cloud credential misuse*. These are two separate results. The
  page now shows **Change type** (the RCA category) and **Matched pattern**
  (threat signature + confidence) side by side, and says so in the Explanation
  tab.
* Text cleanup in `ExplanationBuilder`:
  * scores are rounded (`drift=0.6759999999999999` → `0.68`)
  * Python dicts no longer leak into the text (`{'score': ...}`)
  * internal keys such as `changed_features.api_calls.increase` become
    "api calls increased"
  * internal field names were dropped from the evidence
* List sections (checks, stages, mitigation, resolution criteria, reading) are
  one item per line and render as real lists. Further-reading URLs are links
  (https only; everything else stays plain text).
* Evidence tab: observed/baseline windows are labelled rows instead of raw JSON.

### Model loading
`model_registry/artifacts_manifest.json` version 0.2.0 stores an absolute
`C:\Users\Himank\...` path. On any other machine the loader fell back to the
0.1.0 checkpoint, crashed on a vocab size mismatch, and silently used baseline
scores. The loader now re-anchors the path at `model_registry/`, so the trained
encoder loads (`[ML Engine] Loaded T-STCC PyTorch encoder model`).

## Tests
* Backend: `python -m pytest tests`. New suites cover auth
  (`test_auth_flow.py`), notifications (`test_alert_notifications.py`), and
  explanation readability. Older route tests run in legacy header mode via
  `conftest.py` (`CAPSTONE_AUTH_REQUIRED=false`).
* Frontend: `npm run lint`, `npm run typecheck`, `npm test`,
  `npm run test:e2e` (mock mode, includes register/sign-out and notification
  flows).

## Known limits
* No password reset or email verification; no login rate limiting.
* `/demo/reset` does not clear escalation-suppression memory (pre-existing).
* Hypothesis rules for CREDENTIAL_THEFT etc. never fire, because the generator
  emits `metric_family:*` features rather than the named indicators the rules
  expect. The threat matcher covers these patterns instead, and the UI now
  shows that honestly.
