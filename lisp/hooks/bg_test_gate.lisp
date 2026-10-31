;;; bg_test_gate.lisp -- PreToolUse (Bash): deny a bare test run that is not wrapped in bg.
;;;
;;; Port of claude/hooks/bg_test_gate.py (HEAD). A test command (pytest, tox, nox, run_tests*.py,
;;; swift build|test|run, xcodebuild) must go through ~/ops/site-private/bin/bg. The decision is
;;; made per pipeline segment: the first bare test segment denies the whole command.
;;;
;;; Why: one session ran a full pytest suite directly, its runner sized by os.cpu_count() (8
;;; workers, each spawning children). The load average went from 17 to 220 and every other
;;; session starved (2026-10-08). On 2026-10-13 a bare swift test ran one frontend per core.
;;; bg caps parallelism, runs at utility QoS and takes one of two machine-wide test slots.
;;;
;;; HOST CONTRACT
;;;   1. Before evaluating this file the shim sets the global value of *FACTS* to an alist of
;;;      (SYMBOL . VALUE). DEFVAR below only sets *FACTS* when it is still unbound.
;;;   2. Facts this file reads:
;;;        GATE-OFF   T when BG_GATE_OFF is set and non-empty (the operator's escape hatch)
;;;        IS-BASH    T when tool_name is Bash
;;;        SEGMENTS   a list with one symbol per pipeline segment, in order, each either
;;;                   TEST or SKIP. The host does all the text work: it strips heredoc
;;;                   bodies and quoted strings, splits on newline, ;, &&, || and |, and
;;;                   marks a segment TEST when it is a bare test command. It marks SKIP
;;;                   for an empty segment, a segment already starting with bg (or bgb),
;;;                   and a segment that asks for --version, -V, --help, -h, --collect-only
;;;                   or --co. Any parse error means the host returns NIL, which prints
;;;                   nothing (the Python's "fails open").
;;;   3. The last form, (HOOK-MAIN), returns NIL (print nothing) or a template tree:
;;;        (obj (KEY VALUE) ...)  a JSON object; KEY symbols become camelCase keys
;;;        (frag ITEM ...)        a string; ITEM is a literal string or a fact symbol
;;;      The exit status is always 0.
;;;
;;; QUIRKS WORKED AROUND
;;;   - The dialect has no string predicates, no regexes, no string concatenation and no
;;;     loops with early exit (DOLIST always runs to the end). So the segment walk is a
;;;     recursive function that stops at the first TEST. Recursion is fine at this size:
;;;     calls are not tail-call optimised, but a command has a few dozen segments at most.
;;;   - COND falls through to the last clause's body when nothing matches. Every COND here
;;;     ends with an explicit T clause.
;;;   - EQ compares symbols by identity. The host sends symbols, so no string test is needed.
;;;   - Dynamic scope: FACT and HAS-TEST-SEGMENT see *FACTS* from any depth of the call.
;;;
;;; THE CHECKS, IN ORDER (same as the Python)
;;;   a. BG_GATE_OFF set, or not a Bash call: silent.
;;;   b. The first TEST segment, if any: deny with the bg reason. Otherwise silent.
;;;
;;; WORKED CASES (facts -> answer)
;;;   gate-off  is-bash  segments                  answer
;;;   T         -        -                         silent (the operator's escape hatch)
;;;   NIL       NIL      (TEST)                    silent (not a Bash call)
;;;   NIL       T        (SKIP SKIP)               silent (nothing to deny)
;;;   NIL       T        (SKIP TEST SKIP)          deny (the second segment is a bare test run)
;;;   NIL       T        (TEST TEST)               deny, once (the first TEST is enough)
;;;   NIL       T        ()                        silent (an empty command, or a host parse failure)
;;;   Bare "pytest" and "swift test" are TEST; "bg pytest" and "pytest --collect-only" are SKIP.

(defvar *facts* nil)

(defun fact (key)
  "The value recorded for KEY in *FACTS*, or NIL when there is none."
  (cdr (assoc key *facts*)))

(defun has-test-segment (segments)
  "T when some segment in SEGMENTS, in order, is the symbol TEST. Stops at the first one."
  (cond ((null segments) nil)
        ((eq (car segments) 'test) t)
        (t (has-test-segment (cdr segments)))))

(defun hook-main ()
  "Choose the answer for the current facts. NIL means print nothing."
  (cond ((fact 'gate-off) nil)
        ((not (fact 'is-bash)) nil)
        ((has-test-segment (fact 'segments)) (deny-response))
        (t nil)))

(defun deny-response ()
  "The denial with the bg reason. The text is the Python f-string, joined in the same order."
  '(obj (hook-specific-output
         (obj (hook-event-name "PreToolUse")
              (permission-decision "deny")
              (permission-decision-reason
               (frag "Tests run through bg, not bare: ~/ops/site-private/bin/bg <your command> (bare `bg` is the shell job-control builtin, so use the full path). bg caps parallelism, runs at utility QoS and takes one of two machine-wide test slots; a bare run of a full suite sent the load average to 220 on 2026-10-08. Run the changed files first (--lf -x); run the full suite only when asked."))))))

;; The shim evaluates the file and reads the value of this last form.
(hook-main)
