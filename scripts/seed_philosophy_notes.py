"""
Seed script: Philosophy notes (Stoicism, Buddhism, Taoism, Epicureanism)
Demonstrates Zettelkasten-style atomic notes with tags and [[wikilinks]].

Usage (from the repo root, with your local API running):
    python scripts/seed_philosophy_notes.py

Defaults to http://localhost:1338 with your local dev credentials.
Override with env vars:
    API_URL=http://... EMAIL=... PASSWORD=... python scripts/seed_philosophy_notes.py
"""

from __future__ import annotations

import os
import sys
import json
import urllib.request
import urllib.error

API_URL = os.environ.get("API_URL", "http://localhost:1338").rstrip("/")
EMAIL    = os.environ.get("EMAIL",    "brandon@life-dashboard.local")
PASSWORD = os.environ.get("PASSWORD", "password")


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def req(method: str, path: str, body=None, token: str | None = None):
    url = API_URL + path
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"  HTTP {e.code} on {method} {path}: {body[:200]}")
        raise


# ── Auth ──────────────────────────────────────────────────────────────────────

def login() -> str:
    print(f"Logging in as {EMAIL}…")
    resp = req("POST", "/auth/login", {"email": EMAIL, "password": PASSWORD})
    token = resp.get("access_token")
    if not token:
        print("Login failed — no access_token in response:", resp)
        sys.exit(1)
    print("  ✓ Logged in\n")
    return token


# ── Tags ──────────────────────────────────────────────────────────────────────

TAG_DEFS = [
    {"name": "stoicism",      "color": "#8B7355"},
    {"name": "buddhism",      "color": "#C68B2F"},
    {"name": "taoism",        "color": "#4A7C59"},
    {"name": "epicureanism",  "color": "#6B8CAE"},
    {"name": "philosophy",    "color": "#7B6B9E"},
]

def ensure_tags(token: str) -> dict[str, str]:
    """Create tags if they don't exist. Returns {name: id}."""
    existing = req("GET", "/tags?limit=200", token=token).get("items", [])
    name_to_id = {t["name"]: t["id"] for t in existing}

    for td in TAG_DEFS:
        if td["name"] not in name_to_id:
            t = req("POST", "/tags", td, token=token)
            name_to_id[t["name"]] = t["id"]
            print(f"  + tag: {td['name']}")
        else:
            print(f"  · tag exists: {td['name']}")

    print()
    return name_to_id


# ── Notes ─────────────────────────────────────────────────────────────────────
# Wikilinks use exact note titles defined below — they'll be resolved
# server-side after all notes are created.

NOTES = [
    {
        "title": "The Dichotomy of Control",
        "tags": ["stoicism", "philosophy"],
        "content_md": """\
# The Dichotomy of Control

Epictetus opens the *Enchiridion* with a clean distinction:

> "Some things are in our control and others not."

What is **in our control**: judgment, desire, motivation, opinion.
What is **not in our control**: body, reputation, property, external events.

This is the load-bearing beam of Stoic practice. Nearly every other technique \
rests on it. Anxiety, grief, and anger almost always trace back to placing \
value on things outside your control.

**Practical implication**: Before reacting to any difficulty, pause and ask: \
*Is this in my control?* If not, your only task is to choose your response.

See also: [[Amor Fati]], [[Equanimity]], [[Logos]]
""",
    },
    {
        "title": "The Four Noble Truths",
        "tags": ["buddhism", "philosophy"],
        "content_md": """\
# The Four Noble Truths

The Buddha's first teaching after enlightenment. A diagnostic framework \
more than a creed:

1. **Dukkha** — suffering, unsatisfactoriness, pervades ordinary experience
2. **Samudaya** — suffering arises from craving (*tanha*) and clinging
3. **Nirodha** — cessation of craving ends suffering
4. **Magga** — the [[The Eightfold Path]] is the route to cessation

The medical analogy is useful: identify the illness, identify the cause, \
confirm the cure exists, follow the treatment.

Importantly, the Buddha didn't say life is *only* suffering — he said \
suffering is *embedded in* ordinary experience, particularly wherever we \
cling to things that change.

See also: [[Impermanence]], [[The Middle Way]]
""",
    },
    {
        "title": "The Eightfold Path",
        "tags": ["buddhism"],
        "content_md": """\
# The Eightfold Path

The fourth Noble Truth made concrete. Eight interrelated practices, not \
sequential steps:

- **Wisdom**: Right View, Right Intention
- **Ethics**: Right Speech, Right Action, Right Livelihood
- **Meditation**: Right Effort, Right Mindfulness, Right Concentration

The path is described as a wheel — all eight support each other. You \
don't finish one and move to the next; you deepen all of them simultaneously.

**Contrast with Stoic practice**: The Stoics also divide their discipline \
(logic, physics, ethics) but the eight fold path has a stronger emphasis on \
formal meditation as part of the practice.

See also: [[The Four Noble Truths]], [[The Middle Way]], [[Equanimity]]
""",
    },
    {
        "title": "Memento Mori",
        "tags": ["stoicism"],
        "content_md": """\
# Memento Mori

Latin: *"Remember that you will die."*

A core Stoic contemplative practice. Marcus Aurelius returned to it \
constantly in the *Meditations*. The point is not morbid — it is clarifying.

When you hold your mortality in mind:
- Trivial annoyances lose their grip
- Time with people you love becomes charged with meaning
- The compulsion to impress others fades

**The temporal version**: Treat each morning as if you might not see the \
evening. Not as anxiety, but as an invitation to act rightly *now*.

Buddhism addresses the same territory via [[Impermanence]] (anicca). \
The phenomenology is similar; the metaphysical framing differs.

See also: [[The Dichotomy of Control]], [[Amor Fati]], [[Impermanence]]
""",
    },
    {
        "title": "Impermanence",
        "tags": ["buddhism", "philosophy"],
        "content_md": """\
# Impermanence

**Anicca** in Pali — one of Buddhism's three marks of existence alongside \
*dukkha* (suffering) and *anatta* (non-self).

Everything that arises passes away. This applies to:
- Pleasant experiences (so enjoy them without clinging)
- Unpleasant experiences (so endure them without despair)
- The self itself (which Buddhist metaphysics treats as a process, not a thing)

**Cross-tradition resonances**:
- Heraclitus: *"You cannot step in the same river twice"*
- Stoics: the *logos* moves through constant change — [[Memento Mori]] is the practice of holding this
- Taoism: [[The Flow of the Tao]] is precisely the flow of continuous change

The difference: Buddhism uses impermanence as a direct antidote to clinging. \
Taoism uses it as an invitation to move *with* change rather than against it.

See also: [[The Four Noble Truths]], [[Memento Mori]], [[The Flow of the Tao]]
""",
    },
    {
        "title": "The Middle Way",
        "tags": ["buddhism", "philosophy"],
        "content_md": """\
# The Middle Way

Before the Buddha's enlightenment, he had tried both extremes: the indulgence \
of a royal life and the severe asceticism of the forest renunciants. Neither worked.

The Middle Way (*majjhima patipada*) avoids:
- **Sensual indulgence**: chasing pleasure as the point of life
- **Self-mortification**: punishing the body as the path to liberation

This isn't just a lifestyle prescription — it's an epistemological stance. \
Right View means neither nihilism nor eternalism. Right Practice means neither \
forced effort nor passivity.

**Compare with Epicurus**: [[Ataraxia]] also rejects extreme asceticism, \
but Epicurus grounds this in the pursuit of a specific kind of pleasure \
(katastematic pleasure, absence of pain). The Buddha's framing is different — \
the goal is liberation from the pleasure/pain cycle altogether.

See also: [[The Four Noble Truths]], [[The Eightfold Path]], [[Equanimity]]
""",
    },
    {
        "title": "Equanimity",
        "tags": ["stoicism", "buddhism", "taoism", "philosophy"],
        "content_md": """\
# Equanimity

A word that appears across traditions but means something slightly different in each:

**Stoic apatheia**: freedom from *pathē* (passions that distort judgment). \
Not the absence of feeling, but the absence of *irrational* passion. \
The sage still experiences *eupatheiai* — good emotions like joy, caution, \
and wish.

**Buddhist upekkha**: the fourth *brahmaviharā* (divine abiding). Balanced \
mind that neither clings to pleasant experience nor pushes away unpleasant. \
Often misread as detachment or indifference — it's closer to *stable warmth*.

**Taoist balance**: [[Wu Wei]] produces a kind of equanimity by not \
struggling against the grain of things. The Tao Te Ching describes the sage \
as unmoved by praise or blame — not because they don't care, but because they \
are aligned with [[The Flow of the Tao]].

The practical question: Can equanimity be cultivated directly, or is it a \
*byproduct* of other practices (right action, meditation, alignment with nature)?

See also: [[The Dichotomy of Control]], [[The Middle Way]], [[Wu Wei]]
""",
    },
    {
        "title": "Wu Wei",
        "tags": ["taoism"],
        "content_md": """\
# Wu Wei

Chinese: 無為 — often translated "non-action" or "effortless action."

A central concept in Taoism, especially the *Tao Te Ching* and the *Zhuangzi*. \
The key: wu wei is *not* passivity or laziness. It means acting in harmony \
with the natural flow of things rather than forcing, striving, or contriving.

**Lao Tzu's examples**:
- Water doesn't try to wear down rock — it simply follows its nature
- The best ruler governs so quietly the people barely know he exists
- The skilled craftsman moves without deliberate effort

**Psychological parallel**: Csikszentmihalyi's *flow state* — complete \
absorption in an activity where action feels effortless. Wu wei is something \
like a permanent orientation toward that state.

**Contrast with Stoic discipline**: Stoicism involves active rational effort \
to identify and correct false judgments. Wu wei suggests the effort itself may \
be the problem. Both arrive at [[Equanimity]] but via different routes.

See also: [[The Flow of the Tao]], [[Equanimity]]
""",
    },
    {
        "title": "The Flow of the Tao",
        "tags": ["taoism", "philosophy"],
        "content_md": """\
# The Flow of the Tao

The Tao (道) is the first principle of Taoist philosophy. Lao Tzu opens \
the *Tao Te Ching* with a warning: *"The Tao that can be named is not the \
eternal Tao."*

This is not evasion — it's a claim about the limits of conceptual thought. \
The Tao is the pattern underlying all change, the way things move and transform. \
It cannot be captured in a definition precisely because it *is* the process \
of definition occurring.

**Three characteristics**:
1. **Undifferentiated**: before all distinctions (being/non-being, yin/yang)
2. **Spontaneous**: it does not strive or intend
3. **All-pervading**: nothing is outside it

**Parallel with Stoic Logos**: [[Logos]] in Stoicism is also a rational \
principle pervading nature. Both traditions see the cosmos as ordered, not \
chaotic. The difference: Logos is *rational* (accessible to reason); \
the Tao explicitly exceeds rational grasp.

See also: [[Wu Wei]], [[Impermanence]], [[Logos]]
""",
    },
    {
        "title": "Amor Fati",
        "tags": ["stoicism", "philosophy"],
        "content_md": """\
# Amor Fati

Latin: *"Love of fate."* The phrase is Nietzsche's, but the concept is \
Stoic in origin.

Marcus Aurelius: *"Accept the things to which fate binds you."*
Epictetus: *"Seek not that the things which happen should happen as you wish; \
but wish the things which happen to be as they are."*
Nietzsche took this further: not merely *accept* what happens, but \
*love* it — not as resignation but as affirmation.

**The practical difference between acceptance and amor fati**:
- Acceptance: "This is happening and I won't resist it."
- Amor fati: "This is happening and it is exactly what I would choose."

The second is harder and stranger. It requires finding something meaningful \
or fitting in every outcome — including failure, loss, and death.

**Buddhist resonance**: [[Impermanence]] points in the same direction. \
When you fully accept that everything changes, resistance to change \
becomes obviously futile. But Buddhism tends to dissolve the *self* that \
would love or not love fate, whereas amor fati strengthens individual will.

See also: [[The Dichotomy of Control]], [[Memento Mori]], [[Impermanence]]
""",
    },
    {
        "title": "Ataraxia",
        "tags": ["epicureanism", "philosophy"],
        "content_md": """\
# Ataraxia

Greek: ἀταραξία — *tranquility*, literally "not disturbed."

The Epicurean summum bonum. Often paired with *aponia* (freedom from \
bodily pain). Together they constitute *eudaimonia* for Epicurus — not \
the excitement of pleasure but the stable condition of having no outstanding \
pain or anxiety.

**What disturbs ataraxia?**
- Fear of death (Epicurus: *"Death is nothing to us"* — when death is, \
you are not; when you are, death is not)
- Fear of divine punishment
- Unsatisfied desires for things beyond one's natural needs
- The opinions of others

**Epicurean therapy**: Philosophy is a *medicine for the soul*. The \
*tetrapharmakos* (four-fold remedy): don't fear god, don't fear death, \
what is good is easy to get, what is terrible is easy to endure.

**Compare with [[Equanimity]]**: Stoic apatheia and Epicurean ataraxia \
point at similar psychological states but differ in method. Stoics ground \
tranquility in virtue and reason; Epicurus grounds it in managing desires \
and cultivating friendship.

See also: [[The Pleasure Principle]], [[The Middle Way]], [[Equanimity]]
""",
    },
    {
        "title": "The Pleasure Principle",
        "tags": ["epicureanism"],
        "content_md": """\
# The Pleasure Principle

Epicurus is often misread as a hedonist who taught us to seek pleasure. \
The reality is more subtle.

He distinguished two kinds of pleasure:
- **Kinetic pleasure**: active, moving pleasures (eating, sex, entertainment) — \
these are fine but unstable and often followed by pain
- **Katastematic pleasure**: the stable pleasure of *being in a good state* \
— satisfied, healthy, free from anxiety

Epicurus recommended the second and was famously abstemious in practice \
(bread, water, cheese; a small garden; good friends).

**The mathematics of desire**: Natural and necessary desires (food, shelter, \
friendship) are easy to satisfy. Vain desires (fame, luxury, power) are \
insatiable by nature — pursuing them generates more craving, not satisfaction.

**Comparison across traditions**:
- The Buddhist critique of craving in [[The Four Noble Truths]] covers \
similar territory
- [[The Middle Way]] also rejects indulgence without endorsing asceticism
- The Stoics focus less on pleasure and more on virtue, but Marcus Aurelius \
notes that simple pleasures suffice for a good life

See also: [[Ataraxia]], [[The Middle Way]]
""",
    },
    {
        "title": "Logos",
        "tags": ["stoicism", "philosophy"],
        "content_md": """\
# Logos

Greek: λόγος — reason, word, rational principle.

For the Stoics, the Logos is the *active, rational principle* that structures \
and pervades the universe. It is not personal (not a god who intervenes) but \
it is intelligent — the universe is a living rational organism and Logos is \
its intelligence.

**Implications for ethics**:
- Living according to nature means living according to *Logos*
- Human reason is a fragment of the universal Logos — this is why reason \
is the highest human faculty
- [[The Dichotomy of Control]]: what is "up to us" is precisely our rational \
faculty, our share of Logos

**Compare with [[The Flow of the Tao]]**: Both Logos and the Tao are \
first principles that order all things. Key difference: Logos is explicitly \
*rational* and can be grasped (partially) through reason. The Tao exceeds \
rational comprehension by definition. This shapes very different practices: \
Stoics train reason; Taoists try to *quiet* the rational mind.

**Compare with Buddhist dharma**: The *dhamma* (Pali) refers both to the \
Buddha's teaching and to the underlying order of reality. It shares the \
universality of Logos but is framed in terms of causation and impermanence \
rather than rational structure.

See also: [[The Dichotomy of Control]], [[The Flow of the Tao]], [[Equanimity]]
""",
    },
]


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  Hearth — Philosophy Notes Seed Script")
    print("=" * 60)
    print(f"  API: {API_URL}\n")

    token = login()

    print("Ensuring tags exist…")
    tag_map = ensure_tags(token)

    print(f"Creating {len(NOTES)} notes…\n")
    created = 0
    skipped = 0

    # Fetch existing note titles to avoid duplicates
    existing = req("GET", "/notes?limit=500", token=token).get("items", [])
    existing_titles = {n["title"] for n in existing}

    for note_def in NOTES:
        title = note_def["title"]
        if title in existing_titles:
            print(f"  · skipping (exists): {title}")
            skipped += 1
            continue

        tag_ids = [tag_map[t] for t in note_def.get("tags", []) if t in tag_map]
        payload = {
            "title": title,
            "content_md": note_def["content_md"],
            "tag_ids": tag_ids,
        }
        try:
            req("POST", "/notes", payload, token=token)
            print(f"  + created: {title}")
            created += 1
        except Exception:
            print(f"  ✗ failed:  {title}")

    print(f"\nDone. {created} created, {skipped} skipped.")

    # ── Second pass: re-resolve all backlinks ─────────────────────────────────
    # Notes created before their targets had no targets to link to yet.
    # A lightweight PATCH (same content) re-runs _resolve_backlinks on each note.
    print("\nRe-resolving wikilinks across all notes (second pass)…")
    all_notes = req("GET", "/notes?limit=500", token=token).get("items", [])
    seed_titles = {n["title"] for n in NOTES}
    resolved = 0
    for n in all_notes:
        if n["title"] not in seed_titles:
            continue
        try:
            req("PATCH", f"/notes/{n['id']}", {"content_md": n.get("content_md")}, token=token)
            resolved += 1
        except Exception:
            print(f"  ✗ re-resolve failed: {n['title']}")
    print(f"  ✓ Re-resolved {resolved} notes\n")

    print("All done! Open your dashboard at http://localhost:3000/notes")
    print("Each note's backlinks panel will show which notes link to it.")


if __name__ == "__main__":
    main()
