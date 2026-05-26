#!/usr/bin/env python3
"""
seed_test_data.py — Comprehensive test data seeder for Hearth.

Seeds all major domains for test@hearth.local:
  - Tags
  - Collections (Journal)
  - Journal entries (notes in Journal collection, with wikilinks/tags)
  - Notes (philosophical, with wikilinks/tags)
  - Workouts (last ~3 months)
  - Habits (journaling, exercise, walking, meditation) with occurrences
  - Grocery lists (last ~3 months, archived + active)
  - Goals (financial, fitness, creative)
  - Budget (seed profiles, checking + savings accounts, categories, transactions)
  - Projects (creative writing, kitchen renovation, side hustle) with sub-projects + todos
  - Calendar events (past 2 months + next month)
  - Documents (travel, learning, vehicle, home improvement)

Usage:
  cd /path/to/life-dashboard
  python seed_test_data.py [--host http://localhost:1338] [--email test@hearth.local] [--password password]
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib import request as urllib_request
from urllib.error import HTTPError
from urllib.parse import urlencode

# ── CLI args ──────────────────────────────────────────────────────────────────

parser = argparse.ArgumentParser(description="Seed Hearth test data")
parser.add_argument("--host", default="http://localhost:1338")
parser.add_argument("--email", default="test@hearth.local")
parser.add_argument("--password", default="password")
args = parser.parse_args()

BASE = args.host.rstrip("/")
EMAIL = args.email
PASSWORD = args.password

# ── Helpers (stdlib-only HTTP client) ────────────────────────────────────────

_headers: dict[str, str] = {"Content-Type": "application/json"}

def _request(method: str, path: str, body: dict | None = None,
             params: dict | None = None) -> tuple[int, dict | list]:
    url = f"{BASE}{path}"
    if params:
        url += "?" + urlencode({k: v for k, v in params.items() if v is not None})
    data = json.dumps(body).encode() if body is not None else None
    req = urllib_request.Request(url, data=data, headers=_headers, method=method)
    try:
        with urllib_request.urlopen(req) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw.strip() else {}
    except HTTPError as e:
        body_text = e.read().decode()[:200]
        return e.code, {"_error": body_text}

def login(email: str, password: str) -> str:
    status, data = _request("POST", "/auth/login", {"email": email, "password": password})
    if status != 200:
        print(f"❌  Login failed for {email}: {status} {data.get('_error', data)}")
        sys.exit(1)
    token = data["access_token"]
    print(f"✅  Logged in as {email}")
    return token

def set_token(token: str):
    _headers["Authorization"] = f"Bearer {token}"

def post(path: str, body: dict) -> dict:
    status, data = _request("POST", path, body)
    if status not in (200, 201):
        print(f"  ⚠️  POST {path} → {status}: {data.get('_error', str(data))[:200]}")
        return {}
    return data  # type: ignore[return-value]

def patch(path: str, body: dict) -> dict:
    status, data = _request("PATCH", path, body)
    if status not in (200, 201):
        print(f"  ⚠️  PATCH {path} → {status}: {data.get('_error', str(data))[:200]}")
        return {}
    return data  # type: ignore[return-value]

def get(path: str, params: dict | None = None) -> dict | list:
    status, data = _request("GET", path, params=params)
    if status != 200:
        print(f"  ⚠️  GET {path} → {status}: {data.get('_error', str(data))[:200]}")
        return {}
    return data  # type: ignore[return-value]

def days_ago(n: int) -> date:
    return (date.today() - timedelta(days=n))

def days_from_now(n: int) -> date:
    return (date.today() + timedelta(days=n))

def dt_days_ago(n: int, hour: int = 9) -> str:
    """ISO datetime string N days ago at a given hour (UTC)."""
    d = datetime.now(timezone.utc) - timedelta(days=n)
    return d.replace(hour=hour, minute=0, second=0, microsecond=0).isoformat()

def dt_days_from_now(n: int, hour: int = 9) -> str:
    d = datetime.now(timezone.utc) + timedelta(days=n)
    return d.replace(hour=hour, minute=0, second=0, microsecond=0).isoformat()

def ok(label: str, obj: dict) -> bool:
    if obj and obj.get("id"):
        print(f"  ✅  {label}")
        return True
    print(f"  ❌  {label} (no id in response)")
    return False

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

token = login(EMAIL, PASSWORD)
set_token(token)

# ── 1. Tags ───────────────────────────────────────────────────────────────────
print("\n📌  Creating tags...")
TAG_DEFS = [
    ("philosophy", "#7c3aed"),
    ("stoicism", "#6d28d9"),
    ("identity", "#4f46e5"),
    ("creativity", "#0891b2"),
    ("fitness", "#059669"),
    ("nutrition", "#16a34a"),
    ("productivity", "#d97706"),
    ("finance", "#dc2626"),
    ("learning", "#2563eb"),
    ("travel", "#0284c7"),
    ("mindfulness", "#7c3aed"),
    ("writing", "#db2777"),
    ("home", "#b45309"),
    ("career", "#475569"),
    ("reflection", "#6b7280"),
]

tags: dict[str, str] = {}  # name → id
for name, color in TAG_DEFS:
    t = post("/tags", {"name": name, "color": color})
    if t.get("id"):
        tags[name] = t["id"]
        print(f"  ✅  tag: {name}")
    else:
        # might already exist — try fetching
        existing = get("/tags", {"search": name})
        for item in (existing.get("items") or []):
            if item["name"] == name:
                tags[name] = item["id"]
                print(f"  ↩️  tag exists: {name}")

# ── 2. Journal collection ─────────────────────────────────────────────────────
print("\n📚  Creating Journal collection...")
journal_col = post("/collections", {
    "name": "Journal",
    "icon": "BookOpenText",   # BookOpen is already used by the Notes nav item; BookOpenText is distinct
    "domain": "notes",
    "show_in_nav": True,
    "sort_order": 0,
})
ok("Journal collection", journal_col)
journal_col_id = journal_col.get("id")

# ── 3. Journal entries (notes in Journal collection) ──────────────────────────
print("\n📓  Creating journal entries...")

JOURNAL_ENTRIES = [
    # (days_ago, title, content_md, tag_names)
    (90, "Starting fresh", """Today I've decided to commit to journaling every day. Not sure what will come of it, but it feels important. [[Consistency over perfection]] seems to be the key.

#reflection #philosophy

The morning was quiet. Drank my coffee on the porch and watched the birds. There's something meditative about it.

**What I'm grateful for today:**
- The sunlight through the kitchen window
- A good night's sleep
- The fact that I started this

Tags: [[stoicism]] [[mindfulness]]""", ["reflection", "mindfulness"]),

    (85, "On the nature of habits", """Read a fascinating passage today from a book on [[stoicism]]. Marcus Aurelius wrote something like: *"You have power over your mind, not outside events. Realize this, and you will find strength."*

I've been thinking about how this applies to my [[fitness]] goals. The workout itself isn't the point — the showing up is.

Three things I noticed today:
1. My attention span is shorter than I'd like
2. Gratitude genuinely does shift mood
3. The walk this morning was the best part of the day

See also: [[On habits and willpower]]""", ["stoicism", "reflection", "philosophy"]),

    (80, "The side hustle begins", """Had a long conversation with myself about the [[career]] question. Should I keep building on the side? The answer is yes, but I need to be strategic.

The kitchen renovation is also ramping up — two big projects at once. [[Prioritization]] is going to matter a lot.

Notes:
- Revenue from consulting: small but real
- Need to invoice by end of week
- Get quotes for cabinet refacing""", ["productivity", "career"]),

    (75, "Workout wins and losses", """Missed the gym yesterday. Made up for it today with a longer run. [[Consistency over perfection]] — I keep coming back to that phrase.

The walk habit is going well. 21 days is the threshold, and I'm past it.

Reflecting on [[fitness]] as identity rather than activity. I don't "work out" — I'm someone who moves. That reframe matters.

#fitness""", ["fitness", "reflection"]),

    (68, "Creative drought", """Two weeks without writing anything substantial. The novel is stuck somewhere around chapter 4. I know the plot intellectually, but the words aren't flowing.

[[Creativity]] is weird. It can't be forced but it can be cultivated. Going to try [[morning pages]] for the next 30 days.

The philosophical question underneath: *why does it matter to me to write a novel?* What am I trying to say?""", ["creativity", "writing", "reflection"]),

    (60, "Money and meaning", """Did a proper budget review today. Numbers aren't bad, but they're not great. The [[finance]] goal this year is to hit $10k in the emergency fund.

What I keep noticing: money anxiety and existential anxiety are linked for me. The stoics had a lot to say about this — wealth is a *preferred indifferent*, meaning it's better to have it, but it's not a requirement for flourishing.

See also: [[On wanting less]]""", ["finance", "philosophy", "reflection"]),

    (52, "The graph of ideas", """Spent an hour just reading back through old notes. The [[wikilinks]] are starting to form a web. [[stoicism]] connects to [[mindfulness]] connects to [[fitness]] connects to [[creativity]].

Everything is related. That's the point of a Zettelkasten. The ideas cross-pollinate.

Favorite thread so far: the connection between physical discipline and mental clarity. The Stoics were obsessed with this too.

Tomorrow: start chapter 5. No excuses.""", ["philosophy", "learning", "writing"]),

    (45, "Renovation chaos", """The kitchen demo started today. It's loud, dusty, and somehow exciting. [[Home]] projects are a different kind of creativity — very concrete.

Spent the evening in the living room eating takeout, watching the chaos, feeling oddly content. There's something satisfying about tearing things down to build them back better.

Parallel to writing: you have to be willing to cut the darlings.

#home #creativity""", ["home", "creativity"]),

    (38, "Running numbers", """Finally getting consistent with the morning runs. 4x this week. The [[fitness]] goal is a 5k under 25 minutes by end of year — currently at ~28.

The budget situation: moved $500 to savings. Emergency fund is at $7,200. Getting there.

One philosophical note: the relationship between discipline and freedom. The more structured my morning is, the freer the rest of the day feels. [[Constraint as liberation]].

See also: [[The morning routine]]""", ["fitness", "productivity", "philosophy"]),

    (30, "Finding the thread", """Had a genuine breakthrough on the novel today. The protagonist isn't running *from* something — she's running *toward* something she doesn't have a name for yet. That's the emotional core.

Sometimes the story tells you what it's about, if you get quiet enough.

Also: signed up for that online writing course. Starts next month. [[learning]] continues.

#writing #creativity""", ["writing", "creativity", "learning"]),

    (22, "Mid-year checkpoint", """Halfway through the year in spirit if not calendar. Checking in:

**Fitness:** 3x/week average. Not the 5x I wanted. Still good.
**Finance:** Emergency fund at $8,400. 84% to goal.
**Writing:** Chapter 5 done. Chapter 6 underway.
**Habits:** Journal and morning walk consistent. Meditation inconsistent.

The kitchen is functional again, just needs the finishing touches. Can see the finish line.

Overall: things are moving. Not as fast as I imagined. That's OK.

See also: [[On patience]] [[Goal tracking]]""", ["reflection", "productivity", "finance", "fitness"]),

    (15, "On attention", """Reading *Deep Work* again. The argument is simple: cognitively demanding work requires undistracted concentration. We have less capacity for this than we think, and we're wasting it on shallow tasks.

My morning block (6-9am) is protected now. Phone goes on DND. No email. Just the important thing.

The [[learning]] investment is paying off. The writing course is excellent.

Also: [[stoicism]] and deep work rhyme nicely. Both are about controlling attention, not just output.

#philosophy #learning #productivity""", ["philosophy", "learning", "productivity"]),

    (8, "Almost there", """Emergency fund hits $9,100 today. $900 from the goal. This felt impossible in January.

The novel: 6 chapters done. Maybe 4 more to go. I can see the shape of the ending now.

The kitchen renovation: 95% complete. Waiting on the backsplash tile.

Running: hit 26:30 on the 5k this morning. Getting there.

There's a kind of momentum that builds when multiple things are moving at once. Feels good.

#reflection #finance #fitness #writing""", ["reflection", "finance", "fitness", "writing"]),

    (3, "Today's entry", """Morning pages done. Walk done. Coffee excellent.

The question I've been sitting with: [[what does it mean to live well?]] Not philosophically, but practically. What does a good day look like?

My answer today: something created, something moved, something connected, something quiet.

See also: [[Starting fresh]] [[On the nature of habits]]""", ["philosophy", "reflection", "mindfulness"]),

    (0, "Right now", """Just finished a workout. Tired in the good way.

The backsplash tile arrives tomorrow. The kitchen will finally be done.

One thing I want to remember: the process of building something — a habit, a book, a room — is the point. Not the artifact.

*"It is not the mountain we conquer but ourselves."* — Edmund Hillary

#reflection""", ["reflection", "fitness"]),
]

note_ids: dict[str, str] = {}  # title → id
for days, title, content, tag_names in JOURNAL_ENTRIES:
    tag_id_list = [tags[t] for t in tag_names if t in tags]
    entry = post("/notes", {
        "title": title,
        "content_md": content,
        "collection_id": journal_col_id,
        "tag_ids": tag_id_list,
    })
    if entry.get("id"):
        note_ids[title] = entry["id"]
        print(f"  ✅  journal: {title}")
    else:
        print(f"  ❌  journal: {title}")

# ── 4. Philosophical notes (standalone) ──────────────────────────────────────
print("\n🧠  Creating philosophical notes...")

PHILOSOPHY_NOTES = [
    ("On habits and willpower", """## The myth of willpower

Most people treat willpower as a finite resource — the tank-of-gas model. But research increasingly suggests that what we call "willpower fatigue" is often a failure of *motivation*, not capacity.

The [[stoicism|Stoic]] reframe: habits remove the need for willpower entirely. You don't decide to do the thing. The thing just happens because that's who you are.

**Key insight:** Identity-based habits beat goal-based habits. "I'm a writer" beats "I want to write a novel."

See also: [[The morning routine]] [[Consistency over perfection]]""", ["philosophy", "productivity", "mindfulness"]),

    ("On wanting less", """## Negative capability and desire

Keats coined "negative capability" to describe the ability to sit with uncertainty without grasping for resolution. I think there's a related capacity: the ability to *want less*.

Not in a deprivation sense. In the sense of [[stoicism|Stoic]] *ataraxia* — freedom from disturbance. The less you need the world to be a certain way, the freer you are.

This doesn't mean passive acceptance. It means distinguishing between what's in your control and what isn't.

**Practical exercise:** Before each desire, ask: *is this something I control?* If no, release it. If yes, decide whether to pursue it.

Connects to: [[Starting fresh]] [[The morning routine]]""", ["philosophy", "stoicism", "mindfulness"]),

    ("Consistency over perfection", """## The compound interest of small actions

Imagine two writers. Writer A writes 2,000 words a day but stops for weeks at a time. Writer B writes 300 words a day, every single day.

After a year: Writer A has ~180,000 words (if they wrote ~90 days). Writer B has ~109,500 words — but they have *habit*. They have the identity. They have the momentum.

This is the compounding principle applied to behavior. Small, consistent action beats large, inconsistent action.

The same applies to [[fitness]], [[finance]], and any other domain that accumulates over time.

**The rule:** never miss twice.

See also: [[On habits and willpower]] [[On the nature of habits]]""", ["productivity", "philosophy", "creativity"]),

    ("The morning routine", """## Architecture of a good morning

A morning routine isn't about productivity hacks. It's about *starting on your terms*.

My current structure:
1. Wake without alarm (or at least before it screams)
2. 10 min quiet — no phone, no news
3. Coffee, slowly
4. Morning pages (3 pages, longhand)
5. Movement — walk or workout
6. The one important thing

The key is that the morning routine is *for me*, not for output. The outputs come as a side effect.

Connected concepts: [[On habits and willpower]] [[Consistency over perfection]] [[stoicism]]""", ["productivity", "mindfulness", "philosophy"]),

    ("Constraint as liberation", """## How limits create freedom

Counterintuitively, having more options often leads to worse outcomes (the paradox of choice). Constraints — budgets, deadlines, rules — eliminate the cognitive overhead of deciding and let you focus on *doing*.

The sonnet is one of the most constrained poetic forms in English. It also produced Shakespeare.

In [[creativity|creative work]]: constraints force solutions you wouldn't have found with unlimited freedom.

In [[finance]]: a fixed budget makes spending decisions automatic.

In [[fitness]]: a rigid workout schedule means you never have to decide whether to go.

**The question to ask:** what constraints would make this easier, not harder?

See also: [[Consistency over perfection]] [[The morning routine]]""", ["philosophy", "creativity", "productivity"]),

    ("On patience", """## The slow work of becoming

Most meaningful things take longer than expected. The novel. The body. The net worth. The character.

We chronically overestimate what we can do in a week and underestimate what we can do in five years.

The [[stoicism|Stoic]] exercise of *memento mori* — remembering death — is often read as morbid. But it's actually about proportion. If you have 50 years, 2 years of hard work is 4% of your life. The uncomfortable question: what would you build if you knew you had 50 years?

Patience isn't passive. It's the ability to act *consistently* without demanding immediate results.

Connected to: [[Consistency over perfection]] [[On habits and willpower]]""", ["philosophy", "stoicism", "reflection"]),

    ("What does it mean to live well?", """## A working definition

Not a fixed answer — a working one, subject to revision.

**Living well, for me, currently means:**
1. Creating something each day (writing, building, cooking)
2. Moving the body — it's part of thinking
3. Real connection — depth over breadth
4. Learning something — following genuine curiosity
5. Quiet — enough space to actually notice your life

The Aristotelian term is *eudaimonia* — often translated as happiness, better understood as *flourishing*. It's an activity, not a state. You don't *have* eudaimonia; you *do* it.

**The practical test:** at the end of the day, did I live according to my values? Not perfectly. But did I try?

See also: [[On wanting less]] [[The morning routine]] [[Starting fresh]]""", ["philosophy", "reflection", "mindfulness"]),

    ("Goal tracking as philosophy", """## Why tracking matters (and why it doesn't)

There's a tension in goal-tracking. On one hand, measurement drives improvement — you can't manage what you don't measure. On the other hand, the metric can become the thing, displacing the actual goal.

Goodhart's Law: *when a measure becomes a target, it ceases to be a good measure.*

For [[fitness]]: don't optimize for the number on the scale. Optimize for energy, strength, health.
For [[finance]]: don't optimize for net worth. Optimize for security, freedom, generosity.
For [[writing]]: don't optimize for word count. Optimize for saying something true.

**The fix:** track the behavior, not the outcome. I can't control whether the book sells. I can control whether I write today.

See also: [[Consistency over perfection]] [[On habits and willpower]]""", ["philosophy", "productivity", "reflection"]),
]

for title, content, tag_names in PHILOSOPHY_NOTES:
    tag_id_list = [tags[t] for t in tag_names if t in tags]
    note = post("/notes", {
        "title": title,
        "content_md": content,
        "tag_ids": tag_id_list,
    })
    if note.get("id"):
        note_ids[title] = note["id"]
        print(f"  ✅  note: {title}")
    else:
        print(f"  ❌  note: {title}")

# ── 5. Workouts ───────────────────────────────────────────────────────────────
print("\n🏋️  Creating workouts...")

WORKOUT_TEMPLATES = [
    # (name, notes, entries)
    ("Upper body strength", "Good session, pushed on bench today", [
        {"name": "Bench Press", "type": "strength", "metrics": {"sets": 4, "reps": 8, "weight_kg": 70}},
        {"name": "Bent-over Row", "type": "strength", "metrics": {"sets": 4, "reps": 8, "weight_kg": 60}},
        {"name": "Overhead Press", "type": "strength", "metrics": {"sets": 3, "reps": 10, "weight_kg": 45}},
        {"name": "Pull-ups", "type": "strength", "metrics": {"sets": 3, "reps": 8, "weight_kg": 0}},
        {"name": "Tricep Dips", "type": "strength", "metrics": {"sets": 3, "reps": 12, "weight_kg": 0}},
    ]),
    ("Lower body strength", "Legs day. Hate it. Worth it.", [
        {"name": "Squat", "type": "strength", "metrics": {"sets": 4, "reps": 6, "weight_kg": 90}},
        {"name": "Romanian Deadlift", "type": "strength", "metrics": {"sets": 3, "reps": 10, "weight_kg": 70}},
        {"name": "Leg Press", "type": "strength", "metrics": {"sets": 3, "reps": 12, "weight_kg": 120}},
        {"name": "Calf Raises", "type": "strength", "metrics": {"sets": 4, "reps": 15, "weight_kg": 40}},
    ]),
    ("Morning run", "Early morning, cool air, good pace", [
        {"name": "Outdoor Run", "type": "cardio", "metrics": {"duration_seconds": 1680, "distance_meters": 5000, "avg_heart_rate": 158}},
    ]),
    ("Full body HIIT", "Circuit training, no rest between sets", [
        {"name": "Burpee Circuit", "type": "hiit", "metrics": {"rounds": 5, "work_seconds": 40, "rest_seconds": 20}},
        {"name": "Mountain Climbers", "type": "hiit", "metrics": {"rounds": 4, "work_seconds": 30, "rest_seconds": 15}},
        {"name": "Jump Squats", "type": "hiit", "metrics": {"rounds": 4, "work_seconds": 30, "rest_seconds": 15}},
    ]),
    ("Easy recovery run", "Keeping it light today", [
        {"name": "Outdoor Run", "type": "cardio", "metrics": {"duration_seconds": 1440, "distance_meters": 4000, "avg_heart_rate": 140}},
    ]),
    ("Push day", "Chest and shoulders focus", [
        {"name": "Incline Bench Press", "type": "strength", "metrics": {"sets": 4, "reps": 8, "weight_kg": 60}},
        {"name": "Cable Fly", "type": "strength", "metrics": {"sets": 3, "reps": 12, "weight_kg": 15}},
        {"name": "Lateral Raises", "type": "strength", "metrics": {"sets": 4, "reps": 15, "weight_kg": 10}},
        {"name": "Face Pulls", "type": "strength", "metrics": {"sets": 3, "reps": 15, "weight_kg": 20}},
    ]),
    ("Pull day", "Back and biceps", [
        {"name": "Deadlift", "type": "strength", "metrics": {"sets": 4, "reps": 5, "weight_kg": 100}},
        {"name": "Lat Pulldown", "type": "strength", "metrics": {"sets": 3, "reps": 10, "weight_kg": 55}},
        {"name": "Barbell Curl", "type": "strength", "metrics": {"sets": 3, "reps": 12, "weight_kg": 25}},
        {"name": "Hammer Curl", "type": "strength", "metrics": {"sets": 3, "reps": 12, "weight_kg": 15}},
    ]),
    ("5K time trial", "Pushed hard today, new PR attempt", [
        {"name": "5K Run", "type": "cardio", "metrics": {"duration_seconds": 1590, "distance_meters": 5000, "avg_heart_rate": 172}},
    ]),
    ("Yoga & stretching", "Active recovery", [
        {"name": "Yoga Flow", "type": "flexibility", "metrics": {}, "notes": "30 min vinyasa flow"},
        {"name": "Hip Flexor Stretch", "type": "flexibility", "notes": "5 min each side"},
    ]),
    ("Core & conditioning", "Finisher after upper body", [
        {"name": "Plank Circuit", "type": "hiit", "metrics": {"rounds": 3, "work_seconds": 60, "rest_seconds": 30}},
        {"name": "Hanging Leg Raises", "type": "strength", "metrics": {"sets": 3, "reps": 12, "weight_kg": 0}},
        {"name": "Ab Wheel Rollout", "type": "strength", "metrics": {"sets": 3, "reps": 10, "weight_kg": 0}},
    ]),
]

# Spread ~30 workouts over the last 90 days (roughly 3-4 per week)
workout_days = sorted(random.sample(range(1, 90), 30), reverse=True)
for i, day_offset in enumerate(workout_days):
    template = WORKOUT_TEMPLATES[i % len(WORKOUT_TEMPLATES)]
    name, notes, entries = template
    entries_payload = [
        {k: v for k, v in e.items() if k != "sort_order"} | {"sort_order": j}
        for j, e in enumerate(entries)
    ]
    w = post("/workouts", {
        "workout_date": days_ago(day_offset).isoformat(),
        "name": name,
        "notes": notes,
        "entries": entries_payload,
    })
    if w.get("id"):
        print(f"  ✅  workout: {name} ({days_ago(day_offset)})")
    else:
        print(f"  ❌  workout: {name}")

# ── 6. Habits ─────────────────────────────────────────────────────────────────
print("\n🔄  Creating habits...")

HABIT_DEFS = [
    {
        "name": "Morning journal",
        "description": "Write at least one page in the journal before noon",
        "frequency": "daily",
        "cadence": {"link": {"path": "/collections/" + (journal_col_id or ""), "label": "Journal"}},
        "status": "active",
    },
    {
        "name": "Exercise",
        "description": "Any intentional movement for at least 30 minutes",
        "frequency": "weekly",
        "cadence": {"days_of_week": [0, 2, 4], "times_per_period": 3},  # Mon/Wed/Fri
        "status": "active",
    },
    {
        "name": "Morning walk",
        "description": "Walk outside before starting work — at least 20 minutes",
        "frequency": "daily",
        "cadence": {},
        "status": "active",
    },
    {
        "name": "Meditation",
        "description": "10 minutes of quiet sitting, breathing, or body scan",
        "frequency": "daily",
        "cadence": {},
        "status": "active",
    },
    {
        "name": "Read",
        "description": "Read a physical book for at least 20 minutes",
        "frequency": "daily",
        "cadence": {},
        "status": "active",
    },
    {
        "name": "No alcohol",
        "description": "Alcohol-free day",
        "frequency": "weekly",
        "cadence": {"days_of_week": [0, 1, 2, 3, 4]},  # Weekdays
        "status": "active",
    },
    {
        "name": "Weekly review",
        "description": "Review goals, tasks, and plans for the coming week",
        "frequency": "weekly",
        "cadence": {"days_of_week": [6]},  # Sunday
        "status": "active",
    },
    {
        "name": "Floss",
        "description": "Floss before bed",
        "frequency": "daily",
        "cadence": {},
        "status": "active",
    },
]

habit_ids: list[str] = []
for hdef in HABIT_DEFS:
    h = post("/habits", hdef)
    if h.get("id"):
        habit_ids.append(h["id"])
        print(f"  ✅  habit: {hdef['name']}")
    else:
        print(f"  ❌  habit: {hdef['name']}")

# Seed occurrences — last 60 days with realistic completion patterns
print("     Seeding habit occurrences...")
COMPLETION_RATES = [0.85, 0.72, 0.90, 0.55, 0.80, 0.88, 0.75, 0.65]

for habit_id, rate in zip(habit_ids, COMPLETION_RATES):
    for days_back in range(1, 61):
        d = days_ago(days_back)
        # Skip future dates; random skip based on completion rate
        if random.random() > rate:
            continue
        occ = post(f"/habits/{habit_id}/occurrences", {
            "scheduled_date": d.isoformat(),
            "status": "done",
        })
        # Mark completed
        if occ.get("id"):
            patch(f"/habits/{habit_id}/occurrences/{occ['id']}", {
                "status": "done",
                "completed_at": datetime.combine(d, datetime.min.time()).replace(
                    hour=8, tzinfo=timezone.utc
                ).isoformat(),
            })

print("  ✅  Habit occurrences seeded")

# ── 7. Grocery lists ──────────────────────────────────────────────────────────
print("\n🛒  Creating grocery lists...")

GROCERY_LISTS = [
    {
        "name": "Weekly shop — Week 1",
        "store": "Whole Foods",
        "status": "done",
        "items": [
            {"name": "Organic chicken breast", "quantity": 2, "unit": "lbs", "category": "Meat"},
            {"name": "Salmon fillets", "quantity": 1, "unit": "lb", "category": "Seafood"},
            {"name": "Greek yogurt", "quantity": 3, "category": "Dairy"},
            {"name": "Eggs", "quantity": 12, "unit": "count", "category": "Dairy", "is_checked": True},
            {"name": "Spinach", "quantity": 1, "unit": "bag", "category": "Produce"},
            {"name": "Broccoli", "quantity": 2, "unit": "heads", "category": "Produce"},
            {"name": "Avocados", "quantity": 4, "category": "Produce"},
            {"name": "Brown rice", "quantity": 2, "unit": "lbs", "category": "Pantry"},
            {"name": "Olive oil", "quantity": 1, "unit": "bottle", "category": "Pantry"},
            {"name": "Almond butter", "quantity": 1, "unit": "jar", "category": "Pantry"},
        ],
    },
    {
        "name": "Weekly shop — Week 3",
        "store": "Trader Joe's",
        "status": "done",
        "items": [
            {"name": "Ground turkey", "quantity": 1.5, "unit": "lbs", "category": "Meat"},
            {"name": "Canned tomatoes", "quantity": 4, "unit": "cans", "category": "Pantry"},
            {"name": "Pasta", "quantity": 3, "unit": "boxes", "category": "Pantry"},
            {"name": "Parmesan cheese", "quantity": 1, "unit": "block", "category": "Dairy"},
            {"name": "Cherry tomatoes", "quantity": 2, "unit": "pints", "category": "Produce"},
            {"name": "Garlic", "quantity": 1, "unit": "bulb", "category": "Produce"},
            {"name": "Fresh basil", "quantity": 1, "unit": "bunch", "category": "Produce"},
            {"name": "Sparkling water", "quantity": 12, "unit": "cans", "category": "Beverages"},
            {"name": "Dark chocolate", "quantity": 2, "unit": "bars", "category": "Snacks"},
        ],
    },
    {
        "name": "Costco run",
        "store": "Costco",
        "status": "done",
        "items": [
            {"name": "Mixed nuts", "quantity": 2.5, "unit": "lbs", "category": "Snacks"},
            {"name": "Protein powder", "quantity": 5, "unit": "lbs", "category": "Supplements"},
            {"name": "Paper towels", "quantity": 1, "unit": "pack", "category": "Household"},
            {"name": "Laundry detergent", "quantity": 1, "unit": "jug", "category": "Household"},
            {"name": "Frozen berries", "quantity": 3, "unit": "bags", "category": "Frozen"},
            {"name": "Rotisserie chicken", "quantity": 2, "category": "Meat"},
            {"name": "Baby carrots", "quantity": 2, "unit": "bags", "category": "Produce"},
            {"name": "Hummus", "quantity": 2, "unit": "tubs", "category": "Dairy"},
        ],
    },
    {
        "name": "Weekly shop — Week 6",
        "store": "Local market",
        "status": "done",
        "items": [
            {"name": "Ribeye steak", "quantity": 2, "unit": "steaks", "category": "Meat"},
            {"name": "Asparagus", "quantity": 1, "unit": "bunch", "category": "Produce"},
            {"name": "Sweet potatoes", "quantity": 4, "category": "Produce"},
            {"name": "Kale", "quantity": 1, "unit": "bunch", "category": "Produce"},
            {"name": "Coconut milk", "quantity": 2, "unit": "cans", "category": "Pantry"},
            {"name": "Quinoa", "quantity": 1, "unit": "lb", "category": "Pantry"},
            {"name": "Lemons", "quantity": 6, "category": "Produce"},
            {"name": "Blueberries", "quantity": 2, "unit": "pints", "category": "Produce"},
        ],
    },
    {
        "name": "Weekend cookout",
        "store": "Whole Foods",
        "status": "done",
        "items": [
            {"name": "Beef burgers", "quantity": 8, "unit": "patties", "category": "Meat"},
            {"name": "Hot dogs", "quantity": 1, "unit": "pack", "category": "Meat"},
            {"name": "Burger buns", "quantity": 8, "unit": "buns", "category": "Bakery"},
            {"name": "Potato salad", "quantity": 1, "unit": "lb", "category": "Deli"},
            {"name": "Watermelon", "quantity": 1, "category": "Produce"},
            {"name": "Corn on the cob", "quantity": 6, "category": "Produce"},
            {"name": "BBQ sauce", "quantity": 1, "unit": "bottle", "category": "Condiments"},
            {"name": "Beer", "quantity": 12, "unit": "cans", "category": "Beverages"},
        ],
    },
    {
        "name": "Weekly shop — Week 9",
        "store": "Trader Joe's",
        "status": "done",
        "items": [
            {"name": "Chicken thighs", "quantity": 2, "unit": "lbs", "category": "Meat"},
            {"name": "Wild rice blend", "quantity": 2, "unit": "bags", "category": "Pantry"},
            {"name": "Frozen edamame", "quantity": 2, "unit": "bags", "category": "Frozen"},
            {"name": "Tahini", "quantity": 1, "unit": "jar", "category": "Pantry"},
            {"name": "Bell peppers", "quantity": 4, "category": "Produce"},
            {"name": "Zucchini", "quantity": 3, "category": "Produce"},
            {"name": "Feta cheese", "quantity": 1, "unit": "block", "category": "Dairy"},
        ],
    },
    {
        "name": "Renovation supplies",
        "store": "Home Depot",
        "status": "done",
        "items": [
            {"name": "Painter's tape", "quantity": 3, "unit": "rolls", "category": "Supplies"},
            {"name": "Drop cloths", "quantity": 2, "category": "Supplies"},
            {"name": "Paint rollers", "quantity": 4, "category": "Supplies"},
            {"name": "Sandpaper assortment", "quantity": 1, "unit": "pack", "category": "Supplies"},
        ],
    },
    {
        "name": "This week's groceries",
        "store": "Whole Foods",
        "status": "active",
        "items": [
            {"name": "Salmon", "quantity": 1.5, "unit": "lbs", "category": "Seafood"},
            {"name": "Eggs", "quantity": 18, "unit": "count", "category": "Dairy"},
            {"name": "Spinach", "quantity": 2, "unit": "bags", "category": "Produce"},
            {"name": "Bananas", "quantity": 6, "category": "Produce"},
            {"name": "Oat milk", "quantity": 2, "unit": "cartons", "category": "Dairy"},
            {"name": "Coffee beans", "quantity": 1, "unit": "bag", "category": "Beverages"},
            {"name": "Sourdough bread", "quantity": 1, "unit": "loaf", "category": "Bakery"},
            {"name": "Chicken breast", "quantity": 2, "unit": "lbs", "category": "Meat"},
            {"name": "Greek yogurt", "quantity": 2, "unit": "tubs", "category": "Dairy"},
            {"name": "Mixed greens", "quantity": 1, "unit": "bag", "category": "Produce"},
            {"name": "Cherry tomatoes", "quantity": 1, "unit": "pint", "category": "Produce"},
            {"name": "Olive oil", "quantity": 1, "unit": "bottle", "category": "Pantry"},
        ],
    },
]

for gl_def in GROCERY_LISTS:
    gl = post("/grocery-lists", {
        "name": gl_def["name"],
        "store": gl_def["store"],
        "status": gl_def["status"],
        "items": gl_def["items"],
        "visibility": "household",
    })
    ok(f"grocery: {gl_def['name']}", gl)

# ── 8. Goals ──────────────────────────────────────────────────────────────────
print("\n🎯  Creating goals...")

goal_financial = post("/goals", {
    "title": "Emergency fund: $10,000",
    "description": "Build a fully-funded 3-month emergency fund. Currently tracking through savings account balance.",
    "status": "active",
    "priority": "high",
    "target_value": 10000,
    "current_value": 9100,
    "unit": "USD",
    "due_date": days_from_now(90).isoformat(),
    "visibility": "personal",
})
ok("goal: Emergency fund", goal_financial)

goal_fitness = post("/goals", {
    "title": "Run a 5K under 25 minutes",
    "description": "Currently at ~26:30. Training 3x per week with one long run each weekend.",
    "status": "active",
    "priority": "medium",
    "target_value": 25,
    "current_value": 26.5,
    "unit": "minutes",
    "due_date": days_from_now(120).isoformat(),
    "visibility": "personal",
})
ok("goal: 5K time", goal_fitness)

goal_creative = post("/goals", {
    "title": "Finish the first draft of the novel",
    "description": "Literary fiction, ~80k words. Currently at chapter 6 of ~10. Target: complete draft by year end.",
    "status": "active",
    "priority": "high",
    "target_value": 10,
    "current_value": 6,
    "unit": "chapters",
    "due_date": days_from_now(180).isoformat(),
    "visibility": "personal",
})
ok("goal: Novel draft", goal_creative)

goal_financial_id = goal_financial.get("id")
goal_fitness_id = goal_fitness.get("id")
goal_creative_id = goal_creative.get("id")

# ── 9. Budget ─────────────────────────────────────────────────────────────────
print("\n💰  Setting up budget...")

# Try the seed-defaults shortcut first; if it 500s (known API bug with
# household_id class-level access), fall back to creating profiles directly.
seed_status, _ = _request("POST", "/budget/profiles/seed-defaults", {})
if seed_status in (200, 201):
    print("  ✅  Budget profiles seeded via seed-defaults")
else:
    print(f"  ↩️  seed-defaults returned {seed_status} — creating profiles directly")

# Get profiles (they may already exist from seed-defaults, or we'll create them)
profiles_data = get("/budget/profiles")
profiles = profiles_data if isinstance(profiles_data, list) else []

# If we have no profiles, create them directly
if not profiles:
    for prof_name in ("Personal", "Household"):
        p = post("/budget/profiles", {"name": prof_name, "budgeting_style": "zero_based", "currency": "USD"})
        if p.get("id"):
            profiles.append(p)
            print(f"  ✅  Created budget profile: {prof_name}")

personal_profile = next((p for p in profiles if "personal" in p.get("name", "").lower()), None)
profile_id = (personal_profile or (profiles[0] if profiles else {})).get("id")

if not profile_id:
    print("  ⚠️  Could not find or create a budget profile — budget seeding may be incomplete")

# Seed default category groups
if profile_id:
    status, _ = _request("POST", f"/budget/category-groups/seed-defaults", params={"profile_id": profile_id})
    if status in (200, 201):
        print("  ✅  Default category groups seeded")

# Create accounts
print("  Creating accounts...")
checking = post("/budget/accounts", {
    "name": "Chase Checking",
    "account_type": "checking",
    "scope": "personal",
    "profile_id": profile_id,
})
ok("account: Chase Checking", checking)

savings = post("/budget/accounts", {
    "name": "Marcus Savings",
    "account_type": "savings",
    "scope": "personal",
    "profile_id": profile_id,
})
ok("account: Marcus Savings", savings)

checking_id = checking.get("id")
savings_id = savings.get("id")

# Update balances
if checking_id:
    patch(f"/budget/accounts/{checking_id}", {"current_balance": 4280.55})
if savings_id:
    patch(f"/budget/accounts/{savings_id}", {"current_balance": 9100.00})

# Fetch or create categories for transactions
categories_data = get("/budget/categories")
categories = categories_data if isinstance(categories_data, list) else (categories_data.get("items") or [])

def find_or_create_category(name: str, icon: str | None = None, color: str | None = None) -> str | None:
    for c in categories:
        if c.get("name", "").lower() == name.lower():
            # Backfill icon/color if the existing category is missing them
            needs_patch: dict = {}
            if icon and not c.get("icon"):
                needs_patch["icon"] = icon
            if color and not c.get("color"):
                needs_patch["color"] = color
            if needs_patch:
                updated = patch(f"/budget/categories/{c['id']}", needs_patch)
                if updated.get("id"):
                    c.update(needs_patch)
            return c["id"]
    body: dict = {"name": name, "profile_id": profile_id}
    if icon:
        body["icon"] = icon
    if color:
        body["color"] = color
    new_cat = post("/budget/categories", body)
    if new_cat.get("id"):
        categories.append(new_cat)
        return new_cat["id"]
    return None

cat_groceries        = find_or_create_category("Groceries",               "🛒", "#3b82f6")
cat_dining           = find_or_create_category("Dining Out",              "🍽️", "#f97316")
cat_rent             = find_or_create_category("Rent / Mortgage",         "🏠", "#64748b")
cat_utilities        = find_or_create_category("Utilities",               "⚡", "#eab308")
cat_transport        = find_or_create_category("Transport",               "🚗", "#8b5cf6")
cat_gym              = find_or_create_category("Gym & Fitness",           "🏋️", "#14b8a6")
cat_entertainment    = find_or_create_category("Entertainment",           "🎬", "#a855f7")
cat_coffee           = find_or_create_category("Coffee & Drinks",         "☕", "#b45309")
cat_salary           = find_or_create_category("Salary",                  "💼", "#22c55e")
cat_freelance        = find_or_create_category("Freelance / Side Income", "💡", "#a3e635")
cat_savings_transfer = find_or_create_category("Savings Transfer",        "🏦", "#0ea5e9")
cat_subscriptions    = find_or_create_category("Subscriptions",           "📱", "#6366f1")
cat_home_improvement = find_or_create_category("Home Improvement",        "🔨", "#92400e")
cat_medical          = find_or_create_category("Medical",                 "🏥", "#ef4444")
cat_clothing         = find_or_create_category("Clothing",                "👕", "#ec4899")

print("  ✅  Budget categories configured")

# Create transactions — last 90 days
TRANSACTION_TEMPLATES = []
if checking_id:
    print("  Creating transactions...")
    TRANSACTION_TEMPLATES = [
        # (day_offset, description, amount, category_id_var, account)
        # Income
        (1, "Direct Deposit — Employer", 4200.00, cat_salary, "checking"),
        (15, "Direct Deposit — Employer", 4200.00, cat_salary, "checking"),
        (31, "Direct Deposit — Employer", 4200.00, cat_salary, "checking"),
        (46, "Direct Deposit — Employer", 4200.00, cat_salary, "checking"),
        (61, "Direct Deposit — Employer", 4200.00, cat_salary, "checking"),
        (76, "Direct Deposit — Employer", 4200.00, cat_salary, "checking"),
        (20, "Freelance Invoice — Client A", 850.00, cat_freelance, "checking"),
        (55, "Freelance Invoice — Client B", 1200.00, cat_freelance, "checking"),
        # Rent
        (2, "Chase Online Payment — Rent", -1850.00, cat_rent, "checking"),
        (32, "Chase Online Payment — Rent", -1850.00, cat_rent, "checking"),
        (62, "Chase Online Payment — Rent", -1850.00, cat_rent, "checking"),
        # Utilities
        (5, "ConEdison Electric", -92.40, cat_utilities, "checking"),
        (35, "ConEdison Electric", -88.15, cat_utilities, "checking"),
        (65, "ConEdison Electric", -107.30, cat_utilities, "checking"),
        (7, "Internet — Comcast", -69.99, cat_utilities, "checking"),
        (37, "Internet — Comcast", -69.99, cat_utilities, "checking"),
        (67, "Internet — Comcast", -69.99, cat_utilities, "checking"),
        # Groceries
        (3, "Whole Foods Market", -127.45, cat_groceries, "checking"),
        (10, "Trader Joe's", -84.20, cat_groceries, "checking"),
        (17, "Whole Foods Market", -143.80, cat_groceries, "checking"),
        (24, "Costco Wholesale", -215.60, cat_groceries, "checking"),
        (31, "Trader Joe's", -91.30, cat_groceries, "checking"),
        (38, "Whole Foods Market", -108.75, cat_groceries, "checking"),
        (45, "Trader Joe's", -76.40, cat_groceries, "checking"),
        (52, "Whole Foods Market", -155.20, cat_groceries, "checking"),
        (59, "Costco Wholesale", -187.90, cat_groceries, "checking"),
        (66, "Trader Joe's", -88.60, cat_groceries, "checking"),
        (73, "Whole Foods Market", -119.45, cat_groceries, "checking"),
        (80, "Trader Joe's", -72.30, cat_groceries, "checking"),
        # Dining
        (4, "Sweetgreen", -16.80, cat_dining, "checking"),
        (8, "Local Thai Restaurant", -32.50, cat_dining, "checking"),
        (12, "Chipotle", -14.25, cat_dining, "checking"),
        (16, "Italian Trattoria", -67.40, cat_dining, "checking"),
        (19, "Sweetgreen", -17.20, cat_dining, "checking"),
        (25, "Sushi Place", -58.90, cat_dining, "checking"),
        (29, "Chipotle", -15.10, cat_dining, "checking"),
        (40, "Brunch Spot", -44.60, cat_dining, "checking"),
        (48, "Pizza Night", -38.20, cat_dining, "checking"),
        (57, "Local Thai Restaurant", -29.80, cat_dining, "checking"),
        (70, "Birthday dinner", -112.40, cat_dining, "checking"),
        (83, "Takeout — Thai", -34.50, cat_dining, "checking"),
        # Coffee
        (1, "Blue Bottle Coffee", -6.50, cat_coffee, "checking"),
        (3, "Blue Bottle Coffee", -6.50, cat_coffee, "checking"),
        (5, "Starbucks", -7.25, cat_coffee, "checking"),
        (8, "Local café", -5.80, cat_coffee, "checking"),
        (11, "Blue Bottle Coffee", -13.00, cat_coffee, "checking"),
        (15, "Blue Bottle Coffee", -6.50, cat_coffee, "checking"),
        (22, "Local café", -5.80, cat_coffee, "checking"),
        (35, "Blue Bottle Coffee", -6.50, cat_coffee, "checking"),
        (50, "Starbucks", -8.75, cat_coffee, "checking"),
        (65, "Local café", -5.80, cat_coffee, "checking"),
        # Transport
        (6, "Uber", -18.40, cat_transport, "checking"),
        (14, "MTA MetroCard", -33.00, cat_transport, "checking"),
        (21, "Uber", -22.10, cat_transport, "checking"),
        (33, "Lyft", -15.80, cat_transport, "checking"),
        (44, "MTA MetroCard", -33.00, cat_transport, "checking"),
        (58, "Uber", -31.20, cat_transport, "checking"),
        (72, "Lyft", -19.40, cat_transport, "checking"),
        (85, "MTA MetroCard", -33.00, cat_transport, "checking"),
        # Gym
        (1, "Equinox Monthly", -185.00, cat_gym, "checking"),
        (31, "Equinox Monthly", -185.00, cat_gym, "checking"),
        (61, "Equinox Monthly", -185.00, cat_gym, "checking"),
        (42, "Running shoes — Nike", -145.00, cat_gym, "checking"),
        # Subscriptions
        (1, "Netflix", -22.99, cat_subscriptions, "checking"),
        (1, "Spotify", -10.99, cat_subscriptions, "checking"),
        (1, "Apple iCloud", -2.99, cat_subscriptions, "checking"),
        (31, "Netflix", -22.99, cat_subscriptions, "checking"),
        (31, "Spotify", -10.99, cat_subscriptions, "checking"),
        (61, "Netflix", -22.99, cat_subscriptions, "checking"),
        (61, "Spotify", -10.99, cat_subscriptions, "checking"),
        (15, "Notion Pro", -16.00, cat_subscriptions, "checking"),
        (45, "Notion Pro", -16.00, cat_subscriptions, "checking"),
        (75, "Notion Pro", -16.00, cat_subscriptions, "checking"),
        # Entertainment
        (23, "Ticketmaster — Concert", -85.00, cat_entertainment, "checking"),
        (47, "AMC Theaters", -28.50, cat_entertainment, "checking"),
        (68, "Museum admission", -22.00, cat_entertainment, "checking"),
        # Home improvement
        (18, "Home Depot", -234.80, cat_home_improvement, "checking"),
        (39, "Lowe's", -178.40, cat_home_improvement, "checking"),
        (52, "Cabinet hardware", -89.50, cat_home_improvement, "checking"),
        (71, "Tile supply", -412.00, cat_home_improvement, "checking"),
        # Savings transfers
        (4, "Transfer to Marcus Savings", -500.00, cat_savings_transfer, "checking"),
        (34, "Transfer to Marcus Savings", -500.00, cat_savings_transfer, "checking"),
        (64, "Transfer to Marcus Savings", -400.00, cat_savings_transfer, "checking"),
        # Savings account — corresponding deposits
        (4, "Transfer from Chase Checking", 500.00, cat_savings_transfer, "savings"),
        (34, "Transfer from Chase Checking", 500.00, cat_savings_transfer, "savings"),
        (64, "Transfer from Chase Checking", 400.00, cat_savings_transfer, "savings"),
        (4, "Marcus HYSA Interest", 38.42, cat_salary, "savings"),
        (34, "Marcus HYSA Interest", 39.15, cat_salary, "savings"),
        (64, "Marcus HYSA Interest", 37.88, cat_salary, "savings"),
    ]

    for offset, desc, amount, cat_id, acct in TRANSACTION_TEMPLATES:
        acct_id = checking_id if acct == "checking" else savings_id
        if not acct_id:
            continue
        t = post("/budget/transactions", {
            "account_id": acct_id,
            "category_id": cat_id,
            "date": days_ago(offset).isoformat(),
            "amount": amount,
            "description": desc,
            "import_source": "manual",
        })
        if not t.get("id"):
            print(f"  ⚠️  transaction failed: {desc}")

    print("  ✅  Transactions created")

# ── 10. Projects ──────────────────────────────────────────────────────────────
print("\n📁  Creating projects...")

# — Creative writing project —
proj_novel = post("/projects", {
    "name": "Novel — First Draft",
    "description": "Literary fiction novel, ~80k words. Protagonist navigating identity and place in a changing city.",
    "status": "in_progress",
    "show_in_nav": True,
    "sort_order": 1,
    "visibility": "personal",
})
ok("project: Novel", proj_novel)
proj_novel_id = proj_novel.get("id")

if proj_novel_id and goal_creative_id:
    _request("PUT", f"/projects/{proj_novel_id}/goals/{goal_creative_id}")

# Novel sub-projects
novel_subprojects = [
    ("Act I — Setup (ch. 1–3)", "in_progress", "First three chapters establishing protagonist, world, and inciting incident"),
    ("Act II — Confrontation (ch. 4–7)", "in_progress", "Rising action, complications, mid-point reversal"),
    ("Act III — Resolution (ch. 8–10)", "backlog", "Climax and denouement — not started yet"),
    ("Revision pass", "backlog", "Full manuscript revision after first draft is complete"),
    ("Beta readers & query", "backlog", "Send to 3 beta readers, then query literary agents"),
]
novel_sub_ids = []
for name, status, desc in novel_subprojects:
    sp = post("/projects", {
        "name": name,
        "description": desc,
        "status": status,
        "parent_id": proj_novel_id,
        "visibility": "personal",
    })
    if sp.get("id"):
        novel_sub_ids.append(sp["id"])
        print(f"  ✅  sub-project: {name}")

# Novel todos
NOVEL_TODOS = [
    ("Finish chapter 6 draft", "in_progress", "high", 0),
    ("Outline chapters 7–10", "pending", "high", 7),
    ("Research: 1990s NYC architecture for chapter 5 setting", "done", "medium", None),
    ("Character study: antagonist backstory", "done", "medium", None),
    ("Write chapter 7", "pending", "high", 14),
    ("Write chapter 8", "pending", "medium", 28),
    ("Write chapter 9", "pending", "medium", 45),
    ("Write chapter 10", "pending", "medium", 60),
    ("First full read-through", "pending", "high", 75),
    ("Sign up for writing workshop", "done", "low", None),
    ("Daily word count tracking spreadsheet", "done", "low", None),
]
for title, status, priority, due_days in NOVEL_TODOS:
    todo_body: dict = {
        "title": title,
        "status": status,
        "priority": priority,
        "project_id": proj_novel_id,
        "visibility": "personal",
    }
    if due_days is not None:
        todo_body["due_date"] = days_from_now(due_days).isoformat()
    t = post("/todos", todo_body)
    if not t.get("id"):
        print(f"  ⚠️  todo failed: {title}")

print("  ✅  Novel todos created")

# — Kitchen renovation project —
proj_kitchen = post("/projects", {
    "name": "Kitchen Renovation",
    "description": "Full kitchen update: cabinet refacing, new countertops, backsplash, and lighting. Budget ~$8,500.",
    "status": "in_progress",
    "show_in_nav": True,
    "sort_order": 2,
    "visibility": "household",
})
ok("project: Kitchen Renovation", proj_kitchen)
proj_kitchen_id = proj_kitchen.get("id")

# Kitchen sub-projects
kitchen_subprojects = [
    ("Demo & Prep", "complete", "Tear out old tile, patch walls, prime surfaces"),
    ("Cabinet Refacing", "complete", "New door fronts and hardware on existing boxes"),
    ("Countertop Installation", "complete", "Quartz countertops — measured and installed"),
    ("Backsplash Tile", "in_progress", "Subway tile backsplash — tile arrives this week"),
    ("Lighting & Electrical", "backlog", "Under-cabinet LED strips + pendant over island"),
    ("Final touches & punch list", "backlog", "Touch-up paint, trim, hardware alignment"),
]
kitchen_sub_ids = []
for name, status, desc in kitchen_subprojects:
    sp = post("/projects", {
        "name": name,
        "description": desc,
        "status": status,
        "parent_id": proj_kitchen_id,
        "visibility": "household",
    })
    if sp.get("id"):
        kitchen_sub_ids.append(sp["id"])
        print(f"  ✅  sub-project: {name}")

# Kitchen todos
KITCHEN_TODOS = [
    ("Get 3 contractor quotes for tile work", "done", "high", None),
    ("Order backsplash tile (2 boxes + 10% overage)", "done", "high", None),
    ("Schedule tile installer for after delivery", "done", "high", None),
    ("Tile delivery", "in_progress", "high", 1),
    ("Tile installation", "pending", "high", 4),
    ("Grout and seal tile", "pending", "high", 7),
    ("Order under-cabinet lighting kit", "pending", "medium", 10),
    ("Electrician quote for pendant light", "pending", "medium", 7),
    ("Final inspection walkthrough", "pending", "medium", 21),
    ("Clean and photograph completed kitchen", "pending", "low", 25),
]
for title, status, priority, due_days in KITCHEN_TODOS:
    todo_body = {
        "title": title,
        "status": status,
        "priority": priority,
        "project_id": proj_kitchen_id,
        "visibility": "household",
    }
    if due_days is not None:
        todo_body["due_date"] = days_from_now(due_days).isoformat()
    t = post("/todos", todo_body)
    if not t.get("id"):
        print(f"  ⚠️  todo failed: {title}")

print("  ✅  Kitchen todos created")

# — Side hustle project —
proj_hustle = post("/projects", {
    "name": "Consulting Side Hustle",
    "description": "Freelance UX consulting work — 2 active clients, targeting $2k/month in additional revenue.",
    "status": "active",
    "show_in_nav": True,
    "sort_order": 3,
    "visibility": "personal",
})
ok("project: Side Hustle", proj_hustle)
proj_hustle_id = proj_hustle.get("id")

# Side hustle sub-projects
hustle_subprojects = [
    ("Client A — Design audit", "complete", "Full UX audit of their SaaS product. Delivered."),
    ("Client B — Ongoing retainer", "in_progress", "Monthly advisory: 5 hrs/month, $400/month"),
    ("Portfolio site update", "on_deck", "Update case studies and add two new projects"),
    ("Outreach & pipeline", "active", "3 warm leads to follow up with; goal: 1 new client/quarter"),
]
hustle_sub_ids = []
for name, status, desc in hustle_subprojects:
    sp = post("/projects", {
        "name": name,
        "description": desc,
        "status": status,
        "parent_id": proj_hustle_id,
        "visibility": "personal",
    })
    if sp.get("id"):
        hustle_sub_ids.append(sp["id"])
        print(f"  ✅  sub-project: {name}")

# Side hustle todos
HUSTLE_TODOS = [
    ("Invoice Client B — this month", "pending", "high", 3),
    ("Prepare Client B monthly advisory notes", "in_progress", "high", 5),
    ("Follow up with Lead #1 (intro meeting 3 weeks ago)", "pending", "high", 1),
    ("Follow up with Lead #2 (cold email)", "pending", "medium", 7),
    ("Draft portfolio site copy — Client A case study", "pending", "medium", 14),
    ("Update LinkedIn with new project", "pending", "low", 21),
    ("Set up Calendly for discovery calls", "done", "low", None),
    ("Create standard SOW template", "done", "medium", None),
    ("Invoice Client A — final payment", "done", "high", None),
    ("Set up separate business checking account", "pending", "medium", 30),
    ("Track revenue in budget — Q3 reconciliation", "pending", "medium", 7),
]
for title, status, priority, due_days in HUSTLE_TODOS:
    todo_body = {
        "title": title,
        "status": status,
        "priority": priority,
        "project_id": proj_hustle_id,
        "visibility": "personal",
    }
    if due_days is not None:
        todo_body["due_date"] = days_from_now(due_days).isoformat()
    t = post("/todos", todo_body)
    if not t.get("id"):
        print(f"  ⚠️  todo failed: {title}")

print("  ✅  Side hustle todos created")

# ── 11. Calendar events ───────────────────────────────────────────────────────
print("\n📅  Creating calendar events...")

PAST_EVENTS = [
    (58, 11, 2, "Dentist appointment", "Annual cleaning", "Dr. Kim's office, 3rd Ave"),
    (55, 14, 15, "Client A — kickoff call", "Project kickoff for UX audit engagement", None),
    (51, 10, 11, "Gym class — HIIT", "Signed up for 7am class", "Equinox"),
    (50, 9, 10, "Coffee with mentor", "Monthly check-in", "Blue Bottle, SoHo"),
    (47, 15, 16, "Contractor estimate — kitchen", "Cabinet refacing quote", "Home"),
    (45, 11, 12, "Client B — monthly advisory", "First advisory session", None),
    (42, 9, 10, "Morning run — park loop", None, "Prospect Park"),
    (40, 19, 21, "Concert — indie folk show", "Bought tickets 3 weeks ago", "Brooklyn Steel"),
    (38, 10, 11, "Kitchen demo day 1", "Contractor arrives 10am", "Home"),
    (35, 10, 11, "Kitchen demo day 2", None, "Home"),
    (33, 9, 10, "Doctor — annual physical", "Fasting bloodwork at 9am", "Dr. Chen, UES"),
    (30, 13, 14, "Client B — advisory", None, None),
    (28, 10, 11, "Countertop installation", "Quartz slabs being installed", "Home"),
    (25, 12, 13, "Lunch with college friend", "Haven't seen in months", "The Dutch, SoHo"),
    (22, 9, 21, "Weekend hiking trip", "Catskills — camping overnight", "Catskill Mountains"),
    (20, 18, 20, "Cooking class", "Italian regional cuisine", "Institute of Culinary Ed"),
    (18, 10, 11, "Writing workshop — Session 1", "First meeting of 8-week course", "Online"),
    (15, 10, 11, "Client B — advisory", None, None),
    (12, 9, 10, "Haircut", None, "Tony's Barber, Brooklyn"),
    (10, 18, 20, "Dinner party at Sarah's", "Bringing wine + dessert", "Sarah's place"),
    (8, 9, 9, "5K time trial — park", "Solo time trial, aiming for sub-27", "Prospect Park"),
    (6, 10, 11, "Writing workshop — Session 2", None, "Online"),
    (4, 11, 12, "Tile delivery", "Backsplash tile arriving", "Home"),
    (3, 10, 11, "Client B — advisory", None, None),
    (2, 19, 21, "Museum opening — new exhibit", "Photography exhibit, free admission", "Brooklyn Museum"),
    (1, 9, 10, "Therapy session", "Bi-weekly check-in", "Dr. Patel, remote"),
]

UPCOMING_EVENTS = [
    (1, 10, 11, "Tile installation — Day 1", "Installer scheduled", "Home"),
    (2, 10, 11, "Tile installation — Day 2", None, "Home"),
    (4, 10, 11, "Grout and seal", None, "Home"),
    (5, 10, 11, "Writing workshop — Session 3", None, "Online"),
    (7, 9, 10, "Therapy session", "Bi-weekly check-in", "Dr. Patel, remote"),
    (8, 11, 12, "Call with Lead #1 — discovery", "Potential new consulting client", "Video call"),
    (10, 9, 10, "Morning run — 5K", "Tracking pace improvement", "Prospect Park"),
    (12, 10, 11, "Writing workshop — Session 4", None, "Online"),
    (13, 13, 14, "Client B — advisory", "Review Q3 goals", None),
    (14, 10, 11, "Electrician quote — kitchen lighting", None, "Home"),
    (15, 9, 10, "Therapy session", None, "Dr. Patel, remote"),
    (17, 10, 11, "Writing workshop — Session 5", None, "Online"),
    (18, 9, 22, "Weekend trip — upstate", "Long weekend, leaving Friday evening", "Hudson, NY"),
    (21, 9, 10, "Therapy session", None, "Dr. Patel, remote"),
    (22, 10, 11, "Writing workshop — Session 6", None, "Online"),
    (24, 11, 12, "Kitchen final walkthrough", "Punch list with contractor", "Home"),
    (25, 10, 11, "Client B — advisory", None, None),
    (26, 9, 10, "Dentist — follow up", None, "Dr. Kim's office"),
    (27, 10, 11, "Writing workshop — Session 7", None, "Online"),
    (28, 9, 10, "Therapy session", None, "Dr. Patel, remote"),
    (29, 14, 15, "Friend's birthday party", "Alex's 30th", "TBD"),
    (30, 10, 11, "Portfolio site — photo shoot", "Get headshots + project photos done", "Studio"),
]

def make_event(days_offset: int, start_h: int, end_h: int, title: str,
               desc: str | None, location: str | None, past: bool = True) -> dict:
    if past:
        starts = dt_days_ago(days_offset, start_h)
        ends = dt_days_ago(days_offset, end_h)
    else:
        starts = dt_days_from_now(days_offset, start_h)
        ends = dt_days_from_now(days_offset, end_h)
    body: dict = {
        "title": title,
        "starts_at": starts,
        "ends_at": ends,
        "status": "confirmed",
    }
    if desc:
        body["description"] = desc
    if location:
        body["location"] = location
    return body

for d, sh, eh, title, desc, loc in PAST_EVENTS:
    e = post("/events", make_event(d, sh, eh, title, desc, loc, past=True))
    if e.get("id"):
        print(f"  ✅  event: {title}")
    else:
        print(f"  ❌  event: {title}")

for d, sh, eh, title, desc, loc in UPCOMING_EVENTS:
    e = post("/events", make_event(d, sh, eh, title, desc, loc, past=False))
    if e.get("id"):
        print(f"  ✅  event: {title}")
    else:
        print(f"  ❌  event: {title}")

# ── 12. Documents ─────────────────────────────────────────────────────────────
print("\n📄  Creating documents...")

DOCUMENTS = [
    {
        "title": "Japan Trip — 2025 Planning",
        "icon": "✈️",
        "description": "Research and planning document for a 14-day Japan trip",
        "source_markdown": """# Japan Trip — 2025 Planning

## Overview

14 days, mid-October. Two cities: Tokyo (8 days) + Kyoto (5 days) + possible Osaka day trip.

**Budget estimate:** $5,500–$6,500 total (flights, accommodation, food, activities)

---

## Flights

- **Outbound:** JFK → NRT (nonstop on JAL or ANA preferred)
- **Return:** NRT → JFK
- **Best booking window:** 3–4 months out; target price ~$1,100–$1,300 RT
- Track on Google Flights

---

## Tokyo — 8 days

### Neighborhoods to stay
- **Shinjuku** — central, great transport links, lots of food
- **Shimokitazawa** — hipper, record shops, cafés, vintage

### Must-do
- [ ] Tsukiji outer market breakfast
- [ ] Yanaka neighborhood walk
- [ ] TeamLab digital art experience (book VERY early)
- [ ] Shibuya crossing at night
- [ ] Day trip to Nikko or Kamakura
- [ ] Depachika (department store basement food halls)

### Restaurants to research
- Sushi Saito (impossible, but worth knowing about)
- Standing ramen bars in Shinjuku
- Tonkatsu Maisen, Omotesando

---

## Kyoto — 5 days

### Must-do
- [ ] Fushimi Inari (go at dawn, before crowds)
- [ ] Arashiyama bamboo grove + monkey park
- [ ] Philosopher's Path in fall foliage
- [ ] Nishiki Market ("Kyoto's kitchen")
- [ ] Tea ceremony experience
- [ ] Nijo Castle

### Day trip
- Osaka (1 day): Dotonbori, street food, Osaka Castle

---

## Packing list (draft)

- JR Pass (buy in advance online — cheaper than in Japan)
- Pocket WiFi or local SIM
- IC Card (Suica) — load at airport
- Comfortable walking shoes (will walk 15k+ steps/day)
- Layers — October can be cool in the evenings
- Small backpack for day trips
- Power adapter (Japan uses Type A, same as US — no adapter needed)

---

## Language

- Learn: thank you (arigatou gozaimasu), excuse me (sumimasen), where is? (doko desu ka?)
- Google Translate offline pack downloaded
- Most signs in tourist areas have English

---

## Notes

Ideal time of year for fall foliage. Book TeamLab and any restaurants 2–3 months ahead.
""",
    },
    {
        "title": "Spanish Learning Notes",
        "icon": "📖",
        "description": "Vocabulary, grammar notes, and practice sentences from Spanish self-study",
        "source_markdown": """# Spanish Learning Notes

## Current level: A2 → B1

**Resources:**
- Duolingo (daily streak: 47 days)
- Language Transfer — Complete Spanish (audio course)
- Anki deck — 2,000 most common words

---

## Grammar quick-reference

### Ser vs. Estar

| Use **ser** for | Use **estar** for |
|---|---|
| Origin / nationality | Location |
| Occupation | Temporary state |
| Permanent characteristics | Emotions |
| Time / dates | Progressive tenses |

**Examples:**
- *Soy americano* — I am American (permanent)
- *Estoy cansado* — I am tired (temporary)
- *El libro es interesante* — The book is interesting (characteristic)
- *El libro está en la mesa* — The book is on the table (location)

### Preterite vs. Imperfect

**Preterite:** completed actions with a defined endpoint
- *Ayer comí una pizza* — Yesterday I ate a pizza

**Imperfect:** ongoing/habitual past actions, background descriptions
- *Cuando era niño, jugaba al fútbol* — When I was a child, I used to play soccer

---

## Vocabulary — current Anki deck focus

### Food & dining
- el desayuno — breakfast
- el almuerzo — lunch
- la cena — dinner
- pedir — to order
- la cuenta — the bill
- sin gluten — gluten free
- ¿Qué recomienda? — What do you recommend?

### Travel
- el vuelo — the flight
- el equipaje — the luggage
- la aduana — customs
- ¿A qué hora sale? — What time does it leave?
- el andén — the platform (train)
- perder el tren — to miss the train

### Opinions
- me parece bien — it seems fine to me
- no me gusta nada — I don't like it at all
- es que... — the thing is...
- a ver — let's see

---

## Practice sentences (corrected by language partner)

1. ~~Yo quiero ir a España el año que viene~~ → *Quiero ir a España el año que viene* (drop redundant "yo")
2. *Hace tres años que estudio español* — I've been studying Spanish for three years ✓
3. *Aunque no hablo muy bien, intento practicar todos los días* — Although I don't speak very well, I try to practice every day ✓

---

## Conversation log

- italki session 1: 30 min with tutor from Madrid. Understood ~60%, struggled with speed
- italki session 2: Improved to ~70%. Tutor slowed down a bit. Practiced ordering food
- Goal: 1 session/week + 20 min Anki daily
""",
    },
    {
        "title": "Vehicle Service Record — 2019 Honda Civic",
        "icon": "🚗",
        "description": "Service history, upcoming maintenance, and warranty information",
        "source_markdown": """# Vehicle Service Record — 2019 Honda Civic

**VIN:** 19XFC2F78KE........
**Purchase date:** March 2021
**Current mileage:** ~58,400
**Insurance:** State Farm — Policy #SF-2891-0034

---

## Service history

| Date | Mileage | Service | Shop | Cost |
|---|---|---|---|---|
| Jan 2024 | 55,200 | Oil change + tire rotation | Jiffy Lube | $89 |
| Oct 2023 | 52,800 | Oil change | Jiffy Lube | $72 |
| Aug 2023 | 51,000 | Air filter replacement | Honda dealer | $45 |
| May 2023 | 49,500 | Oil change + brake inspection | Jiffy Lube | $95 |
| Feb 2023 | 47,100 | Oil change | Jiffy Lube | $72 |
| Nov 2022 | 44,800 | 45k service (plugs, cabin filter, fluid check) | Honda dealer | $310 |
| Jul 2022 | 42,000 | Oil change + tire rotation | Jiffy Lube | $89 |

---

## Upcoming maintenance

- **~60,000 miles:** Transmission fluid change (~$150)
- **~60,000 miles:** Coolant flush (~$100)
- **~65,000 miles:** Spark plugs (iridium, ~$200 at dealer)
- **~65,000 miles:** Serpentine belt inspection

**Next oil change:** Due ~60,500 miles (approx. 2 months out)

---

## Tires

- **Brand:** Michelin Defender T+H
- **Size:** 215/55R16
- **Installed:** November 2022 @ 44,800 miles
- **Expected life:** 70,000–80,000 miles from install
- **Next rotation:** 60,000 miles

---

## Known issues / watch list

- Minor scratch on rear bumper (parking lot, 2023) — not worth repairing
- AC makes slight rattle at high fan speeds — checked, not a concern per dealer

---

## Documents (physical location: filing cabinet, "Car" folder)
- Title
- Registration (renews February)
- Insurance card (current)
- Warranty documents
""",
    },
    {
        "title": "Home Improvement Project Quotes",
        "icon": "🔨",
        "description": "Quotes received for various home improvement projects — current and future",
        "source_markdown": """# Home Improvement Project Quotes

## Kitchen Renovation ✅ (In Progress)

**Scope:** Cabinet refacing, quartz countertops, backsplash tile, lighting update

| Contractor | Quote | Notes |
|---|---|---|
| Rodriguez Renovations | $7,800 | Used them — great communication |
| ABC Home Services | $9,200 | Higher quote, less detail |
| Handyman Heroes | $6,400 | Seemed rushed, wouldn't use |

**Awarded to:** Rodriguez Renovations
**Final scope cost (estimate):** ~$8,500 with materials
**Status:** ~95% complete — tile arriving this week

---

## Bathroom Refresh — Master Bath (Future)

**Scope:** New vanity, mirror, lighting, retile shower floor

**Contractors to contact:**
- [ ] Rodriguez Renovations (happy with kitchen work)
- [ ] Tile Pros NYC
- [ ] Ask neighbor who did their bath last year

**Budget estimate:** $4,000–$6,000 depending on tile selection
**Target:** Start spring/summer next year

---

## HVAC — Window Unit Replacement (Future)

**Current units:** 3x window ACs, all 10+ years old, inefficient
**Options:**
1. Replace with 3 new window units (~$1,800 total)
2. Mini-split ductless system — more efficient, quieter (~$6,000–$8,000 installed)
3. Central air (not feasible — no existing ductwork)

**Decision pending** — leaning toward mini-split in the long run

---

## Deck/Outdoor Space (Future)

**Scope:** Replace deteriorating deck boards, add pergola
**One quote received:** Outdoor Living Co — $11,400 (seems high)
**Need 2 more quotes before deciding**
**Priority:** Low — do in 2–3 years

---

## Notes

Always get 3 quotes. Ask for references. Check license and insurance.
Rodriguez Renovations strongly recommended for tile/renovation work.
""",
    },
    {
        "title": "Learning — Photography Notes",
        "icon": "📷",
        "description": "Notes from learning street and travel photography — gear, technique, and composition",
        "source_markdown": """# Photography Notes

## Gear

- **Camera:** Sony a7C (full-frame mirrorless) — bought used, excellent condition
- **Lenses:**
  - Sony 35mm f/1.8 — main walkabout lens
  - Sony 85mm f/1.8 — portraits, compressed street
  - Sony 16-35mm f/4 — landscape, architecture
- **Accessories:** Peak Design strap, B+W ND filters, spare batteries (always 2)

---

## Exposure triangle (quick reference)

| Setting | Controls | Creative use |
|---|---|---|
| **Aperture** (f-stop) | Depth of field | Low f/# = blurry background; High f/# = everything sharp |
| **Shutter speed** | Motion blur | Fast = freeze; Slow = trails (water, light) |
| **ISO** | Sensor sensitivity | Low = clean; High = noise (use at night) |

**Exposure modes I use:**
- Aperture Priority (A) — most of the time, especially street
- Manual (M) — when light is controlled/predictable
- Auto ISO — let the camera handle sensitivity within bounds I set

---

## Composition rules

1. **Rule of thirds** — don't center everything
2. **Leading lines** — streets, fences, hallways draw the eye
3. **Framing** — use doorways, arches, windows to frame subject
4. **Negative space** — sometimes less is more
5. **Light first** — find the light, then the subject
6. **Decisive moment** — street photo is about timing, not setup

---

## Street photography tips (learned from workshop)

- Shoot at 35mm or wider for environmental context
- Get closer than feels comfortable
- f/8, 1/250, auto ISO — zone focus, just shoot
- Golden hour: 1 hr after sunrise, 1 hr before sunset
- Overcast days = natural softbox, great for portraits
- Don't ask permission — just shoot. You can always delete.

---

## Post-processing workflow (Lightroom)

1. Import, flag keepers (P), reject culls (X)
2. Basic panel: exposure, contrast, highlights/shadows
3. HSL panel: adjust individual colors
4. Sharpening + noise reduction
5. Export: long edge 2048px, sRGB, 90% quality for web

**Preset I use:** Vsco A4 as base, then tweak per image

---

## Projects / ideas

- [ ] 30-day street photography project — one photo per day
- [ ] Documentary series: NYC bodegas
- [ ] Print 5 favorites and frame for apartment
- [ ] Submit to local gallery open call (deadline: March)
""",
    },
    {
        "title": "Apartment Lease — Notes",
        "icon": "🏠",
        "description": "Key terms, renewal info, and landlord contact for the current apartment",
        "source_markdown": """# Apartment Lease

**Address:** [redacted for privacy]
**Lease term:** 12 months
**Rent:** $1,850/month
**Lease end:** [next August]
**Landlord:** Property Management Co.
**Super:** Mike — (917) 555-0101

---

## Key terms

- **Security deposit:** 1 month's rent, held in escrow
- **Pet policy:** No pets (current lease)
- **Subletting:** Not permitted without written consent
- **Notice to vacate:** 60 days before lease end
- **Rent increase policy:** ≤ stabilization guidelines

---

## Utilities included

- Water / hot water ✅
- Heat (steam radiator) ✅
- Trash ✅

**Tenant-paid:**
- Electricity (ConEdison)
- Internet (Comcast)

---

## Renewal notes

Typically offered 90 days before lease end. Last year increase was 3.5%. Expecting similar.
Decision point: **May 15** — decide whether to renew or search for new place.

**Factors to consider:**
- [ ] Check comparable rents in neighborhood
- [ ] Review any pending rent increase offer
- [ ] Consider whether bigger place makes sense (WFH needs)

---

## Contacts

- **Landlord email:** rentals@[redacted].com
- **Maintenance request:** via building portal
- **Emergency line:** (212) 555-0100
- **Super (Mike):** (917) 555-0101 — text preferred

---

## Documents (physical location: filing cabinet, "Apartment" folder)
- Signed lease
- Move-in inspection checklist
- Security deposit receipt
- Renter's insurance policy (Lemonade — auto-renewal in January)
""",
    },
    {
        "title": "Reading List & Book Notes",
        "icon": "📚",
        "description": "Books read, currently reading, and want-to-read — with notes on key ideas",
        "source_markdown": """# Reading List & Book Notes

## Currently reading
- **Deep Work** — Cal Newport (re-reading, chapter 3)
- **Brief and Wondrous Life of Oscar Wao** — Junot Díaz (for book club)

---

## Read this year

### Deep Work — Cal Newport ⭐⭐⭐⭐⭐
**Core idea:** The ability to focus without distraction on cognitively demanding tasks is both increasingly rare and increasingly valuable.

**Key concepts:**
- Depth vs. shallow work: schedule and protect deep work blocks
- The 4 disciplines of execution (4DX) applied to deep work habits
- Embrace boredom — don't give in to distraction at the first moment of boredom
- Drain the shallows — ruthlessly minimize email, meetings, shallow tasks

**My takeaways:**
- Protect 6–9am for deep work, every day
- Quit social media or at least treat it like a tool, not default behavior
- "Shutdown complete" ritual at end of workday — review tomorrow, close loops, say it out loud

---

### Meditations — Marcus Aurelius ⭐⭐⭐⭐⭐
**Core idea:** A journal of Stoic philosophy, written for himself, never intended for publication.

**Favorite passages:**
- "You have power over your mind, not outside events. Realize this, and you will find strength."
- "The impediment to action advances action. What stands in the way becomes the way."
- "Waste no more time arguing what a good man should be. Be one."

**My takeaways:**
- The dichotomy of control is foundational: control your judgments, not outcomes
- Virtue (excellence of character) is the only true good
- Practice memento mori — not morbidly, but as a clarifier of what matters

---

### The Artist's Way — Julia Cameron ⭐⭐⭐⭐
**Core idea:** Creativity is a spiritual practice, blocked by fear and critical inner voices. Morning pages and artist dates recover it.

**Key practices I kept:**
- Morning pages: 3 handwritten pages, stream of consciousness, first thing
- Artist dates: weekly solo outing to something new/inspiring

**Status:** Did the full 12 weeks. Morning pages are now a daily habit (mostly).

---

### Atomic Habits — James Clear ⭐⭐⭐⭐
**Core idea:** Habits are the compound interest of self-improvement. Small changes, remarkable results over time.

**Key frameworks:**
- 4 laws of behavior change: Make it obvious, attractive, easy, and satisfying
- Identity-based habits: decide who you want to be, then prove it with small wins
- Environment design beats motivation every time
- Never miss twice (the one rule that matters most after starting)

---

## Want to read

- The Power Broker — Robert Caro
- White Noise — Don DeLillo
- Range — David Epstein
- The Uninhabitable Earth — David Wallace-Wells
- Designing Your Life — Burnett & Evans
- The Pragmatic Programmer — Hunt & Thomas
- How to Take Smart Notes — Sönke Ahrens (perfect complement to Zettelkasten)
""",
    },
]

for doc_def in DOCUMENTS:
    d = post("/documents", {
        "title": doc_def["title"],
        "icon": doc_def.get("icon"),
        "description": doc_def.get("description"),
        "source_markdown": doc_def.get("source_markdown"),
        "visibility": "personal",
    })
    ok(f"document: {doc_def['title']}", d)

# ─────────────────────────────────────────────────────────────────────────────
print("\n🎉  Seed complete!")
print(f"""
Summary:
  • {len(TAG_DEFS)} tags
  • 1 collection (Journal)
  • {len(JOURNAL_ENTRIES)} journal entries
  • {len(PHILOSOPHY_NOTES)} philosophical notes
  • 30 workouts (last 90 days)
  • {len(HABIT_DEFS)} habits with ~60 days of occurrences
  • {len(GROCERY_LISTS)} grocery lists
  • 3 goals (financial, fitness, creative)
  • 2 budget accounts + {len(TRANSACTION_TEMPLATES)} transactions
  • 3 projects with sub-projects and todos
  • {len(PAST_EVENTS) + len(UPCOMING_EVENTS)} calendar events
  • {len(DOCUMENTS)} documents
""")
