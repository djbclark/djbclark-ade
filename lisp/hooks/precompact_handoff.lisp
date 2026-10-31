;;; precompact_handoff.lisp -- PreCompact: write the Tier 1 sidecar checkpoint, then maybe enrich it.
;;;
;;; Port of claude/hooks/precompact_handoff.py (HEAD), hook mode only. The rule the Python keeps:
;;; this hook must never fail or delay a compaction. Every step the host runs is best effort.
;;;
;;; WHAT THIS FILE DECIDES
;;;   - The text of the checkpoint (frontmatter, dirty-files section, the closing note).
;;;   - Whether the detached enrichment should be started after the checkpoint is written.
;;; WHAT THE HOST DOES
;;;   - Reads the hook JSON and the working directory. Works out REPO and TASK (path arithmetic
;;;     over ~/src/ops-worktrees, ~/ops and the nearest .git), runs git for the branch, HEAD and
;;;     the dirty list, and builds the fenced DIRTY-SECTION text.
;;;   - Makes the state directory, writes the file atomically (temp file beside it, then
;;;     os.replace), and starts the enricher in its own session with output to enrich.log.
;;;   - The --resolve <dir> mode is also the host's: it prints REPO/TASK and never reaches
;;;     this file.
;;;   - Any failure of a host step stops the hook without an error, as the Python does.
;;;
;;; HOST CONTRACT
;;;   1. Before evaluating this file the shim sets the global value of *FACTS* to an alist of
;;;      (SYMBOL . VALUE). DEFVAR below only sets *FACTS* when it is still unbound.
;;;   2. Facts this file reads (all strings unless noted):
;;;        TRIGGER          hook JSON trigger, or "unknown"
;;;        UPDATED-AT       local time with offset, as %Y-%m-%dT%H:%M:%S%z
;;;        SESSION-ID       hook JSON session_id, or "unknown"
;;;        TRANSCRIPT-PATH  hook JSON transcript_path, or ""
;;;        REPO             the repo component from resolve_workspace
;;;        TASK             the workspace component from resolve_workspace
;;;        BRANCH           git branch --show-current, or "(not a git tree)"
;;;        HEAD-SHA         git rev-parse HEAD, or ""
;;;        DIRTY-SECTION    the fenced dirty list (the first 40 lines), or the word clean
;;;        NL               one newline character
;;;        ENRICH-OFF       T when HANDOFF_ENRICH is "0"
;;;        ENRICHER-READY   T when the handoff-tools venv python and enrich_checkpoint.py exist
;;;        TRANSCRIPT-SET   T when transcript_path is non-empty
;;;   3. The last form, (HOOK-MAIN), returns a plan, not JSON. It is a tree
;;;        (obj (body (frag ITEM ...)) (enrich YES-or-NO))
;;;      The shim writes BODY as the sidecar when the state directory is usable, and starts the
;;;      enricher only when ENRICH is YES and the write succeeded. Exit status is always 0.
;;;
;;; QUIRKS WORKED AROUND
;;;   - The dialect has no string join. The body is a frag of literal lines and facts, with NL
;;;     facts between them. That also keeps the trailing newline the Python gets from join
;;;     with a final empty element: the last NL in the frag is that newline.
;;;   - The reader takes the character after a backslash literally, so "\n" would read as "n".
;;;     Newlines are only ever the NL fact.
;;;   - COND falls through to the last clause body when nothing matches. There is no COND in
;;;     the checkpoint text; the one decision is an IF with both branches given.
;;;   - Dynamic scope: FACT reads *FACTS* from any depth of the call.
;;;
;;; THE ENRICHMENT RULE (same as the Python)
;;;   Start the enricher only when HANDOFF_ENRICH is not "0", the venv python and
;;;   enrich_checkpoint.py both exist, and the transcript path is non-empty.

(defvar *facts* nil)

(defun fact (key)
  "The value recorded for KEY in *FACTS*, or NIL when there is none."
  (cdr (assoc key *facts*)))

(defun should-enrich ()
  "T when the detached enrichment may start. Checked only after the sidecar was written."
  (and (not (fact 'enrich-off))
       (fact 'enricher-ready)
       (fact 'transcript-set)))

(defun checkpoint-body ()
  "The sidecar text as a frag. Same lines, in the same order, as the Python list joined by newlines."
  '(frag "---" nl
         "schema_version: 1" nl
         "compacted: true" nl
         "trigger: " trigger nl
         "updated_at: " updated-at nl
         "session_id: " session-id nl
         "transcript_path: " transcript-path nl
         "repo: " repo nl
         "workspace: " task nl
         "branch: " branch nl
         "head_sha: " head-sha nl
         "---" nl
         "" nl
         "## Dirty files at compaction" nl
         "" nl
         dirty-section nl
         "" nl
         "Unplanned checkpoint written by precompact_handoff.py. Fold into" nl
         "SESSION_LOG.md Recent History on next owned write, then delete me." nl))

(defun hook-main ()
  "The plan for this compaction: the checkpoint text, and whether to enrich it afterwards."
  (list 'obj
        (list 'body (checkpoint-body))
        (list 'enrich (if (should-enrich) 'yes 'no))))

;; The shim evaluates the file and reads the value of this last form.
(hook-main)
