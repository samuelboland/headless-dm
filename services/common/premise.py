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
import re

from common import people, site

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
    "troll, a tauren, or one of the walking dead the Forsaken. No one knows why or how. There is no way out "
    "that anyone has found, and no word from home. They kept their own memories, names, accents and habits. "
    "The world works like a game, and every one of them can feel it: their level, their health and their "
    "mana or rage or energy, new skills arriving as they grow stronger. Their bodies came with a class's "
    "reflexes they are only starting to understand: a warrior's grip, a priest's healing warmth, a mage's "
    "spark, a hunter's bond with a beast. Each woke at the very start of the road, level 1 and weak, in their "
    "new body's homeland. Dying puts you beside a winged spirit as a ghost, and you walk back to your body; "
    "nobody knows whether that always works or what each death costs, and there are rumours of people who "
    "never came back, so people are afraid to die. A rumour says the way home lies at the end of the road. "
    "Some push toward it, growing stronger as fast as they can; others stay near the towns where they woke, "
    "waiting for a rescue that has not come. The people born in Azeroth go about their lives as if nothing "
    "has happened and treat the newcomers as if they had always been here. The arrivals keep running into "
    "one another. A few of them played this very world back home as a computer game, World of Warcraft, and "
    "know where things are and what is coming; others want that knowledge, and some resent them for it. Word "
    "of it is spreading, and not everyone believes it.")


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
# (job, youngest, oldest): a job only goes to someone of an age that could hold it.
JOBS = [
    ("nurse", 22, 66), ("line cook", 18, 60), ("high school teacher", 23, 66), ("truck driver", 21, 70),
    ("retail cashier", 18, 75), ("warehouse picker", 18, 60), ("electrician", 20, 68), ("plumber", 20, 68),
    ("accountant", 23, 68), ("software developer", 21, 64), ("dental hygienist", 21, 64), ("farmer", 18, 80),
    ("mail carrier", 21, 66), ("bartender", 21, 60), ("paramedic", 20, 60), ("police dispatcher", 21, 64),
    ("hairdresser", 18, 72), ("auto mechanic", 18, 70), ("insurance adjuster", 23, 66), ("college student", 18, 26),
    ("graduate student", 22, 32), ("stay-at-home parent", 22, 50), ("retired machinist", 62, 80),
    ("retired schoolteacher", 58, 80), ("real estate agent", 22, 75), ("pharmacist", 25, 68), ("carpenter", 18, 68),
    ("welder", 18, 64), ("bank teller", 18, 64), ("call center agent", 18, 66), ("daycare worker", 18, 64),
    ("barista", 18, 40), ("lawyer", 25, 75), ("paralegal", 21, 66), ("veterinary technician", 20, 60),
    ("landscaper", 18, 64), ("roofer", 18, 55), ("pastor", 26, 78), ("social worker", 22, 68), ("librarian", 23, 72),
    ("graphic designer", 20, 64), ("personal trainer", 19, 55), ("physical therapist", 24, 66),
    ("HVAC technician", 19, 66), ("home health aide", 18, 70), ("janitor", 18, 72), ("forklift operator", 18, 64),
    ("dairy farmer", 18, 78), ("fishing deckhand", 18, 55), ("oil field worker", 18, 58),
    ("line worker at a car plant", 18, 64), ("hotel housekeeper", 18, 68), ("flight attendant", 21, 64),
    ("pilot", 23, 65), ("army veteran between jobs", 22, 50), ("small business owner", 24, 78),
    ("food truck owner", 22, 66), ("musician who plays weddings", 18, 72), ("substitute teacher", 22, 75),
    ("data analyst", 21, 64), ("marketing coordinator", 21, 50), ("pizza delivery driver", 18, 50),
    ("security guard", 18, 74), ("junior doctor", 26, 34), ("family doctor", 32, 72), ("dentist", 26, 70),
    ("civil engineer", 22, 68), ("construction foreman", 28, 66), ("court clerk", 21, 68), ("city bus driver", 22, 70),
    ("grocery store manager", 24, 66), ("tattoo artist", 19, 60), ("dog groomer", 18, 66), ("ski lift operator", 18, 70),
    ("museum guide", 18, 78), ("unemployed and looking", 18, 64), ("night shift stocker", 18, 60),
    ("tax preparer", 22, 78), ("youth hockey coach", 20, 70), ("translator", 22, 72), ("retired nurse", 60, 80),
    ("retired trucker", 62, 80), ("retired, volunteers at the food bank", 63, 80), ("greeter at a big-box store", 62, 80),
    ("high school senior with a part-time job", 18, 19), ("gig driver for delivery apps", 18, 60),
    ("content creator with a small following", 18, 38), ("Uber driver after retiring early", 55, 72),
]
# What they were doing the moment it happened.
MOMENTS = [
    "asleep in bed", "driving home from work", "in the shower", "at the kitchen table", "on a night shift",
    "standing in line at a store", "watching TV on the couch", "at a family dinner", "on a bus",
    "walking the dog", "in a waiting room", "at the gym", "putting a child to bed", "on a lunch break",
    "in a lecture hall", "mowing the lawn", "at a bar with friends", "on a phone call",
]
# Households are drawn by age: people.LIVES_BY_AGE.

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


def origin(guid, gender=None):
    """The facts a person's backstory is written to, all drawn: the model writes the person, not their facts.

    gender is the character's (0 male, 1 female; the person and the body share it). Without it the person's
    name and family are left undrawn, as an origin stored before people.py existed has them.
    """
    rng = rng_for(guid)
    lo, hi = _pick(rng, AGES)
    home = _pick(rng, HOMES)
    gamer = rng.choices(GAMER, weights=[w for _, _, w in GAMER], k=1)[0]
    age = rng.randint(lo, hi)
    o = dict(
        home=home,
        country="Canada" if home in CANADA else "the United States",
        place_kind=_pick(rng, PLACE_KINDS),
        age=age,
        job=rng.choice([j for j, lo_, hi_ in JOBS if lo_ <= age <= hi_]),
        life=people.life_for(rng, age),   # households that fit the age (people.LIVES_BY_AGE)
        moment=rng.choice(MOMENTS),
        knows_game=gamer[0],
        gaming=gamer[1],
    )
    if gender is not None:
        # Its own stream, so the draws above are the same as before people.py.
        o.update(people.draw(rng_for(guid, "person"), home, o["age"], int(gender), o["life"]))
    return o


def origin_line(o):
    """The origin as the prompt states it."""
    if o.get("player"):
        return player_origin_line(o)
    line = (f"Before: {o['age']} years old, from {o['place_kind']} in {o['home']}, {o['country']}; worked as "
            f"{'an' if o['job'][0] in 'aeiouAEIOU' else 'a'} {o['job']}; {o['life']}; {o['gaming']}. "
            f"When it happened they were {o['moment']}.")
    if not o.get("personality"):
        return line
    lb = o["left_behind"]
    return line + (
        f"\nReal name: {o['earth_name']}."
        f"\nPersonality: {'; '.join(o['personality'])}."
        f"\nFaith: {o['faith']}. Spare time back home: {o['hobby']}. Way of talking: {o['speech']}."
        f"\nThe one they think of most: {lb['relation']}, {lb['name']}, {lb['age']}."
        f"\nLeft unfinished: they {o['unfinished']}. Misses most: {o['misses']}. Afraid of: {o['fear']}."
        f"\nHow they are taking it: {o['coping']}. What they are doing about it: {o['stance']}.")


def sheet_line(o):
    """The drawn facts as the bio says them to the person, in the second person like the story beside it.

    The story is a life told in a few hundred words; it cannot carry every fact without running long, so the
    facts ride in the bio on their own (gen_backstories.project appends this) and the story is free to tell.
    Empty for an origin without the people.py draw, and for a player's character, who wrote their own.
    """
    if o.get("player") or not o.get("personality"):
        return ""
    lb = o["left_behind"]
    return (f"Back home you were {o['earth_name']}, {o['age']}, "
            f"{'an' if o['job'][0] in 'aeiouAEIOU' else 'a'} {o['job']} from {o['place_kind']} in {o['home']}. "
            f"The one you think of most is {lb['relation']}, {lb['name']}, {lb['age']}. "
            f"When it happened you {o['unfinished']}. You are {'; '.join(o['personality'])}. "
            f"Faith: {o['faith']}. Back home you loved {o['hobby']}. The way you talk: {o['speech']}. "
            f"You miss {o['misses']} most, and you are afraid of {o['fear']}. "
            f"Here you are {o['coping']}, and {o['stance']}.")


# ---------------------------------------------------------------------------
# the player, and the characters they write for themselves (services/lore/lore_gate.py)
#
# The player is an arrival too, and the one who certainly knows where they are: they are playing the game. So
# the characters they write for are kept at knows_game 2, the level awareness.py already gives every character
# that is not a bot. Their origin is not drawn from HOMES and JOBS the way a bot's is, because the player says
# who they were: it holds only what the player gave (their real name, where they are from) and leaves the rest
# empty, since a drawn job or age would sit beside the player's own story and contradict it in every later
# prompt that reads both.

PLAYER_KNOWS_GAME = 2
PLAYER_GAMING = "plays World of Warcraft, and knows this world is the game's"


def home_country(home):
    """The country a home back home is in, when it names one of HOMES; None when it names none of them."""
    for place, _ in HOMES:
        if home and re.search(r"\b" + re.escape(place) + r"\b", home, re.I):
            return "Canada" if place in CANADA else "the United States"
    return None


def player_origin(earth_name=None, home=None):
    """A player's character's origin: the same keys as origin(), with only what the player gave filled in."""
    return dict(
        player=True,
        earth_name=earth_name or None,
        home=home or None,
        country=home_country(home),
        place_kind=None,
        age=None,
        job=None,
        life=None,
        moment=None,
        knows_game=PLAYER_KNOWS_GAME,
        gaming=PLAYER_GAMING,
    )


def player_origin_line(o):
    """origin_line for a player's character: what they gave, and nothing in place of what they did not."""
    if o.get("home"):
        where = o["home"] + (f", {o['country']}" if o.get("country") and o["country"] not in o["home"] else "")
        return f"Before: from {where}; {o.get('gaming') or PLAYER_GAMING}; the rest is as their own story tells it."
    return f"Before: a life back home that their own story tells; {o.get('gaming') or PLAYER_GAMING}."


# ---------------------------------------------------------------------------
# what a person knows of the game, as the projected bio says it to them

def knowledge_line(level, source_name=None):
    if level >= 2:
        return ("You played World of Warcraft back home, and you know this is that world: the places, the "
                "people, which roads are dangerous, even what is coming. People ask you for help, and some "
                "resent you for knowing. You wonder what your knowledge means for getting home.")
    if level == 1:
        who = source_name or "Another arrival"
        return (f"{who} told you this world is a computer game called World of Warcraft, one they used to play. "
                "You haven't decided whether you believe it, or how much they aren't telling.")
    return ("You can feel that this world works like a game, with levels and skills, but you have no idea "
            "which one, or where this place is, and you have never heard of World of Warcraft.")


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
    0: "This person has never played World of Warcraft and does not know this world comes from it. They feel "
       "the levels and skills like everyone else and may call it a game, but naming World of Warcraft, or "
       "knowing its places, quests or what is coming, is wrong for them.",
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
            "game, player, server, level, health, mana, skill, quest and XP: everyone here can feel them.\n\n"
            'Text:\n"""\n' + text + '\n"""\n\n'
            "Is any of these true? (1) The text treats something that has not happened in Azeroth yet as having "
            "happened here, or knows of it in a way this person could not. (2) It gives the person deeds, fame, "
            "rank or years of history in Azeroth beyond a few days at the very start of the road: no great "
            "battles, no campaigns, no titles, no childhood there. (3) It makes them anything but an ordinary "
            "person from the real United States or Canada: born in Azeroth, from an invented country, or a "
            "famous or real, identifiable person. Mentions of things that are fine do not count. Reply with "
            'JSON only: {"out_of_time": true or false, "evidence": "the offending words, or an empty string"}')
