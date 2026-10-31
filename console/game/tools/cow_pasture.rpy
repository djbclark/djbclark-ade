# cow-pasture.rpy
# A visual novel front end for managing copy-on-write pastures. Each pasture
# is a scene; the player walks the herd through create, list, enter and retire.

define narrator = Character(None)
define herder = Character("Herder", color="#c9a77f")
define pasture_ai = Character("Pasture", color="#7fc9a8")
define ledger = Character("Ledger", color="#a8a8c9")

default pastures = []
default pasture_next_id = 1
default pasture_base = "master"
default pasture_quota_gb = 40
default pasture_used_gb = 0
default pasture_log = []
default pasture_active = None
default pasture_dry_run = False
default pasture_confirm_retire = True

init python:
    import time

    PASTURE_ROOT = "/home/arch/src/pastures"
    PASTURE_MAX = 12
    PASTURE_CLONE_GB = 2

    class Pasture(object):
        def __init__(self, pid, name, base, created):
            self.pid = pid
            self.name = name
            self.base = base
            self.created = created
            self.status = "open"
            self.size_gb = PASTURE_CLONE_GB
            self.notes = []

        def label(self):
            return "%s (%s)" % (self.name, self.status)

        def path(self):
            return "%s/%03d-%s" % (PASTURE_ROOT, self.pid, self.name)

        def add_note(self, text):
            self.notes.append(text)

    def pasture_find(name):
        for p in store.pastures:
            if p.name == name:
                return p
        return None

    def pasture_open(name):
        if pasture_find(name) is not None:
            return None, "a pasture named %s already exists" % name
        if len(store.pastures) >= PASTURE_MAX:
            return None, "the pasture limit of %d is reached" % PASTURE_MAX
        if store.pasture_used_gb + PASTURE_CLONE_GB > store.pasture_quota_gb:
            return None, "not enough quota for another pasture"
        p = Pasture(store.pasture_next_id, name, store.pasture_base, time.time())
        store.pasture_next_id += 1
        store.pastures.append(p)
        store.pasture_used_gb += p.size_gb
        pasture_log_add("open", p.name)
        return p, None

    def pasture_retire(name):
        p = pasture_find(name)
        if p is None:
            return False, "no pasture named %s" % name
        if p.status == "retired":
            return False, "%s is already retired" % name
        p.status = "retired"
        store.pasture_used_gb = max(0, store.pasture_used_gb - p.size_gb)
        pasture_log_add("retire", p.name)
        return True, None

    def pasture_reopen(name):
        p = pasture_find(name)
        if p is None:
            return False, "no pasture named %s" % name
        if p.status != "retired":
            return False, "%s is not retired" % name
        if store.pasture_used_gb + p.size_gb > store.pasture_quota_gb:
            return False, "not enough quota to reopen %s" % name
        p.status = "open"
        store.pasture_used_gb += p.size_gb
        pasture_log_add("reopen", p.name)
        return True, None

    def pasture_log_add(verb, name):
        stamp = time.strftime("%H:%M:%S")
        store.pasture_log.append("%s %s %s" % (stamp, verb, name))
        if len(store.pasture_log) > 200:
            store.pasture_log = store.pasture_log[-200:]

    def pasture_open_list():
        return [p for p in store.pastures if p.status == "open"]

    def pasture_retired_list():
        return [p for p in store.pastures if p.status == "retired"]

    def pasture_quota_left():
        return store.pasture_quota_gb - store.pasture_used_gb

    def pasture_quota_bar(width=20):
        if store.pasture_quota_gb <= 0:
            return "-" * width
        filled = int(width * store.pasture_used_gb / float(store.pasture_quota_gb))
        filled = max(0, min(width, filled))
        return "#" * filled + "." * (width - filled)

    def pasture_summary():
        return "%d open, %d retired, %d GB free" % (
            len(pasture_open_list()), len(pasture_retired_list()), pasture_quota_left())

    def pasture_rename(old, new):
        p = pasture_find(old)
        if p is None:
            return False, "no pasture named %s" % old
        if pasture_find(new) is not None:
            return False, "%s already exists" % new
        p.name = new
        pasture_log_add("rename", "%s->%s" % (old, new))
        return True, None

    def pasture_note(name, text):
        p = pasture_find(name)
        if p is None:
            return False
        p.add_note(text)
        return True

    def pasture_sorted():
        return sorted(store.pastures, key=lambda p: (p.status != "open", p.name))

    def pasture_base_set(branch):
        store.pasture_base = branch
        pasture_log_add("base", branch)

    def pasture_clean_names(raw):
        out = []
        for ch in raw.strip().lower():
            if ch.isalnum() or ch in "-_":
                out.append(ch)
            elif ch == " ":
                out.append("-")
        cleaned = "".join(out).strip("-")
        return cleaned[:32]

    def pasture_validate_name(raw):
        name = pasture_clean_names(raw)
        if not name:
            return None, "the name is empty after cleaning"
        if name[0] in "-_":
            return None, "a name cannot start with a dash or underscore"
        return name, None

    def pasture_dry_line(verb, name):
        return "would %s %s" % (verb, name) if store.pasture_dry_run else "%s %s" % (verb, name)


label pasture_start:
    scene black
    narrator "The gate opens onto a long field of copy-on-write pastures."
    pasture_ai "Each pasture is a cheap copy of the base. Nothing is shared until it is written."
    herder "Let me see what is already grazing here."
    jump pasture_menu


label pasture_menu:
    $ summary = pasture_summary()
    ledger "[summary]"
    ledger "Quota [pasture_quota_bar()]"
    menu pasture_top:
        "Open a new pasture":
            jump pasture_open_flow
        "List the pastures":
            jump pasture_list_flow
        "Enter a pasture":
            jump pasture_enter_flow
        "Retire a pasture":
            jump pasture_retire_flow
        "Reopen a retired pasture":
            jump pasture_reopen_flow
        "Rename a pasture":
            jump pasture_rename_flow
        "Change the base branch":
            jump pasture_base_flow
        "Read the ledger":
            jump pasture_ledger_flow
        "Leave the field":
            jump pasture_leave


label pasture_open_flow:
    if store.pasture_quota_gb - store.pasture_used_gb < PASTURE_CLONE_GB:
        pasture_ai "There is no room for another pasture under this quota."
        jump pasture_menu
    herder "What shall I call the new pasture?"
    $ raw_name = renpy.input("Pasture name", default="", length=32)
    $ name, err = pasture_validate_name(raw_name)
    if err is not None:
        pasture_ai "[err]"
        jump pasture_menu
    $ pasture, err = pasture_open(name)
    if err is not None:
        pasture_ai "[err]"
        jump pasture_menu
    $ line = pasture_dry_line("open", pasture.name)
    pasture_ai "[line] from base [pasture_base]."
    pasture_ai "Path: [pasture.path()]"
    jump pasture_menu


label pasture_list_flow:
    $ rows = pasture_sorted()
    if not rows:
        ledger "No pastures have been opened yet."
        jump pasture_menu
    $ i = 0
    while i < len(rows):
        $ r = rows[i]
        ledger "[r.pid]. [r.label()] on [r.base], [r.size_gb] GB"
        $ i += 1
    jump pasture_menu


label pasture_enter_flow:
    $ opened = pasture_open_list()
    if not opened:
        pasture_ai "There is no open pasture to enter."
        jump pasture_menu
    $ raw = renpy.input("Which pasture", default="", length=32)
    $ name = pasture_clean_names(raw)
    $ target = pasture_find(name)
    if target is None or target.status != "open":
        pasture_ai "No open pasture called [name]."
        jump pasture_menu
    $ pasture_active = target.name
    herder "I am now in [pasture_active]."
    pasture_ai "Working tree lives at [target.path()]."
    jump pasture_menu


label pasture_retire_flow:
    $ opened = pasture_open_list()
    if not opened:
        pasture_ai "Nothing is open to retire."
        jump pasture_menu
    $ raw = renpy.input("Which pasture to retire", default="", length=32)
    $ name = pasture_clean_names(raw)
    if store.pasture_confirm_retire:
        menu:
            "Retire [name] for certain?"
            "Yes, retire it":
                pass
            "No, keep it":
                jump pasture_menu
    $ ok, why = pasture_retire(name)
    if ok:
        pasture_ai "[name] is retired and its quota is returned."
    else:
        pasture_ai "[why]"
    jump pasture_menu


label pasture_reopen_flow:
    $ gone = pasture_retired_list()
    if not gone:
        pasture_ai "No pasture is retired."
        jump pasture_menu
    $ raw = renpy.input("Which retired pasture to reopen", default="", length=32)
    $ name = pasture_clean_names(raw)
    $ ok, why = pasture_reopen(name)
    if ok:
        pasture_ai "[name] is open again."
    else:
        pasture_ai "[why]"
    jump pasture_menu


label pasture_rename_flow:
    $ raw_old = renpy.input("Current name", default="", length=32)
    $ raw_new = renpy.input("New name", default="", length=32)
    $ old = pasture_clean_names(raw_old)
    $ new, err = pasture_validate_name(raw_new)
    if err is not None:
        pasture_ai "[err]"
        jump pasture_menu
    $ ok, why = pasture_rename(old, new)
    if ok:
        pasture_ai "Renamed to [new]."
    else:
        pasture_ai "[why]"
    jump pasture_menu


label pasture_base_flow:
    ledger "The base is [pasture_base]."
    menu:
        "Use master":
            $ pasture_base_set("master")
        "Use main":
            $ pasture_base_set("main")
        "Keep it":
            pass
    jump pasture_menu


label pasture_ledger_flow:
    if not pasture_log:
        ledger "The ledger is empty."
        jump pasture_menu
    $ tail = pasture_log[-10:]
    $ j = 0
    while j < len(tail):
        ledger "[tail[j]]"
        $ j += 1
    jump pasture_menu


label pasture_leave:
    scene black
    herder "The gate is shut behind me."
    pasture_ai "The pastures keep their copies until someone retires them."
    return
