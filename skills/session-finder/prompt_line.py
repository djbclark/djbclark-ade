#!/usr/bin/env python3
"""prompt_line — the operator's own text on a TUI's input line, read from ANSI screen output. No model.

    prompt_line.py MARK < screen.ansi      prints the operator text after the last MARK line, EMPTY, or NOPROMPT

Claude Code paints its hint text and its suggested next prompt (ghost text, accepted with Tab, replaced by
anything typed) in grey (38;2;153;153;153, the ❯'s own colour) or dim (ESC[2m); the operator's typed text is
in the default colour. cursor-agent draws its cursor block in reverse video over the first letter of its dim
placeholder. So only unstyled text counts as a draft. Same rules as bin/self-slash's classify_prompt
(2026-10-09); relay.py uses this since 2026-10-16, when it refused a pane whose only "draft" was a dim
suggestion ("install the new build on the phone").
"""
import re
import sys

HINTS = ("Try \"", "Try “", "Press up to edit queued messages", "Plan, search, build anything",
         "Add a follow-up")
GREYS = (["2", "153", "153", "153"], ["5", "245"], ["5", "8"])


def operator_text(after: str) -> str:
    """Unstyled text in `after` (the part of the prompt line after its mark), hints dropped."""
    dim = grey = rev = False
    plain: list[str] = []
    for tok in re.split(r"(\x1b\[[0-9;]*m)", after):
        if tok.startswith("\x1b["):
            # Walk the parameters: 38/48 consume their colour arguments, so the "2" in
            # an RGB background (48;2;r;g;b) is not read as dim.
            codes = tok[2:-1].split(";") if tok[2:-1] else ["0"]
            i = 0
            while i < len(codes):
                c = codes[i]
                if c in ("38", "48"):
                    n = 3 if codes[i + 1:i + 2] == ["5"] else 5
                    if c == "38":
                        grey = codes[i + 1:i + n] in GREYS
                    i += n
                    continue
                if c in ("", "0"):
                    dim = grey = rev = False
                elif c == "2":
                    dim = True
                elif c == "22":
                    dim = False
                elif c == "7":
                    rev = True
                elif c == "27":
                    rev = False
                elif c in ("39", "37", "97"):
                    grey = False
                elif c == "90":
                    grey = True
                i += 1
            continue
        txt = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", tok).replace("\xa0", " ").replace("\r", "")
        if txt.strip() and not (dim or grey or rev):
            plain.append(txt)
    text = "".join(plain).strip()
    # Real hints are grey or dim and already dropped above; only a row that carried no style at all (a plain-text
    # screen read) needs the string list. With styles, `Try "make test" first` in the default colour is the operator's.
    return "" if text.startswith(HINTS) and "\x1b[" not in after else text


OMP_MARK = "╰─ "


def omp_after(after: str) -> str:
    """omp draws its input as the box's last row: `╰─ TEXT … ⇧⇥ to change thinking effort ─╯`. The right border and,
    when the line is empty, the `⇧⇥` hint are in plain-looking colours, so cut them before the style walk."""
    after = after.split("⇧⇥", 1)[0]
    return re.sub(r"\s*─╯(?:\x1b\[[0-9;]*m)*\s*$", "", after)


def classify(screen: str, mark: str = "❯") -> str | None:
    """None when no line holds `mark`, else the operator text after the last one ("" = empty)."""
    lines = [ln for ln in screen.splitlines() if mark in ln]
    if not lines:
        return None
    after = lines[-1].split(mark, 1)[1]
    return operator_text(omp_after(after) if mark == OMP_MARK else after)


if __name__ == "__main__":
    mark = sys.argv[1] if len(sys.argv) > 1 else "❯"
    screen = sys.stdin.read()
    r = classify(screen, mark)
    print("NOPROMPT" if r is None else (r or "EMPTY"))
    if r is not None:  # the raw line, for bin/self-slash's log
        print("RAW " + repr([ln for ln in screen.splitlines() if mark in ln][-1][:220]), file=sys.stderr)
