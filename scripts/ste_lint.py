#!/usr/bin/env python
# The project's prose check (CONTRIBUTING.md, section 6). Copied from the repository owner's own
# tool, ste_lint 1.0.0. Run: python scripts/ste_lint.py --mode descriptive FILE.md
"""ste_lint - a deterministic prose check for ASD-STE100 structure and LLM slop.

Standard library only. No network. No model calls.

Two rule families, kept separate on purpose:

  ste.*   structural rules from ASD-STE100 that need no dictionary: sentence
          length, one instruction per sentence, paragraph length, noun
          clusters, voice, tense, ambiguous reference, Latin, punctuation.
  slop.*  register rules that are NOT in ASD-STE100: filler, empty
          intensifiers, LLM vocabulary, hedge stacks, bureaucratic phrases.

The approved ASD-STE100 dictionary of about 900 words is the property of ASD
and is not reproduced here. Conformance to that dictionary is therefore not
checked. The slop list carries the lexical load instead.

Exit codes: 0 no errors, 1 errors above the baseline, 2 the run itself failed.
"""

import argparse
import json
import os
import re
import sys

VERSION = "1.0.0"

CAPS = {"procedural": 20, "descriptive": 25, "chat": 25}

# ---------------------------------------------------------------- lexicons

# phrase -> what to write instead. Matched without case on word boundaries.
SLOP = {
    # filler openers
    "it's worth noting that": "delete it, or state the fact",
    "it is worth noting that": "delete it, or state the fact",
    "it is important to note that": "delete it, or state the fact",
    "it's important to note that": "delete it, or state the fact",
    "it should be noted that": "delete it, or state the fact",
    "keep in mind that": "delete it, or state the fact",
    "bear in mind that": "delete it, or state the fact",
    "needless to say": "delete it",
    "as we all know": "delete it",
    "at the end of the day": "delete it",
    "when it comes to": "for, or about",
    "that being said": "but",
    "with that said": "but",
    "it goes without saying": "delete it",
    "last but not least": "finally",
    "first and foremost": "first",
    # bureaucracy
    "in order to": "to",
    "so as to": "to",
    "for the purpose of": "to",
    "due to the fact that": "because",
    "owing to the fact that": "because",
    "in spite of the fact that": "although",
    "despite the fact that": "although",
    "in the event that": "if",
    "in the event of": "if",
    "prior to": "before",
    "subsequent to": "after",
    "at this point in time": "now",
    "at the present time": "now",
    "has the ability to": "can",
    "have the ability to": "can",
    "is able to": "can",
    "are able to": "can",
    "a number of": "some, or the count",
    "a variety of": "some, or name them",
    "the majority of": "most",
    "in the process of": "delete it",
    "with regard to": "about",
    "with respect to": "about",
    "in relation to": "about",
    "in terms of": "delete it, or name the measure",
    "on a regular basis": "regularly",
    "in close proximity to": "near",
    "a large number of": "many",
    "take into consideration": "consider",
    "make a decision": "decide",
    "provide assistance": "help",
    # LLM register
    "delve into": "examine",
    "delve": "examine",
    "leverage": "use",
    "leveraging": "using",
    "utilize": "use",
    "utilise": "use",
    "utilizing": "using",
    "utilization": "use",
    "robust": "name the property: reliable, tested, fault tolerant",
    "seamless": "delete it, or say what it removes",
    "seamlessly": "delete it",
    "effortless": "delete it",
    "effortlessly": "delete it",
    "elevate": "improve",
    "unlock": "enable, or allow",
    # "harness" alone fires on "test harness", a normal technical noun.
    # Narrowed 2026-10-17 to the marketing verb sense only.
    "harness the": "use",
    "empower": "let, or allow",
    "streamline": "simplify, or shorten",
    "cutting-edge": "delete it",
    "state-of-the-art": "delete it",
    "game-changer": "delete it",
    "game changing": "delete it",
    "best-in-class": "delete it",
    "world-class": "delete it",
    "comprehensive": "complete, or state the scope",
    "holistic": "delete it",
    "myriad": "many",
    "plethora": "many",
    "tapestry": "delete it",
    "realm": "area, or field",
    "foster": "cause, or support",
    "underscore": "show",
    "underscores": "shows",
    "showcase": "show",
    "showcases": "show",
    "pivotal": "important, or state the effect",
    "paramount": "most important",
    "meticulous": "careful",
    "meticulously": "carefully",
    "intricate": "complex, or detailed",
    "nuanced": "state the distinction",
    "a testament to": "shows",
    "deep dive": "detailed review",
    "supercharge": "speed up",
    "turbocharge": "speed up",
    "rich set of": "delete it, or count them",
    "powerful": "state the capability",
    "exciting": "delete it",
    "revolutionary": "delete it",
    "transformative": "delete it",
    # empty intensifiers
    "very": "delete it, or give the number",
    "really": "delete it",
    "extremely": "delete it, or give the number",
    "incredibly": "delete it",
    "remarkably": "delete it",
    "exceptionally": "delete it",
    "highly": "delete it",
    "truly": "delete it",
    "absolutely": "delete it",
    "literally": "delete it",
    "basically": "delete it",
    "essentially": "delete it",
    "fundamentally": "delete it",
    "quite": "delete it",
    "fairly": "delete it",
    "somewhat": "delete it, or give the range",
    "arguably": "delete it, or state who argues it",
    # transition slop
    "moreover": "also, or delete it",
    "furthermore": "also, or delete it",
    "additionally": "also, or delete it",
    "in conclusion": "delete it",
    "to summarize": "delete it",
    "to sum up": "delete it",
    "firstly": "first",
    "secondly": "second",
    "thirdly": "third",
    # vague action verbs
    "deal with": "name the action",
    "take care of": "name the action",
    "come up with": "write, design, or choose",
    "figure out": "determine, or find",
    "go ahead and": "delete it",
    "reach out": "contact, or ask",
    "look into": "examine",
    "sort out": "fix, or arrange",
    "touch base": "contact",
    # "make sure" is NOT listed here on purpose. The approved ASD-STE100
    # dictionary uses MAKE SURE as the approved form, and does not approve
    # "ensure", "verify", "check" (as a verb) or "confirm". Flagging it and
    # suggesting those words pushed writing away from the standard.
    # hedge stacks. A single hedge is kept, because STE keeps modality.
    "may potentially": "may",
    "could potentially": "could",
    "might possibly": "might",
    "may possibly": "may",
    "could possibly": "could",
    "it seems likely that": "probably",
    "generally speaking": "delete it",
    "more or less": "delete it, or give the range",
    "kind of": "delete it",
    "sort of": "delete it",
}

# Rhetorical frames. These are errors because they delay the fact.
SLOP_SHAPE = {
    "not only": "state both facts in two sentences",
    "isn't just": "state what it is",
    "is not just": "state what it is",
    "think of it as": "state what it is",
    "the key is": "state the fact",
    "the beauty of": "delete it",
    "here's the thing": "delete it",
    "let's dive in": "delete it",
}

LATIN = {
    "e.g.": "for example",
    "i.e.": "that is",
    "etc.": "end the list, or write 'and others'",
    "vs.": "or, against",
    "n.b.": "note",
    "cf.": "compare",
}

BE = r"(?:am|is|are|was|were|be|been|being)"

IRREG = (
    "done|made|seen|taken|given|written|shown|known|found|held|kept|left|sent|"
    "put|built|broken|chosen|driven|drawn|eaten|fallen|forgotten|gotten|"
    "hidden|lost|meant|met|paid|said|sold|spent|stood|told|thought|"
    "understood|won|brought|bought|caught|dealt|felt|fed|flown|frozen|grown|"
    "heard|laid|led|lent|lit|proven|risen|sought|shot|slept|spoken|spun|"
    "stolen|struck|swept|sworn|torn|woken|worn|woven"
)

# A bare noun that ends in -tion or -ment is usually the correct technical
# word ('configuration', 'requirement'), so the word shape alone proves
# nothing. Only the light-verb construction is always wrong, because the verb
# is already present and hidden: 'perform a validation' -> 'validate'.
LIGHT_VERB = re.compile(
    r"\b(perform|performs|performed|do|does|did|make|makes|made|provide|"
    r"provides|provided|carry out|carries out|carried out|give|gives|gave|"
    r"conduct|conducts|conducted|undertake|undertakes|effect|effects|"
    r"achieve|achieves|achieved|run|runs|ran)\s+"
    r"(?:a|an|the|some|any)?\s*"
    r"(\w{4,}(?:tion|tions|ment|ments|ance|ances|ence|ences|sis|ysis))\b",
    re.I,
)

# Words that end in -ed but act as adjectives, so 'is <word>' is not passive.
ED_ADJECTIVES = set("""
unfinished finished interested excited tired complicated dedicated limited
detailed advanced sophisticated experienced concerned worried pleased
prepared qualified related aged mixed fixed closed open locked unlocked
enabled disabled deprecated supported unsupported undefined unused
unexpected involved intended wicked sacred naked crowded gifted talented
skilled willing unwilling red
""".split())

IMPERATIVE = (
    "add|allow|apply|build|cancel|change|check|clean|clear|click|close|"
    "compare|configure|confirm|connect|copy|create|delete|deploy|disable|"
    "disconnect|download|edit|enable|ensure|enter|examine|execute|export|"
    "extract|fill|find|fix|flash|follow|format|import|include|insert|install|"
    "keep|launch|load|lock|mount|move|open|paste|press|print|pull|push|read|"
    "reboot|record|remove|rename|repeat|replace|report|reset|restart|restore|"
    "run|save|scan|select|send|set|show|start|stop|switch|test|type|unlock|"
    "unmount|update|upgrade|verify|wait|write"
)

DETERMINERS = set("the a an this that these those its your our their my".split())

FUNCTION_WORDS = set("""
a an the of in on at to for with by from as and or but if then than that this
these those is are was were be been being am do does did have has had will
would can could may might must shall should not no nor so very it its their
his her your our my you we they he she i me him them us there here when where
which who whom whose what how why all any both each few more most other some
such only own same too also now new one two three first next last each per
into over under after before while during about up down out off again
without within through between against across upon because since until
unless whether though although however instead rather onto beyond besides
despite among toward towards above below behind beside near past off per
via than once ever never always often sometimes just only even still yet
plus minus alongside including excluding regarding concerning per each
both either neither such more less many much most least own
""".split())

SYNONYMS = {
    "start": ["start", "begin", "commence", "initiate", "kick off", "launch"],
    "use": ["use", "utilize", "utilise", "leverage", "employ"],
    "show": ["show", "display", "present", "render", "surface"],
    "fix": ["fix", "repair", "remediate", "rectify"],
    "delete": ["delete", "remove", "erase", "purge", "eliminate"],
    "make": ["make", "create", "generate", "produce"],
    "check": ["check", "verify", "validate", "confirm", "inspect"],
    "change": ["change", "modify", "alter", "amend"],
    "get": ["get", "obtain", "acquire", "retrieve", "fetch"],
    "allow": ["allow", "permit", "enable"],
    "need": ["need", "require", "necessitate"],
    "stop": ["stop", "halt", "terminate", "cease", "abort"],
    "find": ["find", "locate", "discover"],
    "send": ["send", "transmit", "dispatch", "forward"],
    "problem": ["problem", "issue", "defect", "fault"],
}

# ---------------------------------------------------------------- masking


def _blank(m):
    """Replace a match with spaces, keeping newlines so offsets stay true."""
    return re.sub(r"[^\n]", " ", m.group(0))


def mask(text):
    """Blank everything that is not prose. Offsets and line numbers survive."""
    # Suppression markers, so a document can quote bad writing on purpose.
    #   <!-- ste-lint off -->  ...  <!-- ste-lint on -->   skips a region
    #   <!-- ste-lint ignore -->                           skips the next line
    text = re.sub(r"<!--\s*ste-lint\s+off\s*-->.*?"
                  r"(?:<!--\s*ste-lint\s+on\s*-->|\Z)", _blank, text,
                  flags=re.S | re.I)
    text = re.sub(r"<!--\s*ste-lint\s+ignore\s*-->[ \t]*\n[^\n]*", _blank,
                  text, flags=re.I)
    text = re.sub(r"\A---\n.*?\n---", _blank, text, flags=re.S)
    text = re.sub(r"^[ \t]*(```|~~~).*?^[ \t]*\1[ \t]*$", _blank, text,
                  flags=re.S | re.M)
    text = re.sub(r"^[ \t]*(```|~~~).*\Z", _blank, text, flags=re.S | re.M)
    text = re.sub(r"^(?: {4}|\t)\S.*$", _blank, text, flags=re.M)
    text = re.sub(r"<!--.*?-->", _blank, text, flags=re.S)
    text = re.sub(r"</?[A-Za-z][^>\n]*>", _blank, text)
    text = re.sub(r"^[ \t]*\|.*$", _blank, text, flags=re.M)
    text = re.sub(r"`[^`\n]*`", _blank, text)
    text = re.sub(r"\]\([^)\n]*\)", _blank, text)
    text = re.sub(r"\b(?:https?|file|ftp)://\S+", _blank, text)
    text = re.sub(r"^\[[^\]\n]+\]:[ \t]*\S+.*$", _blank, text, flags=re.M)
    text = re.sub(r"\b[A-Za-z]:[\\/][^\s,;)\]]+", _blank, text)
    text = re.sub(r"(?<![\w.])(?:~|\.{1,2})?/[\w.~-]+(?:/[\w.~-]+)+",
                  _blank, text)
    text = re.sub(r"\$\{?[A-Za-z_][A-Za-z0-9_]*\}?", _blank, text)
    text = re.sub(r"(?<![\w-])--?[A-Za-z][\w-]*", _blank, text)
    return text


# Trailing markdown emphasis counts as sentence-final punctuation, otherwise
# "...habits.** Next" never splits and the two sentences merge into one.
SENT_END = re.compile(r"(?<=[.!?])[\"')\]*_`]*(?:\s+|$)")
ABBREV = re.compile(
    r"(?:\b[A-Za-z]|\be\.g|\bi\.e|\betc|\bvs|\bMr|\bMrs|\bMs|\bDr|\bFig"
    r"|\bNo|\bapprox|\bcf|\bal)\.[\"')\]]*\s*$", re.I)
LIST_MARK = re.compile(r"^[ \t]*(?:[-*+]|\d+[.)])[ \t]+")
HEADING = re.compile(r"^[ \t]*#{1,6}[ \t]+")


def split_sentences(block):
    """Return [(offset, sentence)] for one prose block."""
    out, start = [], 0
    for m in SENT_END.finditer(block):
        head = block[start:m.start()]
        # A full stop after a digit DOES end a sentence: "...on page 5. The
        # controls..." is two sentences. A decimal or a version needs no
        # guard here, because "3.14" and "v1.2.3" have no space after the
        # dot, so SENT_END never matches inside them. A numbered list marker
        # is already removed by LIST_MARK in blocks_of.
        if ABBREV.search(head):
            continue
        if head.strip():
            out.append((start, head))
        start = m.end()
    tail = block[start:]
    if tail.strip():
        out.append((start, tail))
    return out


def blocks_of(masked):
    """Yield (offset, text) for every prose unit: paragraph, list item, heading.

    A list item is its own unit, so the paragraph rule does not punish lists
    and a long list does not hide a long sentence.
    """
    for pm in re.finditer(r"[^\n]+(?:\n[^\n]+)*", masked):
        para, base = pm.group(0), pm.start()
        cur, cur_off = [], None
        line_off = 0
        for line in para.split("\n"):
            is_item = bool(LIST_MARK.match(line) or HEADING.match(line))
            if is_item:
                if cur:
                    yield base + cur_off, "\n".join(cur)
                stripped = HEADING.sub("", LIST_MARK.sub("", line))
                pad = len(line) - len(stripped)
                cur, cur_off = [stripped], line_off + pad
            else:
                if cur_off is None:
                    cur_off = line_off
                cur.append(line)
            line_off += len(line) + 1
        if cur:
            yield base + (cur_off or 0), "\n".join(cur)


def words(s):
    return re.findall(r"[A-Za-z][A-Za-z'-]*", s)


# ---------------------------------------------------------------- findings


class Finding(object):
    def __init__(self, rule, sev, line, col, msg, fix=None, text=""):
        self.rule, self.sev, self.line, self.col = rule, sev, line, col
        self.msg, self.fix, self.text = msg, fix, text

    def as_dict(self):
        return {"rule": self.rule, "severity": self.sev, "line": self.line,
                "column": self.col, "message": self.msg,
                "suggestion": self.fix, "excerpt": self.text}


def _phrase_pattern(phrase):
    body = re.escape(phrase).replace(r"\ ", r"\s+")
    lead = r"\b" if phrase[0].isalnum() else r"(?<![\w.])"
    trail = r"\b" if phrase[-1].isalnum() else ""
    return lead + body + trail


def check(text, mode="descriptive", cap=None, disabled=()):
    cap = cap or CAPS.get(mode, 25)
    masked = mask(text)
    newlines = [m.start() for m in re.finditer(r"\n", masked)]

    def position(off):
        line = sum(1 for n in newlines if n < off) + 1
        bol = max([n for n in newlines if n < off], default=-1) + 1
        return line, off - bol + 1

    found = []
    seen = set()

    def add(rule, sev, off, msg, fix=None, excerpt=""):
        if rule in disabled or (rule, off) in seen:
            return
        seen.add((rule, off))
        line, col = position(off)
        found.append(Finding(rule, sev, line, col, msg, fix, excerpt))

    # --- document wide lexical sweeps
    for phrase, fix in SLOP.items():
        for m in re.finditer(_phrase_pattern(phrase), masked, re.I):
            add("slop.filler", "error", m.start(),
                "'%s' carries no information" % m.group(0).strip(), fix,
                m.group(0).strip())

    for phrase, fix in SLOP_SHAPE.items():
        for m in re.finditer(_phrase_pattern(phrase), masked, re.I):
            add("slop.shape", "error", m.start(),
                "'%s' is a rhetorical frame, not a fact" % m.group(0).strip(),
                fix, m.group(0).strip())

    for phrase, fix in LATIN.items():
        for m in re.finditer(_phrase_pattern(phrase), masked, re.I):
            add("ste.latin", "error" if mode == "procedural" else "warning",
                m.start(), "ASD-STE100 does not approve '%s'" % phrase, fix,
                phrase)

    if mode != "chat":
        for m in re.finditer(r";", masked):
            add("ste.semicolon", "error", m.start(),
                "ASD-STE100 does not allow the semicolon",
                "write two sentences", ";")

    for m in re.finditer(r"\.\.\.|…", masked):
        add("ste.ellipsis", "error", m.start(),
            "ASD-STE100 does not allow the ellipsis",
            "complete the sentence", m.group(0))

    dashes = len(re.findall(r"—|(?<=\s)--(?=\s)", masked))
    stops = max(1, len(re.findall(r"[.!?]", masked)))
    if dashes >= 3 and float(dashes) / stops > 0.25:
        add("slop.emdash", "warning", 0,
            "%d dashes in about %d sentences" % (dashes, stops),
            "use a full stop, a comma, or brackets")

    # --- per prose unit
    synonym_hits = {}
    for boff, block in blocks_of(masked):
        sentences = split_sentences(block)
        if len(sentences) > 6:
            add("ste.paragraph", "error", boff,
                "%d sentences in one paragraph, the limit is 6"
                % len(sentences), "split the paragraph")

        for soff, sentence in sentences:
            off = boff + soff
            wordlist = words(sentence)
            if len(wordlist) > cap:
                add("ste.sentence-length", "error", off,
                    "%d words, the %s limit is %d"
                    % (len(wordlist), mode, cap), "write two sentences",
                    " ".join(wordlist[:8]))

            verbs = re.findall(
                r"(?:^|[.!?]\s+|\band\s+then\s+|\band\s+|,\s*then\s+)(%s)\b"
                % IMPERATIVE, sentence, re.I)
            if len(verbs) > 1:
                m = re.search(r"\band(\s+then)?\b|,\s*then\b", sentence, re.I)
                if m:
                    add("ste.one-instruction", "error", off + m.start(),
                        "two or more instructions in one sentence",
                        "one instruction per sentence",
                        sentence.strip()[:70])

            for m in re.finditer(
                    r"\b%s\s+(?:not\s+|being\s+)?(\w+ed|%s)\b" % (BE, IRREG),
                    sentence, re.I):
                if m.group(1).lower() in ED_ADJECTIVES:
                    continue
                add("ste.passive", "warning", off + m.start(),
                    "passive voice: '%s'" % m.group(0).strip(),
                    "name the actor, use the active voice", m.group(0).strip())

            for m in re.finditer(
                    r"\b(?:have|has|had)\s+(?:not\s+)?(\w+ed|%s)\b" % IRREG,
                    sentence, re.I):
                add("ste.tense", "warning", off + m.start(),
                    "compound tense: '%s'" % m.group(0).strip(),
                    "use a simple tense, unless the compound carries meaning",
                    m.group(0).strip())

            m = re.match(
                r"\s*(This|That|These|Those|It)\s+(?:is|are|was|were|will|can|"
                r"could|may|might|should|must|does|do|did|means|gives|makes|"
                r"lets|has|have|had)\b", sentence)
            if m:
                add("ste.reference", "warning", off + m.start(1),
                    "'%s' starts the sentence with no named subject"
                    % m.group(1), "name the thing you refer to",
                    sentence.strip()[:60])

            # A noun cluster needs a determiner in front of a run of content
            # words. Without part-of-speech tagging, 4 content words cannot
            # be told apart from a short clause ('the shortest diff wins'),
            # so the threshold is 5. Shorter real clusters are left to the
            # reader, and the skill says so.
            # Keep the apostrophe inside the token, so "skill's" stays one
            # word instead of becoming "skill" plus a stray "s".
            toks = [(m.group(0), m.start())
                    for m in re.finditer(r"[A-Za-z][\w'’-]*", sentence)]
            i = 0
            while i < len(toks):
                if toks[i][0].lower() in DETERMINERS:
                    run = []
                    j = i + 1
                    while j < len(toks) and toks[j][0].lower() not in FUNCTION_WORDS:
                        run.append(toks[j])
                        j += 1
                    if len(run) >= 5:
                        add("ste.noun-cluster", "warning", off + run[0][1],
                            "noun cluster of %d words: '%s'"
                            % (len(run), " ".join(t for t, _p in run)),
                            "use 3 words at most, or add a preposition",
                            " ".join(t for t, _p in run))
                    i = j
                else:
                    i += 1

            for m in LIGHT_VERB.finditer(sentence):
                add("slop.nominalization", "warning", off + m.start(),
                    "'%s' hides a verb" % m.group(0).strip(),
                    "use the verb directly", m.group(0).strip())

            for group, variants in SYNONYMS.items():
                for v in variants:
                    if re.search(r"\b%s\b" % re.escape(v), sentence, re.I):
                        synonym_hits.setdefault(group, {}).setdefault(
                            v.lower(), off)

    for group, hits in synonym_hits.items():
        if len(hits) > 1:
            add("slop.synonym", "warning", min(hits.values()),
                "one idea, %d different words: %s"
                % (len(hits), ", ".join(sorted(hits))),
                "choose one word and keep it")

    found.sort(key=lambda f: (f.line, f.col, f.rule))
    return found


# ---------------------------------------------------------------- reporting


def report(path, found, baseline, as_json):
    errors = [f for f in found if f.sev == "error"]
    warnings = [f for f in found if f.sev == "warning"]
    if as_json:
        return errors, json.dumps(
            {"file": path, "version": VERSION, "errors": len(errors),
             "warnings": len(warnings),
             "findings": [f.as_dict() for f in found]}, indent=2)
    out = []
    for f in found:
        out.append("%s:%d:%d: %s %s: %s"
                   % (path, f.line, f.col, f.sev, f.rule, f.msg))
        if f.fix:
            out.append("    -> %s" % f.fix)
    verdict = "%d error(s), %d warning(s)" % (len(errors), len(warnings))
    if baseline:
        verdict += "  [baseline %d]" % baseline
    out.append(verdict)
    return errors, "\n".join(out)


SELFTEST = [
    ("The fan may have failed.", 0, "modality and compound tense survive"),
    ("Press the button.", 0, "a plain instruction passes"),
    ("We leverage a robust solution in order to seamlessly utilize the data.",
     5, "slop is caught"),
    ("Press the button and then open the cover.", 1, "two instructions"),
    ("The cover is removed by the technician.", 0, "passive warns, never fails"),
    ("Use `leverage` here.\n\n```\nutilize\n```\n", 0, "code is masked"),
    ("See https://example.com/in-order-to-utilize now.", 0, "urls are masked"),
    ("Open the file. Read it. Save it. Close it. Exit. Reboot. Verify.", 1,
     "seven sentences break the paragraph rule"),
    ("<!-- ste-lint off -->\nNever write robust or seamless.\n"
     "<!-- ste-lint on -->\n", 0, "an off region is skipped"),
    ("<!-- ste-lint ignore -->\nThis uses robust on purpose.\n", 0,
     "ignore skips the next line"),
    ("Scan the habits.** Synonym rotation, hedge stacking, light verbs.", 0,
     "markdown emphasis does not merge two sentences"),
    # Both reported by a peer session on 2026-10-15, then verified here
    # independently. The reporting address later denied sending the report,
    # so the credit is unresolved. The fixes rest on the verification.
    ("The LFO controls are on page 5. The controls change the depth and the "
     "rate of the modulation that the operator applies to the carrier.", 0,
     "a full stop after a digit ends the sentence"),
    ("Make sure that the valve can operate.", 0,
     "MAKE SURE is the approved ASD-STE100 form"),
]


# (text, rule id, must it fire, why). These pin the precision of the rules
# that have no part-of-speech tagging behind them.
WARNTEST = [
    ("Replace the main landing gear door actuator now.",
     "ste.noun-cluster", True, "a real noun pile is caught"),
    ("The shortest working diff wins here.",
     "ste.noun-cluster", False, "a short clause is not a noun pile"),
    ("Perform a validation of the request.",
     "slop.nominalization", True, "a light verb hides a verb"),
    ("Read the configuration requirement.",
     "slop.nominalization", False, "a bare -tion noun is the right word"),
    ("The build is unfinished.",
     "ste.passive", False, "an -ed adjective is not the passive voice"),
    ("The cover is removed by the technician.",
     "ste.passive", True, "a real passive is caught"),
    ("This is why the fan stopped.",
     "ste.reference", True, "a sentence must name its subject"),
    # "harness" alone flagged "test harness" and suggested "use", which is
    # wrong for the noun. Narrowed to the verb sense on 2026-10-17.
    ("A separate test harness runs the cases.",
     "slop.filler", False, "harness as a noun is the right word"),
    ("We harness the power of the data.",
     "slop.filler", True, "the marketing verb is still caught"),
]


def selftest():
    failures = 0
    for text, want, why in SELFTEST:
        errors = [f for f in check(text, "procedural") if f.sev == "error"]
        got = len(errors)
        ok = got == want
        if not ok:
            failures += 1
        print("%-4s %-52s want %d got %d"
              % ("pass" if ok else "FAIL", why, want, got))
        if not ok:
            for e in errors:
                print("         %s: %s" % (e.rule, e.msg))

    for text, rule, want, why in WARNTEST:
        fired = any(f.rule == rule for f in check(text, "procedural"))
        ok = fired == want
        if not ok:
            failures += 1
        print("%-4s %-52s %s %s"
              % ("pass" if ok else "FAIL", why,
                 "expect" if want else "expect no", rule))

    print("selftest: %s"
          % ("ok" if not failures else "%d case(s) failed" % failures))
    return 0 if not failures else 1


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="ste_lint",
        description="Check prose against ASD-STE100 structure and LLM slop.")
    p.add_argument("files", nargs="*", help="files to check, or - for stdin")
    p.add_argument("--mode", choices=sorted(CAPS), default="descriptive",
                   help="procedural (20 words), descriptive or chat (25)")
    p.add_argument("--max-sentence", type=int, default=None,
                   help="override the sentence word cap")
    p.add_argument("--baseline", type=int, default=0,
                   help="tolerate this many errors before exit 1")
    p.add_argument("--disable", default="",
                   help="comma separated rule ids to silence")
    p.add_argument("--json", action="store_true")
    p.add_argument("--quiet", action="store_true",
                   help="print nothing when the file is clean")
    p.add_argument("--selftest", action="store_true")
    p.add_argument("--version", action="version", version=VERSION)
    a = p.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    if a.selftest:
        return selftest()

    disabled = tuple(x.strip() for x in a.disable.split(",") if x.strip())
    targets = a.files or ["-"]
    total, chunks = 0, []
    for path in targets:
        if path == "-":
            text, name = sys.stdin.read(), "<stdin>"
        else:
            if not os.path.isfile(path):
                print("ste_lint: no such file: %s" % path, file=sys.stderr)
                return 2
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            name = path
        errors, out = report(
            name, check(text, a.mode, a.max_sentence, disabled),
            a.baseline, a.json)
        total += len(errors)
        chunks.append(out)

    failed = total > a.baseline
    if failed or not a.quiet:
        print("\n".join(chunks))
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(2)
    except Exception as exc:  # a linter bug must never break a hook
        print("ste_lint: internal error: %s" % exc, file=sys.stderr)
        sys.exit(2)
