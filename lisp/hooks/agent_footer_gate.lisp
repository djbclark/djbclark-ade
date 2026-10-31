;;; agent_footer_gate.lisp -- PreToolUse (Agent): append the delivery footer to a sub-agent prompt.
;;;
;;; Port of claude/hooks/agent_footer_gate.py (HEAD). The policy (which branch answers) lives
;;; in this file. Everything the dialect cannot do (JSON, regexes, files, subprocesses, string
;;; tests) is done by the host shim, described in the contract below.
;;;
;;; HOST CONTRACT
;;;   1. Before evaluating this file the shim sets the global value of *FACTS* to an alist of
;;;      (SYMBOL . VALUE). The DEFVAR below only sets *FACTS* when it is still unbound, so the
;;;      shim's value is the one this file sees.
;;;   2. Facts this file reads:
;;;        TOOL-IS-AGENT  T when tool_name is Agent or Task
;;;        GATE-OFF       T when AGENT_FOOTER_GATE_OFF is set and non-empty
;;;        EXEMPT         T when subagent_type is claude-code-guide or statusline-setup
;;;        HAS-MARK       T when the prompt already contains "Delivery contract"
;;;        FOOTER         the acp-dispatch footer text, or NIL when it could not be built
;;;        PROMPT-RSTRIP  the prompt with trailing whitespace removed
;;;        REPORT         the report path the footer was built for
;;;        TWO-NL         the two-character string of two newlines
;;;        ONE-NL         one newline
;;;      The shim may leave a fact NIL when the branch that reads it is not taken. FOOTER and
;;;      REPORT are only needed once the first four tests have let the hook proceed.
;;;   3. The last form, (HOOK-MAIN), returns NIL (print nothing) or a template tree:
;;;        (obj (KEY VALUE) ...)   a JSON object; KEY symbols become camelCase keys
;;;        (frag ITEM ...)         a string; each ITEM is a literal string or a fact symbol,
;;;                                replaced by that fact's value and joined in order
;;;        (prompt-with FRAG)      tool_input with its prompt replaced by the FRAG text
;;;        (arr ITEM ...)          a JSON array
;;;      The exit status is always 0. Every branch of this hook fails open, and an error
;;;      inside the dialect makes the shim print nothing and exit 0.
;;;
;;; QUIRKS WORKED AROUND
;;;   - There is no string predicate and no string concatenation, so the host does both.
;;;   - The reader takes the character after a backslash literally, so "\n" reads as "n".
;;;     Newlines are therefore carried as the TWO-NL and ONE-NL facts instead.
;;;   - COND evaluates the body of its last clause when nothing matches. Every COND here ends
;;;     with an explicit T clause, so the default is written down rather than inherited.
;;;   - IF takes one form per branch. Branches that need several forms use PROGN.
;;;   - Variables are dynamically scoped, so FACT reads *FACTS* from anywhere in the call.
;;;
;;; THE CHECKS, IN ORDER (same as the Python)
;;;   a. Not an Agent or Task tool call: silent.
;;;   b. AGENT_FOOTER_GATE_OFF: silent.
;;;   c. Exempt sub-agent type, or the footer heading already present: silent.
;;;   d. The footer could not be built: deny, with the reason text.
;;;   e. Otherwise append the footer through updatedInput and say where the report is.

(defvar *facts* nil)

(defun fact (key)
  "The value recorded for KEY in *FACTS*, or NIL when there is none."
  (cdr (assoc key *facts*)))

(defun hook-main ()
  "Pick the answer for the current facts. NIL means print nothing."
  (cond ((not (fact 'tool-is-agent)) nil)
        ((fact 'gate-off) nil)
        ((or (fact 'exempt) (fact 'has-mark)) nil)
        ((not (fact 'footer)) (deny-response))
        (t (allow-response))))

(defun deny-response ()
  "The denial used when no footer can be built. The text is the Python DENY_REASON, verbatim."
  '(obj (hook-specific-output
         (obj (hook-event-name "PreToolUse")
              (permission-decision "deny")
              (permission-decision-reason
               (frag "This sub-agent prompt has no delivery footer (~/CLAUDE.md rule 25) and the hook could not build one. Run `~/src/djbclark-ade/bin/acp-dispatch footer --report <scratchpad>/<name>-report.md`, paste its output (it starts with '## Delivery contract') at the end of the prompt, and launch again; then read that report file, not the final message."))))))

(defun allow-response ()
  "Append the footer to the prompt and tell the model where its report goes.
The prompt is the stripped prompt, two newlines, the footer, then one newline, as in the Python."
  '(obj (hook-specific-output
         (obj (hook-event-name "PreToolUse")
              (updated-input
               (prompt-with (frag prompt-rstrip two-nl footer one-nl)))
              (additional-context
               (frag "agent_footer_gate appended the delivery footer to this sub-agent's prompt. Its report is "
                     report
                     " (done marker "
                     report
                     ".done): read that file, not the final message."))))))

;; The shim evaluates the file and reads the value of this last form.
(hook-main)
