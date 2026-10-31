;;; autorename_nudge.lisp -- ask the agent to title an untitled session, once.
;;;
;;; Port of skills/autorename/autorename_nudge.py (HEAD). The hook hands the agent a note: run the
;;; autorename skill in --auto mode as the last step of the turn, to title the session and label
;;; its own tab, nothing else. The backend (Claude Code, cursor-agent, Grok, zcode) is chosen by
;;; the host, and so is every text and filesystem check. This file decides which gate stops the
;;; hook, whether the once-per-session marker is written, and which envelope the note goes out in.
;;;
;;; ORDER THAT MATTERS
;;;   The Python writes the once-per-session marker BEFORE it checks whether the title is set. So a
;;;   session that already has a title still gets its marker. That is why the answer below is a
;;;   plan (MARK-NUDGED, then OUTPUT) and not just the note.
;;;
;;; WHAT THE HOST DOES
;;;   Arms the 2 s alarm (the Python exits silently when it fires; the shim does the same), reads
;;;   the stdin JSON, works out the backend and the session id, checks cursor headless mode with
;;;   ps, reads the first prompt line of a zcode transcript, reads the title for each backend,
;;;   reads and writes ~/.local/state/autorename/<sid>.nudged, and prints. The sid-safety and
;;;   the marker file are host work, because they are path and file operations.
;;;
;;; HOST CONTRACT
;;;   1. Before evaluating this file the shim sets the global value of *FACTS* to an alist of
;;;      (SYMBOL . VALUE). DEFVAR below only sets *FACTS* when it is still unbound.
;;;   2. Facts this file reads:
;;;        BACKEND           the symbol CLAUDE, CURSOR, GROK or ZCODE, from the hook event and
;;;                          the session id shape (Stop or stop means GROK; a cursor_version,
;;;                          generation_id or beforeSubmitPrompt means CURSOR; sess_ means ZCODE)
;;;        CURSOR-EVENT-OK   T when the event is "", beforeSubmitPrompt or UserPromptSubmit
;;;        CURSOR-HEADLESS   T when the cursor-agent above this hook runs with acp, -p or --print
;;;        GROK-HOLD         T when stopHookActive or subagentType is set (a continuation or a
;;;                          subagent must be allowed to stop)
;;;        GROK-REASON-OK    T when the stop reason is absent, empty or end_turn
;;;        ENTRYPOINT-OK     T when CLAUDE_CODE_ENTRYPOINT (default cli) is cli
;;;        SID-PRESENT       T when the session id is non-empty
;;;        SID-SAFE          T when the session id has no slash or backslash and is not . or ..
;;;        PROMPT-LEN        the stripped prompt's length, in characters (the host reads the
;;;                          zcode transcript when the prompt is not a string)
;;;        PROMPT-BARE       T when the prompt starts with / and has no space in it
;;;        ALREADY-NUDGED    T when the <sid>.nudged marker file exists
;;;        TITLE-SET         T when the backend says the session is titled or manual (cursor's
;;;                          manual check, grok's manual check, zcode's generated or custom
;;;                          title, the Claude custom-title record). Missing sessions count as
;;;                          set for grok and zcode, and as unset for cursor, as the Python does.
;;;        PY                the interpreter path for the note: PY when it exists, else python3
;;;        SKILL-DIR         the directory of autorename_nudge.py, for the two script paths
;;;   3. The last form, (HOOK-MAIN), returns NIL (print nothing), or
;;;        (obj (mark-nudged yes) (output OUTPUT))
;;;      where OUTPUT is NONE (write the marker, print nothing) or an envelope:
;;;        (text FRAG)                          claude: print the note as plain text
;;;        (obj ("additional_context" FRAG))    cursor: one JSON object, snake_case key kept
;;;        (obj (hook-specific-output (obj (hook-event-name NAME) (additional-context FRAG))))
;;;                                             zcode and grok: NAME is UserPromptSubmit, or
;;;                                             Stop for grok
;;;      The shim writes the marker file as a side effect of the (mark-nudged yes) item, before
;;;      it prints. The exit status is always 0.
;;;
;;; QUIRKS WORKED AROUND
;;;   - The dialect has no string predicates, so every startswith, in and length test is a host
;;;     fact. Here the only length test is an integer comparison.
;;;   - The reader takes the character after a backslash literally, so \" in the note reads as a
;;;     plain double quote. That is what the Python prints.
;;;   - The cursor envelope key is snake_case in the JSON, and the Python keeps it that way. A
;;;     string key in an (obj ...) is printed verbatim; a symbol key is camelCased.
;;;   - COND falls through to its last clause body when nothing matches. Every COND here ends in
;;;     an explicit T clause.
;;;   - Dynamic scope: FACT reads *FACTS* from any depth of the call.
;;;
;;; THE CHECKS, IN ORDER (same as the Python)
;;;   a. The backend's gate: cursor needs a known event and no headless run; grok needs no
;;;      hold and an end_turn reason; claude and zcode need the cli entrypoint (zcode always
;;;      passes). A failed gate is silent and writes nothing.
;;;   b. The prompt: grok needs a session id; every other backend needs a session id, a prompt
;;;      of at least MIN-PROMPT-CHARS characters, and not a bare slash command. Silent otherwise.
;;;   c. The session id is safe to use as a file name. Silent otherwise.
;;;   d. A marker already exists: silent.
;;;   e. Write the marker. Then, unless the title is already set, print the note in the
;;;      backend's envelope.

(defvar *facts* nil)
(defvar min-prompt-chars 20)

(defun fact (key)
  "The value recorded for KEY in *FACTS*, or NIL when there is none."
  (cdr (assoc key *facts*)))

(defun backend-gate-ok ()
  "Step a. Each backend has its own early exit; a failed gate writes nothing."
  (let ((backend (fact 'backend)))
    (cond ((eq backend 'cursor)
           (and (fact 'cursor-event-ok) (not (fact 'cursor-headless))))
          ((eq backend 'grok)
           (and (not (fact 'grok-hold)) (fact 'grok-reason-ok)))
          (t
           (or (eq backend 'zcode) (fact 'entrypoint-ok))))))

(defun prompt-ok ()
  "Step b. Grok only needs a session id. The others also need a prompt that is long enough
and is not a bare slash command."
  (cond ((eq (fact 'backend) 'grok) (fact 'sid-present))
        (t (and (fact 'sid-present)
                (>= (fact 'prompt-len) min-prompt-chars)
                (not (fact 'prompt-bare))))))

(defun note-frag ()
  "The note as a frag. The words are the Python note_text() words, in the same order."
  (list 'frag
        "[autorename] This session has no title yet. As the LAST step of this turn, after the requested work, follow the autorename skill in --auto mode: pick a title, run `"
        (fact 'py) " " (fact 'skill-dir)
        "/autorename.py --auto \"<title>\"`, THEN run `"
        (fact 'py) " " (fact 'skill-dir)
        "/herdr_place.py label --from-title` (labels a generic herdr tab from the new title; prints `skipped:` outside herdr and in a Paseo-hosted agent, whose tab autorename.py names). Rename nothing else: no workspace, no moving the tab. Mention the result in one line; don't otherwise discuss this note."))

(defun output-for (backend note)
  "The envelope for BACKEND. Claude prints the note as text; cursor uses its snake_case key;
grok and zcode use hookSpecificOutput, with Stop as the event for grok only."
  (cond ((eq backend 'claude) (list 'text note))
        ((eq backend 'cursor) (list 'obj (list "additional_context" note)))
        (t (list 'obj
                 (list 'hook-specific-output
                       (list 'obj
                             (list 'hook-event-name
                                   (if (eq backend 'grok) "Stop" "UserPromptSubmit"))
                             (list 'additional-context note)))))))

(defun hook-main ()
  "Choose the answer for the current facts. NIL means print nothing and write nothing."
  (cond ((not (backend-gate-ok)) nil)
        ((not (prompt-ok)) nil)
        ((not (fact 'sid-safe)) nil)
        ((fact 'already-nudged) nil)
        (t (list 'obj
                 (list 'mark-nudged 'yes)
                 (list 'output
                       (if (fact 'title-set)
                           'none
                           (output-for (fact 'backend) (note-frag))))))))

;; The shim evaluates the file and reads the value of this last form.
(hook-main)
