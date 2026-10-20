"""Who the bots are: the realm's premise (isekai branch).

Two premises, chosen by PREMISE in site/site.env:

  native   (the default) the bots were born in Azeroth and have lived there all their lives. Everything
           else in this repository was written for it, and nothing changes when PREMISE is unset.
  isekai   every bot, and the player, is an ordinary person from the United States or Canada who woke up in
           Azeroth a few days ago in a body that is not theirs, at the very start of their road (level 1).
           A few of them played World of Warcraft and recognise the place; the rest do not, and word of it
           spreads from person to person (services/lore/awareness.py).

The era (era.py) still decides what has happened in Azeroth. A person who played the game may *know about*
later chapters as things the game had; none of them has *happened* here.

This module is the contract the services share: the premise text, a person's origin (drawn, not
invented, so a few hundred people from two countries do not all come out as a software engineer from
Seattle), what they know of the game, and how long they have been here. Stdlib only.
"""
import datetime as dt
import hashlib
import random

from common import site

NATIVE, ISEKAI = "native", "isekai"


def current():
    value = (site.get("PREMISE", NATIVE) or NATIVE).strip().lower()
    if value not in (NATIVE, ISEKAI):
        raise SystemExit(f"PREMISE={value!r} in site/site.env; known: {NATIVE}, {ISEKAI}")
    return value


def is_isekai():
    return current() == ISEKAI


# ---------------------------------------------------------------------------
# the premise, as every isekai prompt states it

PREMISE_TEXT = (
    "A few days ago, without warning, a few thousand ordinary people from the United States and Canada woke "
    "up in Azeroth, each in a body that is not their own: a human, a dwarf, a gnome, a night elf, an orc, a "
    "troll, a tauren, or one of the walking dead the Forsaken. No one knows why or how, or whether there is a "
    "way back. They kept their own memories, names, accents and habits. Their new bodies came with "
    "reflexes they are only starting to understand: a warrior's grip, a priest's healing warmth, a mage's "
    "spark, a hunter's bond with a beast. Each woke at the very start of the road, untrained and weak, in "
    "their new body's homeland. Dying does not stick here: you come back as a ghost beside a winged spirit "
    "and walk back to your body, and no one knows whether that will always hold. The people born in Azeroth "
    "go about their lives as if nothing has happened and treat the newcomers as if they had always been "
    "here. The arrivals keep running into one another. A few of them used to play a computer game called "
    "World of Warcraft and recognise this world from it; that word is spreading, and not everyone "
    "believes it.")


def setting(e):
    """The setting line an isekai prompt opens with: the premise, then the era's Azeroth."""
    return PREMISE_TEXT + " The Azeroth they woke in is " + e["setting"]


# ---------------------------------------------------------------------------
# where each person came from: drawn from the guid, so a rerun draws the same person

# Weighted roughly by population, so most people come from where most people live.
HOMES = [
    ("California", 39), ("Texas", 30), ("Florida", 22), ("New York", 20), ("Pennsylvania", 13),
    ("Illinois", 13), ("Ohio", 12), ("Georgia", 11), ("North Carolina", 11), ("Michigan", 10),
    ("New Jersey", 9), ("Virginia", 9), ("Washington", 8), ("Arizona", 7), ("Tennessee", 7),
    ("Massachusetts", 7), ("Indiana", 7), ("Missouri", 6), ("Maryland", 6), ("Wisconsin", 6),
    ("Colorado", 6), ("Minnesota", 6), ("South Carolina", 5), ("Alabama", 5), ("Louisiana", 5),
    ("Kentucky", 5), ("Oregon", 4), ("Oklahoma", 4), ("Connecticut", 4), ("Utah", 3), ("Iowa", 3),
    ("Nevada", 3), ("Arkansas", 3), ("Mississippi", 3), ("Kansas", 3), ("New Mexico", 2), ("Nebraska", 2),
    ("Idaho", 2), ("West Virginia", 2), ("Hawaii", 1), ("New Hampshire", 1), ("Maine", 1), ("Montana", 1),
    ("Rhode Island", 1), ("Delaware", 1), ("South Dakota", 1), ("North Dakota", 1), ("Alaska", 1),
    ("Vermont", 1), ("Wyoming", 1),
    ("Ontario", 16), ("Quebec", 9), ("British Columbia", 5), ("Alberta", 5), ("Manitoba", 1),
    ("Saskatchewan", 1), ("Nova Scotia", 1), ("New Brunswick", 1), ("Newfoundland and Labrador", 1),
]
CANADA = {"Ontario", "Quebec", "British Columbia", "Alberta", "Manitoba", "Saskatchewan", "Nova Scotia",
          "New Brunswick", "Newfoundland and Labrador"}
PLACE_KINDS = [("a big city", 30), ("a suburb", 30), ("a small town", 25), ("the countryside", 15)]
AGES = [((18, 24), 14), ((25, 34), 22), ((35, 44), 20), ((45, 54), 18), ((55, 64), 16), ((65, 78), 10)]
JOBS = [
    "nurse", "line cook", "high school teacher", "truck driver", "retail cashier", "warehouse picker",
    "electrician", "plumber", "accountant", "software developer", "dental hygienist", "farmer", "mail carrier",
    "bartender", "paramedic", "police dispatcher", "hairdresser", "auto mechanic", "insurance adjuster",
    "college student", "graduate student", "stay-at-home parent", "retired machinist", "retired schoolteacher",
    "real estate agent", "pharmacist", "carpenter", "welder", "bank teller", "call center agent",
    "daycare worker", "barista", "lawyer", "paralegal", "veterinary technician", "landscaper", "roofer",
    "pastor", "social worker", "librarian", "graphic designer", "personal trainer", "physical therapist",
    "HVAC technician", "home health aide", "janitor", "forklift operator", "dairy farmer", "fishing deckhand",
    "oil field worker", "line worker at a car plant", "hotel housekeeper", "flight attendant", "pilot",
    "army veteran between jobs", "small business owner", "food truck owner", "musician who plays weddings",
    "substitute teacher", "data analyst", "marketing coordinator", "pizza delivery driver", "security guard",
    "junior doctor", "dentist", "civil engineer", "construction foreman", "court clerk", "city bus driver",
    "grocery store manager", "tattoo artist", "dog groomer", "ski lift operator", "museum guide",
    "unemployed and looking", "night shift stocker", "tax preparer", "youth hockey coach", "translator",
]
# What they were doing the moment it happened.
MOMENTS = [
    "asleep in bed", "driving home from work", "in the shower", "at the kitchen table", "on a night shift",
    "standing in line at a store", "watching TV on the couch", "at a family dinner", "on a bus",
    "walking the dog", "in a waiting room", "at the gym", "putting a child to bed", "on a lunch break",
    "in a lecture hall", "mowing the lawn", "at a bar with friends", "on a phone call",
]
LIVES = [
    ("lives alone", 22), ("has a partner and young kids", 18), ("has a partner, no kids", 16),
    ("is a single parent", 8), ("has grown kids", 14), ("lives with their parents", 8),
    ("lives with roommates", 8), ("is caring for an elderly parent", 4), ("is recently divorced", 2),
]

# What they know of the game, and how it is kept on lore_character.knows_game:
#   0  never played it, and has not been told
#   1  heard it from another arrival (knows_game_from names who); may not believe it
#   2  played it themselves, and recognised this world on their own
# Mostly 0 at the start: the knowledge is meant to spread, not to be handed out.
GAMER = [
    (0, "has never played video games much", 34),
    (0, "plays phone games, nothing like this", 22),
    (0, "plays other video games but never this one", 26),
    (2, "played World of Warcraft years ago, for a while", 11),
    (2, "played World of Warcraft a lot, and still sometimes does", 7),
]


def _pick(rng, weighted):
    items, weights = zip(*weighted)
    return rng.choices(items, weights=weights, k=1)[0]


def rng_for(guid, salt=""):
    """A random source fixed by the guid, so the same character always draws the same origin."""
    digest = hashlib.sha256(f"isekai:{guid}:{salt}".encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def origin(guid):
    """The facts a person's backstory is written to. The model invents their name and the details."""
    rng = rng_for(guid)
    lo, hi = _pick(rng, AGES)
    home = _pick(rng, HOMES)
    gamer = rng.choices(GAMER, weights=[w for _, _, w in GAMER], k=1)[0]
    return dict(
        home=home,
        country="Canada" if home in CANADA else "the United States",
        place_kind=_pick(rng, PLACE_KINDS),
        age=rng.randint(lo, hi),
        job=rng.choice(JOBS),
        life=_pick(rng, LIVES),
        moment=rng.choice(MOMENTS),
        knows_game=gamer[0],
        gaming=gamer[1],
    )


def origin_line(o):
    """The origin as the prompt states it."""
    return (f"Before: {o['age']} years old, from {o['place_kind']} in {o['home']}, {o['country']}; worked as "
            f"{'an' if o['job'][0] in 'aeiouAEIOU' else 'a'} {o['job']}; {o['life']}; {o['gaming']}. "
            f"When it happened they were {o['moment']}.")


# ---------------------------------------------------------------------------
# what a person knows of the game, as the projected bio says it to them

def knowledge_line(level, source_name=None):
    if level >= 2:
        return ("You played World of Warcraft back home, and you know this is that world: the places, the "
                "people, even what is coming. You can't prove it to anyone, and you wonder what it means for "
                "getting home.")
    if level == 1:
        who = source_name or "Another arrival"
        return (f"{who} told you this world is a computer game called World of Warcraft, one they used to play. "
                "You haven't decided whether you believe it.")
    return ("You have no idea where this place is. Nobody you have met has been able to explain it, and you "
            "have never heard of World of Warcraft.")


# ---------------------------------------------------------------------------
# how long they have been here. REALM_FIRST_DAY is the day everyone woke up.

def arrival_day():
    raw = site.get("ARRIVAL_DAY", "") or site.get("REALM_FIRST_DAY", "")
    try:
        return dt.date.fromisoformat(raw)
    except ValueError:
        return dt.date.today()


def days_here(today=None):
    return max(0, ((today or dt.date.today()) - arrival_day()).days)


def days_line(today=None):
    n = days_here(today)
    if n == 0:
        return "You woke up here today."
    if n == 1:
        return "You woke up here yesterday."
    return f"You woke up here {n} days ago."


# ---------------------------------------------------------------------------
# the judge's question, for the isekai premise
#
# era.judge_prompt asks whether a text treats a later age as real. That question is still asked here, but it is
# not the only one: a story can be true to the era and still break this premise, by giving a person years of
# history in Azeroth, deeds no one can do in their first few days, or a life that never happened in the real
# world. A gamer's knowledge of later chapters is the one thing the era judge would wrongly flag, so it is
# allowed here, and only as knowledge of the game.

GAME_KNOWLEDGE = {
    0: "This person has never played World of Warcraft and does not know this world comes from a game. Any "
       "knowledge of the game, or of what is coming, is wrong for them.",
    1: "Another arrival has told this person this world is from a computer game called World of Warcraft. They "
       "may repeat what they were told, as hearsay, but they never played it themselves.",
    2: "This person played World of Warcraft back home. They may know of the game's later chapters and say so, "
       "but only as things the game had (\"in the game, ...\"), never as things that have happened here.",
}


def judge_prompt(e, text, knows_game=0, known=()):
    """The isekai counterpart of era.judge_prompt; the same reply shape, so fleet.Judge reads it unchanged."""
    names = ", ".join(sorted({n for n in known if n}))
    return ("You check writing for a story with a fixed premise. " + setting(e) + "\n\n"
            "These belong to Azeroth's present or past and are fine: " + e["judge_allowed"] + "\n\n"
            + ("These are people, companies and creatures of the present, and naming them is fine: " + names + "\n\n"
               if names else "")
            + "These have NOT happened in Azeroth yet: " + e["judge_forbidden"] + "\n\n"
            + GAME_KNOWLEDGE.get(knows_game, GAME_KNOWLEDGE[0]) + "\n\n"
            "The person in the text is an ordinary person from the United States or Canada who arrived a few "
            "days ago. Real places, brands, jobs and everyday life back home are fine, and so are the words "
            "game, player, server and level.\n\n"
            'Text:\n"""\n' + text + '\n"""\n\n'
            "Is any of these true? (1) The text treats something that has not happened in Azeroth yet as having "
            "happened here, or knows of it in a way this person could not. (2) It gives the person deeds, fame, "
            "rank or years of history in Azeroth beyond a few days at the very start of the road: no great "
            "battles, no campaigns, no titles, no childhood there. (3) It makes them anything but an ordinary "
            "person from the real United States or Canada: born in Azeroth, from an invented country, or a "
            "famous or real, identifiable person. Mentions of things that are fine do not count. Reply with "
            'JSON only: {"out_of_time": true or false, "evidence": "the offending words, or an empty string"}')
