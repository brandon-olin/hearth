# Home Assistant Integration

Control Hearth from Home Assistant — add groceries, create to-dos, check in habits, and read your to-do count — using HA automations or the built-in **Assist** voice assistant. No custom HA component is required: Hearth exposes a plain REST API and HA calls it with `rest_command` and `rest` sensors.

Voice examples once set up:

- *"Hey Google, ask Home Assistant to add milk to the shopping list"*
- *"Assist, create a to-do: call the dentist"*
- *"Assist, how many to-dos do I have today?"*

---

## How it authenticates

Hearth uses **Personal Access Tokens (PATs)** — the same long-lived, scoped, revocable Bearer tokens used for every agent integration (there is no separate "integration token"). You generate one token, scope it to just the domains HA needs, and paste it into your HA config.

A PAT can never do more than your own account can, and only reaches the domains you grant. For HA you need:

| Action | Scope required |
|---|---|
| Add a grocery item | `grocery: write` |
| Create a to-do | `todos: write` |
| Read today's to-do count | `todos: read` (implied by `write`) |
| Check in a habit | `habits: write` |

Everything outside those scopes (your budget, documents, other people's data, minting more tokens) stays unreachable with this token — that is enforced server-side, deny-by-default.

---

## Step 1 — Generate the token

1. In Hearth, go to **Settings → Integrations → Home Assistant**.
2. Click **Generate Home Assistant token**. This creates a PAT named "Home Assistant" pre-scoped to `grocery: write`, `todos: write`, `habits: write`.
3. **Copy the token now** — it is shown once and cannot be retrieved again. If you lose it, revoke it and generate a new one.

> You can also create a token by hand under **Settings → Access tokens** with whichever scopes you like. The Integrations card is just the pre-scoped shortcut.

Your Hearth base URL is whatever you use in the browser, e.g. `http://192.168.1.50:1338` on your LAN, or your Tailscale/Caddy HTTPS hostname if you've set that up.

---

## Step 2 — Find your active shopping list ID

Grocery actions target a specific list. Grab the ID of the list you want HA to add to (usually your one active list):

```bash
curl -s -H "Authorization: Bearer hearth_pat_XXXX" \
  "http://192.168.1.50:1338/grocery-lists?status=active" | jq '.items[] | {id, name}'
```

Copy the `id` of the list you want. If you keep a single standing "Shopping" list this is a one-time step. (Creating and swapping lists is a UI action; HA writes to a fixed list ID.)

---

## Step 3 — Add the REST commands to `configuration.yaml`

Replace `BASE_URL`, `TOKEN`, and `LIST_ID` with your values. In production, store the token in `secrets.yaml` and reference it as `!secret hearth_token`.

```yaml
rest_command:
  hearth_add_grocery:
    url: "BASE_URL/grocery-lists/LIST_ID/items"
    method: POST
    headers:
      Authorization: "Bearer TOKEN"
      Content-Type: "application/json"
    payload: '{"name": "{{ item }}"}'

  hearth_create_todo:
    url: "BASE_URL/todos"
    method: POST
    headers:
      Authorization: "Bearer TOKEN"
      Content-Type: "application/json"
    # due_date is optional; omit the key for an undated to-do.
    payload: '{"title": "{{ title }}", "due_date": "{{ now().strftime(''%Y-%m-%d'') }}"}'
```

The `{{ item }}` / `{{ title }}` placeholders are filled in by whatever calls the command (an automation, a script, or an Assist intent).

---

## Step 4 — Add the "to-dos today" sensor

This polls Hearth for the count of pending to-dos due today and exposes it as `sensor.hearth_todos_today`.

```yaml
sensor:
  - platform: rest
    name: Hearth To-dos Today
    unique_id: hearth_todos_today
    resource_template: "BASE_URL/todos?status=pending&due_date_from={{ now().strftime('%Y-%m-%d') }}&due_date_to={{ now().strftime('%Y-%m-%d') }}"
    headers:
      Authorization: "Bearer TOKEN"
    value_template: "{{ value_json.total }}"
    scan_interval: 300
```

Restart Home Assistant (or reload YAML) after editing `configuration.yaml`.

---

## Step 5 — Wire up voice with Assist intents

Add intent scripts so HA's Assist assistant understands the phrases. `configuration.yaml`:

```yaml
intent_script:
  HearthAddGrocery:
    speech:
      text: "Added {{ item }} to your shopping list."
    action:
      - service: rest_command.hearth_add_grocery
        data:
          item: "{{ item }}"

  HearthCreateTodo:
    speech:
      text: "Created a to-do: {{ title }}."
    action:
      - service: rest_command.hearth_create_todo
        data:
          title: "{{ title }}"

  HearthTodoCount:
    speech:
      text: "You have {{ states('sensor.hearth_todos_today') }} to-dos due today."
```

Then teach Assist the sentences — `custom_sentences/en/hearth.yaml`:

```yaml
language: "en"
intents:
  HearthAddGrocery:
    data:
      - sentences:
          - "add {item} to [the] (shopping list | grocery list)"
  HearthCreateTodo:
    data:
      - sentences:
          - "create a to-do [called] {title}"
          - "add a task [called] {title}"
  HearthTodoCount:
    data:
      - sentences:
          - "how many to-dos do I have [today]"
          - "what's on my list today"
lists:
  item:
    wildcard: true
  title:
    wildcard: true
```

Now *"Assist, add milk to the shopping list"* and *"Assist, how many to-dos do I have today"* work on any Assist surface (the HA app, a Voice PE puck, or an Echo/Nest speaker bridged to HA).

---

## Habit check-in (optional)

Checking in a habit needs the habit's ID and creates an occurrence for today. Look up the habit ID with `GET /habits`, then:

```yaml
rest_command:
  hearth_checkin_habit:
    url: "BASE_URL/habits/HABIT_ID/occurrences"
    method: POST
    headers:
      Authorization: "Bearer TOKEN"
      Content-Type: "application/json"
    payload: '{"scheduled_date": "{{ now().strftime(''%Y-%m-%d'') }}", "status": "completed"}'
```

---

## Testing without hardware

You don't need a physical Echo or a Voice PE puck. Run Home Assistant in Docker and use the **Developer Tools → Actions** panel (or the Assist debug dialog) to fire the commands:

```bash
docker run -d --name homeassistant \
  -v "$PWD/ha-config":/config \
  --network host \
  ghcr.io/home-assistant/home-assistant:stable
```

Then in HA: **Developer Tools → Actions → `rest_command.hearth_add_grocery`**, set `item: milk`, and **Perform action**. Confirm the item appears in Hearth. For voice, open **Settings → Voice assistants → Assist → try the debug box** and type a sentence.

---

## Revoking access

If a token is exposed, or you're decommissioning the HA box:

- **Settings → Access tokens → Revoke** next to the "Home Assistant" token.

Revocation takes effect on the very next request — HA calls immediately return `401 Unauthorized`, and its actions fail with an "unable to connect" style error until you paste in a new token.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `401 Unauthorized` | Token revoked, expired, or mistyped | Generate a fresh token; check `secrets.yaml` |
| `403 Forbidden` on an action | Token lacks that scope | Re-generate with the needed scope (e.g. `todos: write`) |
| `404` when adding groceries | Wrong or deleted `LIST_ID` | Re-run Step 2 to get the current active list ID |
| Sensor shows `unknown` | HA can't reach the base URL | Confirm `BASE_URL` is reachable from the HA host, not just your laptop |
