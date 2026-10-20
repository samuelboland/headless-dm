# The isekai premise

The ordinary realm's bots were born in Azeroth. On an isekai realm they were not. Every bot, and the player, is an
ordinary person from the United States or Canada who woke up in Azeroth a few days ago in a body that is not theirs:
a gnome, an orc, a night elf, one of the walking dead. They kept their names, their accents, their jobs and the people
they left behind. They start at level 1, and there are enough of them that they keep running into one another.

The feel is Sword Art Online's:
- **Nobody can leave.** There is no way out anyone has found, and no word from home. A rumour says the way home is
  at the end of the road.
- **Everyone feels the system:** their level, health, mana, new skills. They talk about levelling openly.
- **Nobody knows whether death is safe.** You come back as a ghost and walk back, but no one knows whether that
  always works, and there are rumours of people who never came back.
- **Some push to the front;** others stay near the towns where they woke, waiting for a rescue.

A few of them played World of Warcraft back home and know exactly where they are, where things are and what is
coming. Others want that knowledge, and some resent them for it. Most have never heard of it. The name of the game,
and that knowledge, travel from person to person as they talk and travel together, and not everyone who hears it
believes it.

One setting switches it on, and the rest of this repository follows it. With the setting left out, nothing changes.

**Choose the premise before the bots exist.** Bots made on a native realm already have levels and lives written for
Azeroth. An isekai realm needs a fresh bot population, and stories written under one premise stop a run under the other.

---

## What changes

| Part | Native | Isekai |
|---|---|---|
| Who the bots are | People born in Azeroth | People from the US and Canada, days in, drawn from the guid |
| Starting level | Spread across level bands | Everyone at 1, and nobody is ever rerolled |
| Backstory | Homeland, family, the wars | Life before, the moment it happened, waking up, the first days |
| Earth name | — | Kept beside the name they go by here (`origin` column) |
| Companies | Sworn companies with histories | Bands of arrivals that formed in the last few days |
| Knowing it is a game | Never | Everyone feels levels and skills; only some know it is World of Warcraft |
| Chat | In-world speech only | Their own modern voice; slang and home are fine |
| Filtered words | Game and modern words | Only words that break the frame: AI, language model, roleplay, prompt |
| Faction loyalty | Loyal to their side | None yet; the other faction still sounds foreign |
| The player | A person of Azeroth | An arrival too, who knows it is the game |

The era still decides what has happened in Azeroth. A person who played may know what the game had later, and may
say so, but none of it has happened here.

### Who someone was

Each person is drawn from their character's guid, so a rerun draws the same person. The model then writes the
person to those facts, and is told not to trade them for something more typical. Drawing rather than letting the
model choose is what keeps fifty people from all being Sarah Chen, a warm, wry software engineer from Seattle.

- `services/common/premise.py`:
  - home state or province, weighted by population;
  - city, suburb, town or countryside;
  - age;
  - a job that fits the age;
  - a household that fits the age;
  - what they were doing when it happened;
  - how much they played games. About one in five played World of Warcraft.
- `services/common/people.py`:
  - a real first name common in their birth year, and a family name from a family background weighted by where
    they live (a Quebecer is mostly French-Canadian, a Texan more often Mexican-American);
  - the five broad personality traits, with only the clear ones said;
  - faith, a hobby, a way of talking;
  - the one person back home they think of most, named and aged to fit;
  - what they left unfinished, what they miss, what they fear;
  - how they are taking it, and what they are doing about it (the front line, waiting in town, helping newcomers,
    trading, searching for someone).

The story tells the life. The drawn facts also ride in the bio on their own (`premise.sheet_line`), so the chat
model sees them even where the story leaves one out. Fifty draws give fifty different names and about 35 different
jobs and hobbies.

### How the knowledge spreads

`services/lore/awareness.py` runs every ten minutes. It looks at who actually spent time together since its last
look: a judged conversation between them, a bot-to-bot conversation, or a group they rode in. Where one knows and the
other does not, it rolls:

- from someone who played it: 25% (`AWARENESS_CHANCE_FIRSTHAND`)
- from someone who only heard it: 10% (`AWARENESS_CHANCE_SECONDHAND`)

The player counts as someone who played it. A bot who learns it gets a line in their story ("Ama told you this world
is a game called World of Warcraft, one they used to play"), and the bios are rebuilt and reloaded. The bios are also
rebuilt once a day even with no news, because each one says how many days the person has been here.

Every change is in the `awareness_event` table, so you can watch the word travel:

```bash
. ops/env.sh && db acore_characters -e "
  SELECT a.at, l.name AS learner, t.name AS teller, a.evidence FROM awareness_event a
  JOIN characters l ON l.guid = a.learner_guid LEFT JOIN characters t ON t.guid = a.teller_guid
  ORDER BY a.id DESC LIMIT 20;"
```

No chat prompt says the world is a game. If one did, every bot would know it at once and nothing would spread.

---

## Setting it up

Follow `docs/GUIDE.md` as usual. These are the places where an isekai realm differs.

### Phase 2 — site files

In `site/site.env`:

```sh
PREMISE=isekai
# The day everyone woke up. Bios count days from here. Defaults to REALM_FIRST_DAY.
ARRIVAL_DAY=2026-10-20
# The service that spreads the word. Off unless 1; turn it on in Phase 11.
AWARENESS_ENABLED=0
```

For a small realm, set `BOT_MIN` and `BOT_MAX` low (for example 20 and 25). Keep `BOT_GUILDS` small too, since a
band of arrivals is a handful of people.

### Phase 7 — configure

`ops/scripts/conf-apply.py` reads `PREMISE` and lays `conf/isekai/` over `conf/`. Its first line of output says which
premise it applied. Check that it says isekai **before the first boot**, because bots made at the first boot keep the
level they are made with:

```text
premise: isekai (conf/isekai/ laid over conf/)
```

The isekai layer sets bots to start at level 1 and never be rerolled (`DisableRandomLevels`, `RandombotStartingLevel`,
`PersistentProgression = 1`, level brackets off), and rewrites the chat prompts, the idle-chatter topics and the
filtered-word list.

`ops/scripts/conf-overrides.py`, which copies live config back into `conf/`, leaves the isekai values out of the base
files, so running it on an isekai realm does not turn the native realm isekai.

### Phase 10 — lore

- **10.3 temperaments:** load `sql/characters/temperaments-isekai.sql` instead of the in-world set.
  `ops/seed-world.sh` picks it by itself when `PREMISE=isekai`.
- **10.4 backstories:** the same commands. Read the sample for the isekai things instead:
  - a real-world first and last name, and a believable life from the drawn origin
  - waking up days ago, in that race's starting land
  - no great deeds, no years here, nobody born in Azeroth
  - game knowledge only for those who played it
- `restand`, `name-pools` and `repool` say they have nothing to do under isekai. That is correct: the people level up
  while living their story, and invented people from home get ordinary American and Canadian names.
- `era-scan` still reports later-age names. For someone who played, a hit framed as "in the game" is fine; read it.

### 10.5 — the main (G10)

The player is an arrival too, and knows this is World of Warcraft. When you write your own character's story through
the lore gate, write your life before, the waking and the first days. Game words are fine. The gate refuses what
breaks the premise: being born here, years here, great deeds days in.

Under isekai, an alt is another arrival who has come to know your main in these few days. A kin or sworn bond can be
someone you knew back home who came through too.

### Phase 11 — services

Install the units as usual; `ops/systemd/install.sh --user` includes `wow-awareness`. Then set
`AWARENESS_ENABLED=1` in `site/site.env` and:

```bash
systemctl --user enable --now wow-awareness
```

Try one pass first without writing anything:

```bash
. ops/env.sh && python3 "$REPO/services/lore/awareness.py" --once --dry-run
```

The dry run needs the awareness tables, so run `--once` for real at least once before it.

---

## Settings

| Key (`site/site.env`) | Default | What |
|---|---|---|
| `PREMISE` | `native` | `isekai` switches everything on this page |
| `ARRIVAL_DAY` | `REALM_FIRST_DAY` | The day everyone woke up |
| `AWARENESS_ENABLED` | `0` | The spreading service; off unless 1 |
| `AWARENESS_CHANCE_FIRSTHAND` | `0.25` | Chance a player of the game tells someone per meeting |
| `AWARENESS_CHANCE_SECONDHAND` | `0.10` | Chance someone who only heard it passes it on |

Kill switches for the spreading service: `AWARENESS_ENABLED=0`, `systemctl --user stop wow-awareness`, or a file named
`PAUSE` beside `services/lore/awareness.py`.

---

## Known limits

- **Bots should wake in their own race's starting zone.** On the first isekai boot, all 24 bots were in their
  own race's starting zone. The playerbots code doesn't promise that.
- **Two lines the chat module hard-codes push against talk of levels:** "Stay in character at all times… speak
  only of what someone here could see, touch, or have heard tell of" and "Do not break character for any reason"
  (`mod-ollama-chat_roleplay.cpp`). The isekai system prompt answers them; making them config keys needs a module
  change.
- **Body and person share a gender.** Nothing draws a different one.
- **Motivation targets** are often people or places back home. Anything that sends bots toward their target's place
  will find names it cannot place, and skips them.
- **The memory writer drops a note that repeats four words of the system prompt,** so a note like "came back to
  their body" can be lost. The log says "echoes the prompt" when it happens.
- **Alts written by the `alts` command get a drawn origin,** so their stored game knowledge can say they never
  played, while the spreading service treats every character on the player's account as knowing. Alts written
  through the lore gate are stored as knowing.
- **The main's real name and home live only in its sheet text.** The sheet's table has no origin column.
- **Nothing here has been run against a live realm yet.** Every piece was checked with stand-ins for the database
  and the models.
