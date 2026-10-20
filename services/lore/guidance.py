#!/usr/bin/env python3
"""Guidance: the operator follows one person closely and sends them a system message (isekai premise).

Under PREMISE=isekai everyone is an arrival who can feel the game's system. This lets the operator reach one of
them through it: a window only they can see, from no named sender, the way Sword Art Online's system speaks.
What the operator writes is intent, not the window's text. A model turns it into the window's words, into how
this person takes it (true to who they are), and into what changes:

  goal   what drives them now (lore_character.motivation*, so "What drives you" in every prompt)
  know   something they now know or suspect (a line in their story)
  feel   warmer or colder toward someone (regard, plus an aside the chat module adds to that person's line)
  free   whichever of those the guidance calls for

Every message is a draft first: STORES NOTHING until the operator reads it and sends it. Sending writes the
window and their reaction into lore_character_note (source 'guidance'), which `gen_backstories.py project`
puts in the bio after the story, then rebuilds the bios and reloads them on the GM console. Every sent message
can be taken back; `guidance.plan` keeps what it replaced.

The page that drives this is the dashboard's People panel, through the lore gate (lore_gate.py: GET /people,
GET /person, POST /guide-draft, /guide-send, /guide-takeback).

Kill switch: GUIDANCE_ENABLED unset or 0 in site/site.env (reading people stays on), or the gate's PAUSE file.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import gen_backstories as g  # noqa: E402  (database, era patterns, json extraction)

premise = g.premise
TABLES_SQL = os.path.join(HERE, "guidance_tables.sql")

KINDS = ("goal", "know", "feel", "free")
NOTE_MAX = 255                 # lore_character_note.note
NOTICE_MAX = 200               # leaves room for the words around it in the note
MAX_CHANGE = 25                # the most one message moves a feeling, of -100..100
ATTEMPTS = 3
CHAT_LINES = 40


def enabled():
    return premise.is_isekai() and str(g.site.get("GUIDANCE_ENABLED", "0")).strip().lower() in ("1", "true", "yes", "on")


def ensure_schema():
    with open(TABLES_SQL) as f:
        g.sql(f.read(), fetch=False)


def _json(query, default):
    rows = g.sql(query)
    if not rows or not rows[0] or rows[0][0] in ("", "NULL"):
        return default
    return json.loads(rows[0][0])


def _str(expr):
    return f"JSON_UNQUOTE(JSON_EXTRACT(l.origin, '$.{expr}'))"


# ---------------------------------------------------------------------------
# reading: everyone, and one person closely

def people():
    """Everyone with a story, light: who they are here and back home, and the last thing they said."""
    has_guidance = bool(g.sql("SELECT 1 FROM information_schema.tables WHERE table_schema = DATABASE() "
                              "AND table_name = 'guidance'"))
    guided = ("(SELECT COUNT(*) FROM guidance gd WHERE gd.guid = c.guid AND gd.state = 'sent')"
              if has_guidance else "0")
    rows = _json(
        "SELECT JSON_ARRAYAGG(JSON_OBJECT("
        "'guid', c.guid, 'name', c.name, 'level', c.level, 'race', c.race, 'class', c.class, 'gender', c.gender, "
        "'online', c.online, 'earth', " + _str("earth_name") + ", 'age', " + _str("age") + ", "
        "'job', " + _str("job") + ", 'home', " + _str("home") + ", 'knows', l.knows_game, "
        "'goal', l.motivation_short, 'guild', gu.name, 'guided', " + guided + ", "
        "'said', (SELECT lc.text FROM ledger_chat lc WHERE lc.speaker_guid = c.guid ORDER BY lc.id DESC LIMIT 1), "
        "'said_at', (SELECT UNIX_TIMESTAMP(MAX(lc.ts)) FROM ledger_chat lc WHERE lc.speaker_guid = c.guid))) "
        "FROM lore_character l JOIN characters c ON c.guid = l.guid "
        "LEFT JOIN guild_member m ON m.guid = c.guid LEFT JOIN guild gu ON gu.guildid = m.guildid",
        [])
    rows.sort(key=lambda p: p["name"])
    return rows


def person(guid):
    """Everything about one person the page shows, or None."""
    guid = int(guid)
    base = _json(
        "SELECT JSON_OBJECT('guid', c.guid, 'name', c.name, 'level', c.level, 'race', c.race, 'class', c.class, "
        "'gender', c.gender, 'online', c.online, 'origin', l.origin, 'knows', l.knows_game, 'told_by', kf.name, "
        "'personality', l.personality, 'gist', l.gist, 'backstory', l.backstory, 'goal', l.motivation_short, "
        "'goal_long', l.motivation, 'goal_kind', l.motivation_kind, 'goal_target', l.motivation_target, "
        "'kin', l.kin, 'craft', l.craft, 'guild', gu.name, 'written_by', l.model) "
        "FROM lore_character l JOIN characters c ON c.guid = l.guid "
        "LEFT JOIN characters kf ON kf.guid = l.knows_game_from "
        "LEFT JOIN guild_member m ON m.guid = c.guid LEFT JOIN guild gu ON gu.guildid = m.guildid "
        f"WHERE l.guid = {guid}", None)
    if not base:
        return None
    base["days"] = premise.days_here()
    base["notes"] = _json(
        "SELECT JSON_ARRAYAGG(JSON_OBJECT('id', id, 'source', source, 'note', note, "
        f"'at', UNIX_TIMESTAMP(created_at))) FROM lore_character_note WHERE guid = {guid}", [])
    base["chat"] = _json(
        "SELECT JSON_ARRAYAGG(JSON_OBJECT('id', id, 'at', UNIX_TIMESTAMP(ts), 'who', speaker_name, "
        "'from', speaker_guid, 'to', listener_guid, 'channel', channel, 'type', chat_type, 'text', text)) "
        f"FROM (SELECT * FROM ledger_chat WHERE speaker_guid = {guid} OR listener_guid = {guid} "
        f"ORDER BY id DESC LIMIT {CHAT_LINES}) t", [])
    base["feels"] = _json(
        "SELECT JSON_ARRAYAGG(JSON_OBJECT('guid', r.other_guid, 'name', c.name, 'score', ROUND(r.score), "
        "'moments', r.familiarity, 'words', r.description, 'aside', a.words)) "
        "FROM (SELECT * FROM regard WHERE bot_guid = " + str(guid) + " ORDER BY ABS(score) DESC LIMIT 12) r "
        "JOIN characters c ON c.guid = r.other_guid "
        "LEFT JOIN regard_aside a ON a.bot_guid = r.bot_guid AND a.other_guid = r.other_guid", [])
    base["felt_by"] = _json(
        "SELECT JSON_ARRAYAGG(JSON_OBJECT('guid', r.bot_guid, 'name', c.name, 'score', ROUND(r.score), "
        "'words', r.description)) FROM (SELECT * FROM regard WHERE other_guid = " + str(guid) +
        " ORDER BY ABS(score) DESC LIMIT 8) r JOIN characters c ON c.guid = r.bot_guid", [])
    base["memories"] = _json(
        "SELECT JSON_ARRAYAGG(JSON_OBJECT('text', memory_text, 'importance', importance, "
        "'at', UNIX_TIMESTAMP(created_at))) FROM (SELECT * FROM mod_ollama_chat_memories "
        f"WHERE bot_guid = {guid} ORDER BY created_at DESC LIMIT 20) t", [])
    base["word"] = _json(
        "SELECT JSON_ARRAYAGG(JSON_OBJECT('at', UNIX_TIMESTAMP(a.at), 'learner', l.name, 'teller', t.name, "
        "'evidence', a.evidence)) FROM awareness_event a JOIN characters l ON l.guid = a.learner_guid "
        f"LEFT JOIN characters t ON t.guid = a.teller_guid WHERE a.learner_guid = {guid} OR a.teller_guid = {guid}",
        [])
    base["guidance"] = history(guid)
    for key in ("chat", "memories"):
        base[key].sort(key=lambda r: r.get("at") or 0, reverse=True)
    base["feels"].sort(key=lambda r: -abs(r["score"]))
    return base


def history(guid):
    if not g.sql("SELECT 1 FROM information_schema.tables WHERE table_schema = DATABASE() "
                 "AND table_name = 'guidance'"):
        return []
    rows = _json(
        "SELECT JSON_ARRAYAGG(JSON_OBJECT('id', id, 'at', UNIX_TIMESTAMP(at), 'kind', kind, 'asked', asked, "
        "'notice', notice, 'plan', plan, 'state', state, 'taken_back_at', UNIX_TIMESTAMP(taken_back_at))) "
        f"FROM guidance WHERE guid = {int(guid)}", [])
    rows.sort(key=lambda r: -r["id"])
    return rows


# ---------------------------------------------------------------------------
# writing a message: a draft, which stores nothing

PROMPT = """{setting}

You write a SYSTEM MESSAGE for one of these people: a window that opens in the air before them, the way the system speaks in Sword Art Online. Only they can see it. It has no named sender. {before}

The person:
{sheet}
{personality} {gist}
What drives them now: {goal}
{knows}
They are a level {level} {race} {cls}{guild}. {days}
People they feel strongly about: {ties}

The operator's guidance, which is what the window must achieve ({kind_rule}):
\"\"\"{text}\"\"\"

Reply with ONLY a JSON object with these keys:
- "notice": the window's words. Terse and impersonal like a game's system text: one or two short sentences, at most 30 words. It carries exactly what the guidance wants and nothing it did not ask for. It may set a quest, name a place or a person, or give a hint. Name only places that really are where you say they are in this world, or keep the place vague. Never quote the operator, and never explain who sent it. Don't open the way the earlier windows opened.{game_rule}
- "reaction": one or two sentences in the second person ("you"), at most 45 words: how THIS person took it, true to who they are and how they are coping. Plain modern English.
- "goal": null, or an object: "short" (one sentence, second person, at most 30 words: what drives you now), "long" (two or three sentences, second person), "target" (the short name of who or what it is aimed at), "target_type" (one of person, place, cause, foe, faction), "kind" (one of {kinds}).
- "know": null, or one sentence in the second person, at most 35 words: what you now know or suspect because of the window.
- "feel": a list, empty unless the guidance is about how they feel toward someone. Each entry: "name" (exactly one of: {names}), "change" (a whole number from -{max} for much colder to {max} for much warmer), "aside" (second person, at most 20 words: what you now think about them, because of the window).
Everything after "notice" must agree with it: the person can only react to, know, or want what the window actually said.
No markdown."""

KIND_RULES = {
    "goal": "it changes what drives them, so \"goal\" must be filled; leave \"know\" null and \"feel\" empty "
            "unless the guidance plainly needs them",
    "know": "it tells them something, so \"know\" must be filled; leave \"goal\" null",
    "feel": "it changes how they feel about someone, so \"feel\" must have at least one entry; leave \"goal\" null",
    "free": "fill whichever of \"goal\", \"know\" and \"feel\" the guidance calls for, at least one of them",
}


def _limit(text, words, what):
    text = " ".join(str(text or "").split())
    if not text:
        raise ValueError(f"no {what}")
    if len(text.split()) > words + 8:
        raise ValueError(f"{what} runs to {len(text.split())} words")
    return text


def _cast():
    """Every name a feeling can be about: the people with stories, and every character on a player's account."""
    kinds = g.sql("SELECT 1 FROM information_schema.tables WHERE table_schema = DATABASE() "
                  "AND table_name = 'person_kind'")
    players = " OR c.guid NOT IN (SELECT guid FROM person_kind WHERE kind = 'bot')" if kinds else ""
    rows = g.sql("SELECT c.guid, c.name FROM characters c WHERE c.guid IN (SELECT guid FROM lore_character)" + players)
    return {name.lower(): (int(guid), name) for guid, name in rows}


def _kinds():
    return list(g.ISEKAI_KINDS) + [k for k in g.eras.MOTIVATION_KINDS if k not in g.ISEKAI_KINDS]


def check(data, kind, p, cast, e):
    """The model's draft, validated and cleaned. Raises ValueError with the reason."""
    knows = int(p.get("knows") or 0)
    bad = g.meta_for(e, knows)
    out = {"notice": _limit(data.get("notice"), 30, "notice"),
           "reaction": _limit(data.get("reaction"), 45, "reaction"), "goal": None, "know": None, "feel": []}
    if len(out["notice"]) > NOTICE_MAX:
        raise ValueError("notice too long")
    goal = data.get("goal")
    if isinstance(goal, dict) and goal.get("short"):
        target = " ".join(str(goal.get("target") or "").split())[:80]
        ttype = goal.get("target_type") if goal.get("target_type") in ("person", "place", "cause", "foe", "faction") \
            else "cause"
        out["goal"] = {"short": _limit(goal["short"], 30, "goal")[:NOTE_MAX],
                       "long": _limit(goal.get("long") or goal["short"], 80, "goal's longer telling"),
                       "target": target or None, "target_type": ttype,
                       "kind": goal.get("kind") if goal.get("kind") in _kinds() else p.get("goal_kind")}
    if data.get("know"):
        out["know"] = _limit(data["know"], 35, "what they now know")
    for f in data.get("feel") or []:
        if not isinstance(f, dict):
            continue
        who = cast.get(str(f.get("name", "")).strip().lower())
        if not who or who[0] == p["guid"]:
            raise ValueError(f"nobody here is called {f.get('name')!r}")
        try:
            change = max(-MAX_CHANGE, min(MAX_CHANGE, round(float(f.get("change", 0)))))
        except (TypeError, ValueError):
            raise ValueError("a feeling's change is not a number") from None
        if change == 0:
            continue
        out["feel"].append({"guid": who[0], "name": who[1], "change": change,
                            "aside": _limit(f.get("aside"), 20, "aside")[:NOTE_MAX]})
    # A message changes only what it was asked to: what they know may come with a new goal, nothing else does.
    if kind == "know":
        out["goal"], out["feel"] = None, []
    if kind == "feel":
        out["goal"], out["know"] = None, None
    if kind == "goal":
        out["feel"] = []
    if "..." in out["notice"] or "\u2026" in out["notice"]:
        raise ValueError("the notice trails off or corrects itself")
    if kind == "goal" and not out["goal"]:
        raise ValueError("the guidance was about their goal and none was written")
    if kind == "know" and not out["know"]:
        raise ValueError("the guidance was something to know and nothing was written")
    if kind == "feel" and not out["feel"]:
        raise ValueError("the guidance was about a feeling and none was written")
    if kind == "free" and not (out["goal"] or out["know"] or out["feel"]):
        raise ValueError("the window changes nothing")
    for text in [out["notice"], out["reaction"], out["know"] or ""] + \
            ([out["goal"]["short"], out["goal"]["long"]] if out["goal"] else []) + [f["aside"] for f in out["feel"]]:
        hit = bad.search(text)
        if hit:
            raise ValueError(f"out-of-world word: {hit.group(0)!r}")
    return out


def draft(guid, kind, text, lane, era_name):
    """A message for one person, written and checked. Stores nothing. Returns (draft, None) or (None, why)."""
    if kind not in KINDS:
        return None, "Say what kind of guidance it is."
    p = person(guid)
    if not p:
        return None, "Nobody with a story has that guid."
    e = g.get_era(era_name)
    origin = json.loads(p["origin"]) if isinstance(p.get("origin"), str) else (p.get("origin") or {})
    cast = _cast()
    before = [r["notice"] for r in p["guidance"] if r["state"] == "sent"][:4]
    ties = "; ".join(f"{t['name']} ({'warm' if t['score'] > 0 else 'cold'}{': ' + t['words'] if t.get('words') else ''})"
                     for t in p["feels"][:6] if abs(t["score"]) >= 10) or "nobody yet"
    knows = int(p.get("knows") or 0)
    prompt = PROMPT.format(
        setting=premise.setting(e),
        before=("Nobody has ever seen a window like it: it is the first sign that someone, or something, is "
                "watching." if not before else
                "They have had windows like this before: " + " / ".join(f'"{n}"' for n in before)),
        sheet=origin.get("sheet") or "", personality=p.get("personality") or "", gist=p.get("gist") or "",
        goal=p.get("goal") or "getting through the day",
        knows=premise.knowledge_line(knows, p.get("told_by")),
        level=p["level"], race=g.RACES.get(int(p["race"]), "person"), cls=g.CLASSES.get(int(p["class"]), ""),
        guild=f", in the band {p['guild']}" if p.get("guild") else "", days=premise.days_line(), ties=ties,
        kind_rule=KIND_RULES[kind], text=text.strip()[:1500], kinds=", ".join(_kinds()),
        names=", ".join(n for _, n in sorted(cast.values(), key=lambda v: v[1]) if n != p["name"]),
        max=MAX_CHANGE,
        game_rule=("" if knows >= 1 or "warcraft" in text.lower() else
                   " Never name World of Warcraft or any game: this person does not know where they are."))
    why = "no reply"
    for attempt in range(1, ATTEMPTS + 1):
        try:
            data = g.extract_json(lane.chat([{"role": "user", "content": prompt}], 900, temperature=0.8, context={
                "purpose": "guidance_draft", "source": "lore/guidance.py", "stage": "draft", "route": "batch",
                "guid": p["guid"], "attempt": attempt}))
            out = check(data, kind, p, cast, e)
            out.update(guid=p["guid"], name=p["name"], kind=kind, asked=text.strip())
            return out, None
        except (ValueError, RuntimeError, KeyError, TypeError) as err:
            why = str(err)
    return None, f"Three tries and no message passed the checks; the last said: {why}."


# ---------------------------------------------------------------------------
# sending, and taking back

def _notes(d):
    """The lines that go into their story, each short enough for one lore_character_note."""
    lines = [f'A system window opened before you, from no sender, and said: "{d["notice"]}"', d["reaction"]]
    if d["know"]:
        lines.append(d["know"])
    return [l[:NOTE_MAX] for l in lines]


def send(d):
    """Apply a checked draft. Returns the guidance id. The caller rebuilds the bios afterwards."""
    ensure_schema()
    guid, q = int(d["guid"]), g.q
    plan = {"notes": [], "goal": None, "feel": []}
    stmts = ["START TRANSACTION;"]
    for line in _notes(d):
        stmts.append(f"INSERT INTO lore_character_note (guid, source, note) VALUES ({guid}, 'guidance', {q(line)});"
                     "SELECT LAST_INSERT_ID();")
    if d["goal"]:
        old = _json("SELECT JSON_OBJECT('short', motivation_short, 'long', motivation, 'kind', motivation_kind, "
                    f"'target', motivation_target) FROM lore_character WHERE guid = {guid}", {})
        target = json.dumps({"name": d["goal"]["target"], "type": d["goal"]["target_type"]}) \
            if d["goal"]["target"] else None
        stmts.append(f"UPDATE lore_character SET motivation_short = {q(d['goal']['short'])}, "
                     f"motivation = {q(d['goal']['long'])}, motivation_kind = {q(d['goal']['kind'] or '')}, "
                     f"motivation_target = {q(target) if target else 'NULL'} WHERE guid = {guid};")
        plan["goal"] = {"set": d["goal"], "was": old}
    for f in d["feel"]:
        o, ch = int(f["guid"]), int(f["change"])
        reason = q(("a system window: " + f["aside"])[:160])
        stmts.append(
            "INSERT INTO regard (bot_guid, other_guid, score, baseline, familiarity, last_reason, last_delta) "
            f"VALUES ({guid}, {o}, {ch}, 0, 0, {reason}, {ch}) ON DUPLICATE KEY UPDATE "
            f"score = LEAST(100, GREATEST(-100, score + {ch})), last_reason = VALUES(last_reason), "
            "last_delta = VALUES(last_delta), updated_at = NOW();"
            "INSERT INTO regard_log (bot_guid, other_guid, delta, score, source, reason) "
            f"SELECT {guid}, {o}, {ch}, score, 'guidance', {reason} FROM regard "
            f"WHERE bot_guid = {guid} AND other_guid = {o};"
            # An aside another step owns (a sponsor's candidacy) is left alone; one of ours is replaced.
            f"INSERT INTO regard_aside (bot_guid, other_guid, source, words) VALUES ({guid}, {o}, 'guidance', "
            f"{q(f['aside'])}) ON DUPLICATE KEY UPDATE words = IF(source = 'guidance', VALUES(words), words), "
            "updated_at = IF(source = 'guidance', NOW(), updated_at);")
        plan["feel"].append({"guid": o, "name": f["name"], "change": ch, "aside": f["aside"]})
    stmts.append("COMMIT;")
    ids = [int(r[0]) for r in g.sql("\n".join(stmts)) if r and r[0].isdigit()]
    plan["notes"] = ids
    plan["reaction"], plan["know"] = d["reaction"], d["know"]
    g.sql("INSERT INTO guidance (guid, kind, asked, notice, plan) VALUES "
          f"({guid}, {q(d['kind'])}, {q(d['asked'])}, {q(d['notice'])}, {q(json.dumps(plan))});", fetch=False)
    return int(g.sql(f"SELECT MAX(id) FROM guidance WHERE guid = {guid}")[0][0])


def take_back(gid):
    """Undo one sent message as far as it still can be. Returns (guid, what was left alone) or None."""
    rows = g.sql(f"SELECT guid, state, plan FROM guidance WHERE id = {int(gid)}")
    if not rows or rows[0][1] != "sent":
        return None
    guid, plan, q = int(rows[0][0]), json.loads(rows[0][2]), g.q
    left = []
    stmts = ["START TRANSACTION;"]
    if plan["notes"]:
        stmts.append(f"DELETE FROM lore_character_note WHERE source = 'guidance' AND guid = {guid} "
                     f"AND id IN ({','.join(str(int(i)) for i in plan['notes'])});")
    goal = plan.get("goal")
    if goal:
        now = g.sql(f"SELECT motivation_short FROM lore_character WHERE guid = {guid}")
        if now and g.q(now[0][0]) == g.q(goal["set"]["short"]):
            was = goal["was"]
            target = was.get("target")
            stmts.append(f"UPDATE lore_character SET motivation_short = {q(was.get('short') or '')}, "
                         f"motivation = {q(was.get('long') or '')}, motivation_kind = {q(was.get('kind') or '')}, "
                         f"motivation_target = {q(json.dumps(target)) if target else 'NULL'} WHERE guid = {guid};")
        else:
            left.append("their goal has changed again since, so it was left as it is")
    for f in plan.get("feel", []):
        o, ch = int(f["guid"]), -int(f["change"])
        stmts.append(f"UPDATE regard SET score = LEAST(100, GREATEST(-100, score + {ch})), updated_at = NOW() "
                     f"WHERE bot_guid = {guid} AND other_guid = {o};"
                     "INSERT INTO regard_log (bot_guid, other_guid, delta, score, source, reason) "
                     f"SELECT {guid}, {o}, {ch}, score, 'guidance', 'a system window taken back' FROM regard "
                     f"WHERE bot_guid = {guid} AND other_guid = {o};"
                     f"DELETE FROM regard_aside WHERE bot_guid = {guid} AND other_guid = {o} AND source = 'guidance' "
                     f"AND words = {q(f['aside'])};")
    stmts.append(f"UPDATE guidance SET state = 'taken back', taken_back_at = NOW() WHERE id = {int(gid)};")
    stmts.append("COMMIT;")
    g.sql("\n".join(stmts), fetch=False)
    return guid, left
