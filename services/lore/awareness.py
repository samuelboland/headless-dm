#!/usr/bin/env python3
"""Awareness: how the word "this world is a game" travels from person to person (isekai premise).

Under PREMISE=isekai a few arrivals played World of Warcraft and recognise Azeroth; the rest do not. This
service lets that knowledge spread only by people meeting, never by decree. Levels (common/premise.py):
0 doesn't know, 1 heard it from someone (lore_character.knows_game_from is who), 2 played it. Nobody's
level ever goes down, and a 1 can pass it on, but less readily than a 2.

What counts as having spent time together. Talking is what carries news, and time spent merely near each
other does not, so the evidence is taken from conversations, not proximity:
  - regard_log rows with source 'chat': regard.py's judge read an actual exchange between the two (bot to
    bot, or a bot and the player) and moved a feeling. This is the best evidence: a judged line of talk.
  - bot_talk: the written conversations bots have when no player is about, with both speakers named.
  - regard_log 'event' rows for joining a group or slaying something together: they did not necessarily
    talk, but a party shares hours and a channel, so it counts, and is labelled as such.
Left out on purpose: regard's presence moments ("crossed paths in Westfall"), which are written with
log_moments=False and so are not in regard_log at all, and ledger_chat itself, whose listener column is
empty for bot-to-bot lines and so cannot say who heard what.

The human player's characters (accounts that are not bots, per person_kind) are tellers at level 2 because
they are literally playing the game, so a bot who talks with the player may learn it from them. The
player's own character is never written to: its level is not stored, and it never needs to learn.

Each cycle (default 10 minutes):
  1. nothing happens unless PREMISE=isekai and AWARENESS_ENABLED=1, and there is no PAUSE file beside this one.
  2. read the pairs seen since the last cycle; for each pair where one knows more than the other, roll to
     pass it on: AWARENESS_CHANCE_FIRSTHAND (default 0.25) from a 2 to a 0, AWARENESS_CHANCE_SECONDHAND
     (default 0.10) from a 1 to a 0. A 0 becomes 1 with the teller recorded. Someone who learns this cycle
     does not teach until the next, so word moves one step per cycle.
  3. record each change in awareness_event and write a note into lore_character_note.
  4. after a change, and at least once per UTC day (the bios say how many days they have been here), run
     `gen_backstories.py project` and then `ollama reload` over the GM console. One console session at a
     time is all it serves, so both run in order from this one process.

Usage:
  python3 awareness.py [--interval 600]    service loop (systemd user unit wow-awareness)
  python3 awareness.py --once [--dry-run]  one cycle; --dry-run prints what would change and writes nothing
Kill switch: AWARENESS_ENABLED unset or 0, `systemctl --user stop wow-awareness`, or touch PAUSE beside this file.
"""
import argparse
import datetime as dt
import os
import random
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
# realpath: the unit may run this through the /opt/wow symlink, and abspath does not follow it.
_REAL = os.path.dirname(os.path.realpath(__file__))
SERVICES = os.path.dirname(_REAL)
REPO = os.path.dirname(SERVICES)
sys.path.insert(0, SERVICES)
from common import premise, site  # noqa: E402

PAUSE_FILE = os.path.join(HERE, "PAUSE")
TABLES_SQL = os.path.join(_REAL, "awareness_tables.sql")
PROJECT_CMD = [sys.executable, os.path.join(_REAL, "gen_backstories.py"), "project"]
FIRSTHAND, SECONDHAND = 0.25, 0.10   # default chances, see settings()
MAX_SEEN = 5000                      # most evidence rows read in one cycle


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# database (mysql CLI; credentials from site/secrets.env. Never printed.)

def _db():
    # Looked up on first use, so a disabled or non-isekai service never needs database credentials.
    return site.db("characters")


def sql(query, fetch=True):
    host, port, user, pw, db = _db()
    cmd = ["mysql", "--default-character-set=utf8mb4", "-h", host, "-P", port, "-u", user, db,
           "--batch", "--raw", "-N"]
    # On stdin: the table file is several statements and an argv string is capped.
    out = subprocess.run(cmd, input=query, env={"MYSQL_PWD": pw, "PATH": "/usr/bin:/bin"},
                         capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip())
    if not fetch:
        return []
    return [row.split("\t") for row in out.stdout.splitlines() if row]


def q(s):
    return "'" + str(s).replace("\\", "\\\\").replace("'", "\\'") + "'"


def ensure_schema():
    sql(open(TABLES_SQL).read(), fetch=False)
    if not sql("SELECT 1 FROM information_schema.tables WHERE table_schema = DATABASE() "
               "AND table_name = 'lore_character'"):
        return False   # gen_backstories has not made its tables yet; nobody to teach
    have = {r[0] for r in sql("SELECT column_name FROM information_schema.columns WHERE table_schema = "
                              "DATABASE() AND table_name = 'lore_character'")}
    # Same ALTER-if-missing as gen_backstories.ensure_schema, so it does not matter which starts first.
    for column, ddl in (("knows_game", "TINYINT NOT NULL DEFAULT 0"),
                        ("knows_game_from", "INT UNSIGNED NULL")):
        if column not in have:
            sql(f"ALTER TABLE lore_character ADD COLUMN {column} {ddl}", fetch=False)
    return True


def settings():
    def num(key, default):
        try:
            return max(0.0, min(1.0, float(site.get(key, default))))
        except ValueError:
            return default
    return (site.get("AWARENESS_ENABLED", "0") == "1",
            num("AWARENESS_CHANCE_FIRSTHAND", FIRSTHAND), num("AWARENESS_CHANCE_SECONDHAND", SECONDHAND))


# ---------------------------------------------------------------------------
# the decision, pure so it can be tried without a database

def decide(pairs, levels, rng, firsthand=FIRSTHAND, secondhand=SECONDHAND):
    """Who learns from whom this cycle.

    pairs   {(a, b): evidence}, each pair once whichever way round it was seen
    levels  {guid: level}, a player's characters already set to 2; a guid missing from it cannot learn
    Returns [(learner, teller, teller_level, evidence)]. Tellers are judged on the levels as they stood at
    the start of the cycle, and each learner learns at most once, so a single cycle moves word one step.
    """
    out, learned = [], set()
    ordered = sorted(pairs.items())
    rng.shuffle(ordered)   # no pair is favoured by the order the database returned them in
    for (a, b), why in ordered:
        la, lb = levels.get(a), levels.get(b)
        if la is None or lb is None or la == lb:
            continue
        learner, teller = (a, b) if la < lb else (b, a)
        if levels[learner] != 0 or levels[teller] < 1 or learner in learned:
            continue
        chance = firsthand if levels[teller] >= 2 else secondhand
        if rng.random() < chance:
            learned.add(learner)
            out.append((learner, teller, levels[teller], why))
    return out


# ---------------------------------------------------------------------------
# who met whom

def cursor(source):
    rows = sql(f"SELECT last_id FROM awareness_cursor WHERE source = {q(source)}")
    return int(rows[0][0]) if rows else None


def cursor_sql(source, last_id):
    return (f"INSERT INTO awareness_cursor (source, last_id) VALUES ({q(source)}, {int(last_id)}) "
            "ON DUPLICATE KEY UPDATE last_id = VALUES(last_id);")


def seen_pairs(interval):
    """(pairs {(low, high): evidence}, cursor updates sql). A first run, with no cursor, reads only the last
    interval's worth, so switching the service on does not replay the realm's whole history at once."""
    pairs, moves = {}, []

    def add(a, b, why):
        a, b = int(a), int(b)
        if a != b and a and b:
            pairs.setdefault((min(a, b), max(a, b)), why)

    cur = cursor("regard_log")
    since = f"id > {cur}" if cur is not None else f"ts > NOW() - INTERVAL {int(interval)} SECOND"
    # Chat moments rank first (a judged exchange), so they set the label when a pair has several.
    rows = sql("SELECT id, bot_guid, other_guid, source, reason FROM regard_log "
               f"WHERE {since} AND (source = 'chat' OR (source = 'event' AND (reason IN "
               "('took you into their company', 'joined your company') OR reason LIKE 'slew % together'))) "
               f"ORDER BY id LIMIT {MAX_SEEN}")
    for r in rows:
        add(r[1], r[2], "talked (judged chat)" if r[3] == "chat" else "rode in a group")
    last = max((int(r[0]) for r in rows), default=None)
    if last is None and cur is None:
        last = int(sql("SELECT COALESCE(MAX(id), 0) FROM regard_log")[0][0])
    if last is not None:
        moves.append(cursor_sql("regard_log", last))
    # Overheard bot-to-bot talk outranks a group event, so it replaces that label (but not a chat moment).
    cur = cursor("bot_talk")
    since = f"id > {cur}" if cur is not None else f"ts > NOW() - INTERVAL {int(interval)} SECOND"
    rows = sql(f"SELECT id, a_guid, b_guid FROM bot_talk WHERE {since} ORDER BY id LIMIT {MAX_SEEN}")
    for r in rows:
        key = (min(int(r[1]), int(r[2])), max(int(r[1]), int(r[2])))
        if key[0] != key[1] and pairs.get(key) in (None, "rode in a group"):
            pairs[key] = "talked (bot to bot)"
    last = max((int(r[0]) for r in rows), default=None)
    if last is None and cur is None:
        last = int(sql("SELECT COALESCE(MAX(id), 0) FROM bot_talk")[0][0])
    if last is not None:
        moves.append(cursor_sql("bot_talk", last))
    return pairs, "\n".join(moves)


def levels_for(guids):
    """({guid: level}, {guid: name}). Players' characters count as 2; a bot with no lore row is left out
    (it has nowhere to keep what it learns, and its level cannot be known)."""
    levels, names = {}, {}
    if not guids:
        return levels, names
    ids = ",".join(str(g) for g in sorted(guids))
    for guid, name, kind, lvl in sql(
            "SELECT c.guid, c.name, pk.kind, lc.knows_game FROM characters c "
            "JOIN person_kind pk ON pk.guid = c.guid LEFT JOIN lore_character lc ON lc.guid = c.guid "
            f"WHERE c.guid IN ({ids})"):
        names[int(guid)] = name
        if kind != "bot":
            levels[int(guid)] = 2           # a person playing the game; never written to
        elif lvl != "NULL":
            levels[int(guid)] = int(lvl)
    return levels, names


# ---------------------------------------------------------------------------
# applying it

def note_for(teller_name, teller_level):
    if teller_level >= 2:
        return f"{teller_name} told you this world is a game called World of Warcraft, one they used to play."
    return (f"{teller_name} told you this world is a game called World of Warcraft, "
            "something they had heard from another arrival.")


def apply(changes, names):
    """Write each change; the UPDATE only fires on a 0, so a race with gen_backstories cannot lower anyone."""
    done = 0
    for learner, teller, tl, why in changes:
        hit = sql(f"UPDATE lore_character SET knows_game = 1, knows_game_from = {teller} "
                  f"WHERE guid = {learner} AND knows_game = 0; SELECT ROW_COUNT();")
        if not hit or hit[0][0] != "1":
            continue
        sql("INSERT INTO awareness_event (learner_guid, teller_guid, from_level, to_level, evidence) VALUES "
            f"({learner}, {teller}, 0, 1, {q(why)}); "
            "INSERT INTO lore_character_note (guid, source, note) VALUES "
            f"({learner}, 'awareness', {q(note_for(names.get(teller, 'Someone'), tl))});", fetch=False)
        done += 1
    return done


def reproject():
    """Rebuild the bios and tell the running world. True when both worked."""
    try:
        done = subprocess.run(PROJECT_CMD, capture_output=True, text=True, timeout=900)
        if done.returncode != 0:
            log("project failed: " + (done.stderr.strip().splitlines() or ["no output"])[-1][:200])
            return False
    except (OSError, subprocess.TimeoutExpired) as e:
        log(f"project failed: {type(e).__name__}")
        return False
    script = os.environ.get("LORE_GATE_RELOAD", os.path.join(REPO, "ops", "scripts", "ra.sh"))
    if not os.path.exists(script):
        return False
    try:
        done = subprocess.run([script, "ollama reload"], capture_output=True, text=True, timeout=90)
        return done.returncode == 0 and bool(done.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        return False   # a console that will not answer is retried next cycle, not an error


def cycle(interval, dry_run):
    if not premise.is_isekai():
        return log("PREMISE is not isekai; nothing to do")
    enabled, first, second = settings()
    if not enabled:
        return log("AWARENESS_ENABLED is not 1; nothing to do")
    if os.path.exists(PAUSE_FILE):
        return log("PAUSE file present; nothing to do")
    if dry_run:
        # Tables are created only for a real run; a dry run must not write, so it needs them to exist.
        if not sql("SELECT 1 FROM information_schema.tables WHERE table_schema = DATABASE() "
                   "AND table_name = 'awareness_cursor'"):
            return log("dry run: awareness tables do not exist yet; run once without --dry-run")
    elif not ensure_schema():
        return log("lore_character does not exist yet; nothing to do")

    pairs, moves = seen_pairs(interval)
    levels, names = levels_for({g for p in pairs for g in p})
    changes = decide(pairs, levels, random.Random(time.time_ns()), first, second)
    for learner, teller, tl, why in changes:
        log(f"{'would: ' if dry_run else ''}{names.get(learner, learner)} learns from "
            f"{names.get(teller, teller)} (level {tl}), {why}")
    if dry_run:
        return log(f"dry run: {len(pairs)} pairs seen, {len(changes)} would learn; nothing written")

    learned = apply(changes, names)
    if moves:
        sql(moves, fetch=False)
    today = dt.datetime.now(dt.timezone.utc).date().toordinal()
    if learned:
        sql(cursor_sql("project", 0), fetch=False)   # owed until it succeeds, so a failure is retried
    stale = cursor("project") != today
    projected = False
    if learned or stale:
        projected = reproject()
        if projected:
            sql(cursor_sql("project", today), fetch=False)
    log(f"{len(pairs)} pairs seen, {learned} learned, {'reprojected' if projected else 'not reprojected'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=int, default=600)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="print what would change; write nothing")
    args = ap.parse_args()
    while True:
        t0 = time.time()
        try:
            cycle(args.interval, args.dry_run)
        except Exception as e:  # the database went away: log it and try again next cycle
            log(f"cycle failed: {type(e).__name__}: {e}")
            if args.once:
                return 1
        if args.once or args.dry_run:
            return 0
        time.sleep(max(10, args.interval - (time.time() - t0)))


if __name__ == "__main__":
    sys.exit(main())
