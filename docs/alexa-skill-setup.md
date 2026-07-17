# Amazon Alexa Skill

Control Hearth by voice on any Echo device — add groceries, create to-dos, check off habits, and ask how many to-dos you have today — with a **custom Alexa skill** you build and self-publish. The skill stays private to your own Amazon account; it never has to be listed in the public Alexa Skill Store.

Voice examples once set up:

- *"Alexa, ask Hearth to add milk to my shopping list"*
- *"Alexa, ask Hearth to create a to-do: call the dentist"*
- *"Alexa, ask Hearth to check off flossing"*
- *"Alexa, ask Hearth how many to-dos I have today"*

---

## How it fits together

```
Echo device ──▶ Alexa cloud ──▶ (account linking) ──▶ POST /voice/alexa on your Hearth
                     │                                        │
              your custom skill                    resolves the linked PAT,
              (intents + slots)                     runs the intent, speaks back
```

Alexa sends every request as a JSON envelope to your skill's **HTTPS endpoint** — the Hearth API route `POST /voice/alexa`. Hearth authenticates the request using the **account-linking token** Alexa attaches, runs the matching action through the normal service layer (idempotent, household-scoped, audited), and returns a short spoken reply.

There is **no Lambda to write**. The endpoint is already part of the Hearth API. You point the skill's endpoint at your Hearth URL and connect the two with account linking.

---

## How it authenticates — account linking

Hearth uses **Personal Access Tokens (PATs)** for every agent integration — long-lived, scoped, revocable Bearer tokens. A PAT can never do more than the member who owns it, and only reaches the domains you grant it. Alexa delivers a PAT to Hearth on every request through **account linking**, in one of two ways depending on your deployment tier:

| Tier | How the token gets into Alexa |
|---|---|
| **Cloud** (hosted) | Alexa runs the **OAuth 2.1** account-linking flow (security-007). The user taps *Link Account* in the Alexa app, logs into Hearth, approves the scopes, and Alexa stores the OAuth-minted PAT. This is the consumer flow. |
| **Local / self-hosted** | There is no OAuth server. Use Alexa's **"Auth Code Grant" with a static token**, or the simplest path: paste a hand-created PAT as the account-linking access token (details below). |

Scopes needed for the four intents:

| Intent | Scope required |
|---|---|
| `AddGroceryItem` | `grocery: write` |
| `CreateTodo` | `todos: write` |
| `CheckInHabit` | `habits: write` |
| `QueryTodos` | `todos: read` (implied by any `write`) |

Everything outside those scopes (budget, documents, other members' private data, minting more tokens) stays unreachable — enforced server-side, deny-by-default, exactly as for Home Assistant and MCP.

---

## Step 1 — Create the skill in the Alexa Developer Console

1. Go to <https://developer.amazon.com/alexa/console/ask> and sign in with your Amazon account.
2. **Create Skill** → name it `Hearth` → choose **Custom** model and **Provision your own** hosting.
3. Start from a **Scratch** template.
4. Set the skill's **Invocation Name** to `hearth` (this is the wake phrase: "ask *hearth* to…").

---

## Step 2 — Define the interaction model

In the console's **JSON Editor** (Build tab → Interaction Model → JSON Editor), paste the model below. It declares the four intents and their slots. `AMAZON.HelpIntent`, `AMAZON.StopIntent`, and `AMAZON.CancelIntent` are handled by Hearth automatically.

```json
{
  "interactionModel": {
    "languageModel": {
      "invocationName": "hearth",
      "intents": [
        { "name": "AMAZON.HelpIntent", "samples": [] },
        { "name": "AMAZON.StopIntent", "samples": [] },
        { "name": "AMAZON.CancelIntent", "samples": [] },
        { "name": "AMAZON.FallbackIntent", "samples": [] },
        {
          "name": "AddGroceryItem",
          "slots": [{ "name": "item", "type": "AMAZON.Food" }],
          "samples": [
            "add {item} to my shopping list",
            "add {item} to the grocery list",
            "put {item} on the shopping list",
            "add {item}"
          ]
        },
        {
          "name": "CreateTodo",
          "slots": [{ "name": "task", "type": "AMAZON.SearchQuery" }],
          "samples": [
            "create a to-do {task}",
            "create a to-do to {task}",
            "add a to-do to {task}",
            "remind me to {task}"
          ]
        },
        {
          "name": "CheckInHabit",
          "slots": [{ "name": "habit", "type": "AMAZON.SearchQuery" }],
          "samples": [
            "check off {habit}",
            "check in {habit}",
            "mark {habit} done",
            "I did {habit}"
          ]
        },
        {
          "name": "QueryTodos",
          "slots": [],
          "samples": [
            "how many to-dos do I have today",
            "how many to-dos are due today",
            "what's on my to-do list today"
          ]
        }
      ]
    }
  }
}
```

> `AMAZON.SearchQuery` slots (used for `task` and `habit`) can't share an utterance with other slots, which is why each sample has exactly one. **Save Model** and **Build Model**.

---

## Step 3 — Point the skill's endpoint at Hearth

1. Build tab → **Endpoint** → choose **HTTPS**.
2. **Default Region** → enter your Hearth Alexa URL: `https://YOUR_HEARTH_HOST/voice/alexa`.
   - Cloud tier: your public hostname, e.g. `https://hearth.example.com/voice/alexa`.
   - Self-hosted: your Caddy/Tailscale HTTPS hostname. Alexa **requires HTTPS with a certificate trusted by Amazon** — a plain `http://LAN-IP` endpoint will not work. A Tailscale Funnel or Caddy Let's Encrypt cert satisfies this.
3. For the SSL certificate type, choose **"My development endpoint has a certificate from a trusted certificate authority"**.

### Turn on request signature verification (recommended for a public endpoint)

Because the endpoint is reachable by anyone who learns the URL, enable Hearth's Alexa request verification so only genuinely Amazon-signed requests are honored. In your Hearth API environment:

```bash
ALEXA_SKILL_ID=amzn1.ask.skill.xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx   # from the console's skill settings
ALEXA_VERIFY_SIGNATURE=true                                          # verify Amazon's signature + timestamp
```

- `ALEXA_SKILL_ID` makes Hearth reject any request that doesn't name **your** skill. Safe to set on every tier.
- `ALEXA_VERIFY_SIGNATURE=true` makes Hearth validate Amazon's request signature and timestamp on each call. It needs outbound HTTPS to Amazon's S3 certificate host, so enable it on the internet-facing **cloud** tier (and self-hosted if your endpoint is internet-exposed). Leave it off for a LAN-only test where the extra round-trip isn't wanted.

Even with verification off, every intent still requires a valid account-linked PAT, so an unauthenticated request can do nothing but hear "link your account."

---

## Step 4 — Configure account linking

Build tab → **Account Linking** → enable it.

### Cloud tier (OAuth 2.1)

1. **Auth Grant Type** → *Auth Code Grant*.
2. **Authorization URI** → `https://YOUR_HEARTH_HOST/oauth/authorize`
3. **Access Token URI** → `https://YOUR_HEARTH_HOST/oauth/token`
4. **Client ID / Client Secret** → register a client first with dynamic client registration and use the returned values:
   ```bash
   curl -sX POST https://YOUR_HEARTH_HOST/oauth/register \
     -H 'Content-Type: application/json' \
     -d '{
       "client_name": "Alexa",
       "redirect_uris": ["https://layla.amazon.com/api/skill/link/YOUR_VENDOR_ID"],
       "token_endpoint_auth_method": "client_secret_post",
       "grant_types": ["authorization_code"]
     }'
   ```
   Alexa shows its exact **Redirect URLs** on the Account Linking page — copy them into `redirect_uris` above before registering.
5. **Scope** → `grocery:write todos:write habits:write`
6. Save. In the Alexa app, open the skill and tap **Link Account** — you'll be sent to Hearth to log in and approve. Alexa stores the minted PAT and attaches it to every request.

### Local / self-hosted tier (paste a PAT)

The OAuth endpoints return 404 off the cloud tier by design, so use the token directly:

1. In Hearth, **Settings → Access tokens** → create a token named `Alexa`, scoped to `grocery: write`, `todos: write`, `habits: write`. **Copy it now** — it's shown once.
2. In the console, set **Auth Grant Type** → *Auth Code Grant* is not available without an OAuth server; instead use a linking helper or a static-token setup that places `hearth_pat_XXXX` into the request's `accessToken`. The simplest reliable path for a private, single-user skill is to run the cloud-tier OAuth flow on any host set to `DEPLOYMENT_TIER=cloud`, or to front the skill with a tiny Lambda that adds `Authorization` — but for pure local testing you can also use the **Alexa simulator** (Step 6) with a linked account from a cloud instance.

> For most self-hosters the practical setup is: run Hearth on the cloud tier (or a small VPS with `DEPLOYMENT_TIER=cloud`) so the OAuth account-linking flow is available, then point Echo devices at it. A LAN-only Echo skill without any OAuth server is an Amazon limitation, not a Hearth one.

---

## Step 5 — Talk to it

On any Echo signed into your Amazon account, once account linking shows **Hearth** as linked in the Alexa app:

- *"Alexa, ask Hearth to add milk to my shopping list."* → "Added milk to your shopping list."
- *"Alexa, ask Hearth to create a to-do: call the dentist."* → "I've added a to-do: call the dentist."
- *"Alexa, ask Hearth to check off flossing."* → "Nice work. I've checked off Floss for today."
- *"Alexa, ask Hearth how many to-dos I have today."* → "You have one to-do due today."

Adding the same item twice is idempotent — you'll hear "milk is already on your shopping list," and no duplicate is created.

---

## Step 6 — Test without an Echo

The console's **Test** tab (set to *Development*) runs the skill from the browser. Type or speak *"ask hearth how many to-dos I have today"* and watch the JSON request/response. Account linking must be completed in the Alexa app first (the simulator uses the same linked token).

You can also exercise the endpoint directly with a crafted envelope and a real PAT — useful for verifying Hearth before touching the console:

```bash
curl -sX POST https://YOUR_HEARTH_HOST/voice/alexa \
  -H 'Content-Type: application/json' \
  -d '{
    "version": "1.0",
    "context": {"System": {
      "application": {"applicationId": "amzn1.ask.skill.YOUR_SKILL_ID"},
      "user": {"accessToken": "hearth_pat_XXXX"}
    }},
    "request": {
      "type": "IntentRequest",
      "timestamp": "2026-07-17T12:00:00Z",
      "intent": {"name": "AddGroceryItem", "slots": {"item": {"name": "item", "value": "milk"}}}
    }
  }' | jq '.response.outputSpeech.text'
```

(With `ALEXA_VERIFY_SIGNATURE=true` this hand-crafted request is rejected — it isn't Amazon-signed. Turn verification off to test with curl, or test through the console/simulator which sends real signed requests.)

---

## Step 7 — (Optional) Submit as a private skill

To use the skill on Echo hardware beyond the developer simulator, it must pass certification — but it can be submitted as a **private skill available only to your own Amazon account**, never listed publicly:

1. **Distribution** tab → fill in the minimal store listing fields (they aren't shown publicly for a private skill).
2. **Certification** → submit. Private skills for your own account clear certification quickly since they aren't publicly discoverable.
3. Once certified, the skill is enabled on all Echo devices signed into your account.

---

## Revoking access

Revoke the `Alexa` token any time under **Settings → Access tokens** (or delete the OAuth client on the cloud tier). Alexa requests then fail authentication, and Hearth responds gracefully — *"I'm having trouble connecting to your Hearth account. Try re-linking it in the Alexa app."* — with a Link Account card, rather than an error. Nothing is written.

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| "To use Hearth, link your account in the Alexa app" | No token reached Hearth — account linking isn't completed, or the link expired. Re-link in the Alexa app. |
| "I'm having trouble connecting to your Hearth account" | The linked token is invalid, expired, or revoked. Create/link a new one. |
| "Sorry, your account doesn't have permission to do that" | The token's scopes (or the member's household permissions) don't allow that action. Re-scope the token or adjust household permissions. |
| Endpoint returns 400 in the console | Signature verification is on and the request wasn't validly signed, the `applicationId` doesn't match `ALEXA_SKILL_ID`, or the body was malformed. Confirm the skill ID and that the console is sending real requests. |
| "You don't have a shopping list yet" | Create an active grocery list in the Hearth app first; voice adds to your most recent active list. |
```
