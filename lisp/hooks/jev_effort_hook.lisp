;;; jev_effort_hook.lisp -- UserPromptSubmit: optional effort observation through bin/jev.
;;;
;;; Port of claude/hooks/jev_effort_hook.py (HEAD). Failures never block a prompt. The hook
;;; observes in shadow mode and speaks only in act mode, and only with a systemMessage that
;;; suggests /model sonnet when a prompt looks mechanical and the session runs an expensive model.
;;;
;;; What stays in the Python shim, and why: the 2.9 s SIGALRM deadline (this dialect has no
;;; signals, so the host uses subprocess timeouts instead, with the same 2.7 s budget), the
;;; reading of the mode file and environment, the prompt skip test (regexes and a JSON parse),
;;; the tail read of the transcript for the model, the call to bin/jev, and the two-decimal
;;; formatting of the probability. Deciding what to say is this file's job.
;;;
;;; HOST CONTRACT
;;;   1. Before evaluating this file the shim sets the global value of *FACTS* to an alist of
;;;      (SYMBOL . VALUE). DEFVAR below only sets *FACTS* when it is still unbound.
;;;   2. Facts this file reads:
;;;        MODE             the symbol OFF, SHADOW or ACT (JEV_MODE, else ~/.config/jev/mode,
;;;                         else OFF; any other value is OFF)
;;;        SKIP             T when the prompt is too short, starts with /, is a task
;;;                         notification or tool result, or is only tool_result JSON blocks
;;;        ANSWER           the symbol MECHANICAL, NORMAL or HARD from bin/jev, or OTHER when
;;;                         jev failed, timed out, printed nothing, or gave another answer
;;;        CONFIDENT        T when bin/jev reported confident true
;;;        EXPENSIVE-MODEL  T when the transcript's model name contains "opus" or "fable"
;;;        PROB-2DP         the probability formatted to two decimals, e.g. "0.87"
;;;   3. The last form, (HOOK-MAIN), returns NIL (print nothing) or a template tree:
;;;        (obj (KEY VALUE) ...)  a JSON object; KEY symbols become camelCase keys
;;;        (frag ITEM ...)        a string; ITEM is a literal string or a fact symbol
;;;      The shim runs bin/jev before this file is consulted whenever MODE is not OFF and
;;;      SKIP is NIL, because shadow mode records an observation even though it prints nothing.
;;;      The exit status is always 0.
;;;
;;; QUIRKS WORKED AROUND
;;;   - No strings are compared here. The host turns the jev answer into a symbol, and EQ
;;;     does the test. EQ on symbols is identity, which is what we want.
;;;   - COND falls through to its last clause body when nothing matches. The COND below
;;;     ends in an explicit T clause.
;;;   - Dynamic scope: FACT reads *FACTS* from any depth of the call.
;;;   - Probabilities are not formatted here: the dialect has no floats and no format
;;;     directives, so the host sends the two-decimal text.
;;;
;;; THE CHECKS, IN ORDER (same as the Python)
;;;   a. MODE is OFF: silent (the Python exits before it reads anything).
;;;   b. SKIP is T: silent.
;;;   c. MODE is SHADOW: silent. The observation has already been recorded by the shim.
;;;   d. ANSWER is not MECHANICAL, or CONFIDENT is NIL: silent.
;;;   e. EXPENSIVE-MODEL is NIL: silent. Otherwise say so, with the probability.
;;;
;;; WORKED CASES (facts -> answer)
;;;   mode     skip  answer       confident  expensive  answer
;;;   OFF      -     -            -          -          silent (jev is never called)
;;;   SHADOW   NIL   MECHANICAL   T          T          silent (observed only)
;;;   ACT      T     MECHANICAL   T          T          silent (a skipped prompt)
;;;   ACT      NIL   HARD         T          T          silent (not mechanical)
;;;   ACT      NIL   MECHANICAL   NIL        T          silent (not confident)
;;;   ACT      NIL   MECHANICAL   T          NIL        silent (already on a cheap model)
;;;   ACT      NIL   MECHANICAL   T          T          systemMessage with the probability

(defvar *facts* nil)

(defun fact (key)
  "The value recorded for KEY in *FACTS*, or NIL when there is none."
  (cdr (assoc key *facts*)))

(defun hook-main ()
  "Choose the answer for the current facts. NIL means print nothing."
  (cond ((eq (fact 'mode) 'off) nil)
        ((fact 'skip) nil)
        ((not (eq (fact 'mode) 'act)) nil)
        ((not (eq (fact 'answer) 'mechanical)) nil)
        ((not (fact 'confident)) nil)
        ((not (fact 'expensive-model)) nil)
        (t (suggest-response))))

(defun suggest-response ()
  "The systemMessage. Same words as the Python f-string; PROB-2DP is the host's formatting."
  '(obj (system-message
         (frag "jev: this looks mechanical (p=" prob-2dp "); /model sonnet would cost less"))))

;; The shim evaluates the file and reads the value of this last form.
(hook-main)
