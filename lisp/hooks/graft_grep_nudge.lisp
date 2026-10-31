;;; graft_grep_nudge.lisp -- PreToolUse (Grep|Glob|Bash): once per session, remind the model to try graft.
;;;
;;; Port of claude/hooks/graft_grep_nudge.py (HEAD). Non-blocking: the answer is additionalContext
;;; only. Silent when the repo has no graft/INDEX.md, when a Bash call is not a code search, or
;;; when this session's marker already exists.
;;;
;;; HOST CONTRACT
;;;   1. Before evaluating this file the shim sets the global value of *FACTS* to an alist of
;;;      (SYMBOL . VALUE). DEFVAR below only sets *FACTS* when it is still unbound.
;;;   2. Facts this file reads:
;;;        HAS-GRAFT-INDEX  T when <cwd or CLAUDE_PROJECT_DIR or getcwd>/graft/INDEX.md is a file
;;;        IS-BASH          T when tool_name is Bash
;;;        SEARCH-CMD       T when the command, after the host strips heredoc bodies and quoted
;;;                         strings, has grep, egrep, rg, ag, ack, find or fd as a command word.
;;;                         Only consulted when IS-BASH is T.
;;;        MARKER-SET       T when the file graft-nudge-<session_id> already exists in the temp dir
;;;   3. The last form, (HOOK-MAIN), returns NIL (print nothing) or a template tree:
;;;        (obj (KEY VALUE) ...)  a JSON object; KEY symbols become camelCase keys
;;;        (frag ITEM ...)        a string; ITEM is a literal string or a fact symbol
;;;      When the answer is not NIL the shim creates the marker file (the Python does this
;;;      before printing, and a failure to create it is ignored), then prints the object.
;;;      The exit status is always 0.
;;;
;;; QUIRKS WORKED AROUND
;;;   - No string predicates or concatenation exist in this dialect, so the regexes, the
;;;     heredoc stripping and the marker file are the host's work.
;;;   - COND falls through to its last clause body when nothing matches, so the last clause here
;;;     is an explicit T.
;;;   - Dynamic scope: FACT reads *FACTS* from any depth of the call.
;;;
;;; THE CHECKS, IN ORDER (same as the Python)
;;;   a. No graft index in the repo: silent.
;;;   b. Bash that is not a code search: silent. Grep and Glob always go on to the next check.
;;;   c. Marker already set for this session: silent.
;;;   d. Otherwise: additionalContext naming the four graft commands.
;;;
;;; WORKED CASES (facts -> answer), for whoever checks the port against the Python
;;;   has-graft-index  is-bash  search-cmd  marker-set   answer
;;;   NIL              -        -          -            silent (no index: the repo is not graft-indexed)
;;;   T                T        NIL        -            silent (a Bash call that is not a code search)
;;;   T                T        T          T            silent (this session already had its nudge)
;;;   T                T        T          NIL          nudge; the shim then creates the marker
;;;   T                NIL      -          NIL          nudge (Grep and Glob are not Bash, so no search test)
;;;   T                NIL      -          T            silent
;;;   The marker is per session, so a second nudge in one session never happens.
;;;
;;; NOTES ON THE HOST SIDE (the Python behaviour the shim keeps)
;;;   - The marker lives in the temp directory, under graft-nudge-<session_id>, as in HEAD. A
;;;     session id of "default" is used when the hook JSON has none.
;;;   - A failure to create the marker is ignored, so the nudge still goes out once more.
;;;   - Unparseable hook JSON stops the hook silently, before any fact is computed.
;;;   - The repo root is cwd, else CLAUDE_PROJECT_DIR, else the process cwd. Only
;;;     <root>/graft/INDEX.md counts as indexed; a graft directory without INDEX.md is silent.
;;;   - The SEARCH-CMD fact is the one place the heredoc and quote stripping matter. A command
;;;     that only mentions grep inside quotes, or inside a heredoc body, is not a search, so it
;;;     must reach this file as NIL. The strip is the host's, and the Lisp takes its word for it.
;;;   - Only grep, egrep, rg, ag, ack, find and fd, each as a command word after the start of a
;;;     line, a pipe, a semicolon, an ampersand, an open parenthesis or a space, count as searches.

(defvar *facts* nil)

(defun fact (key)
  "The value recorded for KEY in *FACTS*, or NIL when there is none."
  (cdr (assoc key *facts*)))

(defun hook-main ()
  "Choose the answer for the current facts. NIL means print nothing."
  (cond ((not (fact 'has-graft-index)) nil)
        ((and (fact 'is-bash) (not (fact 'search-cmd))) nil)
        ((fact 'marker-set) nil)
        (t (nudge-response))))

(defun nudge-response ()
  "The one-time nudge. The text is the Python string, joined in the same order."
  '(obj (hook-specific-output
         (obj (hook-event-name "PreToolUse")
              (additional-context
               (frag "This repo is indexed by graft. Before grepping/globbing for code, try `graft ask` (how/where), `graft grep` (every occurrence), `graft callers` (callers/blast radius) or `graft skeleton` (a file's API). Fall back to Grep/Glob for non-code text or when graft misses."))))))

;; The shim evaluates the file and reads the value of this last form.
(hook-main)
