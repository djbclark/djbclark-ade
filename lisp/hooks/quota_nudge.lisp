;;; quota_nudge.lisp -- UserPromptSubmit: tell a session what the quota guard's level means for it.
;;;
;;; Port of claude/hooks/quota_nudge.py (HEAD). Three kinds of line, each printed at most once
;;; per session (and once per day for the frontier allowance):
;;;   - the guard's level advice, when the level rises (a drop is remembered too);
;;;   - the "aiuse unreadable" episode line, when the guard reports a real, current episode;
;;;   - the "[gates]" line: an active gate profile, or else the standing frontier allowance.
;;; The Python never fails: every error is swallowed, and the hook exits 0.
;;;
;;; WHAT THIS FILE DECIDES
;;;   Which lines are due, in which order, and which once-per-session memories to update. The
;;;   answer is a list of ITEMs in print order; a LINE item is printed, a MARK item says what
;;;   the memory must now remember.
;;; WHAT THE HOST DOES
;;;   Reads the stdin JSON and the guard state file, takes the nudge lock (flock, LOCK_RETRIES
;;;   by LOCK_WAIT_S, non-blocking; if the lock is not held the host prints nothing and changes
;;;   nothing, and this file is not consulted), reads and writes ~/.claude/state/quota-nudges.json
;;;   atomically, trims it to its last 200 sessions, and turns every timestamp into integer
;;;   seconds. It also formats the profile end time for the America/New_York zone, and
;;;   sanitises the profile name (ASCII only, else "gate"). It does not run aiuse; nothing here
;;;   needs a network or a subprocess.
;;;
;;; HOST CONTRACT
;;;   1. Before evaluating this file the shim sets the global value of *FACTS* to an alist of
;;;      (SYMBOL . VALUE). DEFVAR below only sets *FACTS* when it is still unbound.
;;;   2. Facts this file reads. A fact the host cannot compute is NIL.
;;;        STATE-AGE             integer seconds from checked_at to now (negative is allowed),
;;;                              NIL when checked_at does not parse
;;;        LEVEL-RANK            0 ok, 1 watch, 2 tight, 3 critical; NIL when the level is not one of these
;;;        LEVEL-NAME            the level's name as a string
;;;        SHOWN-RANK            the rank remembered for this session (0 when none or unknown)
;;;        ADVICE                the advice string, NIL unless it is a non-blank string
;;;        UNREADABLE-PINGED     T when last_unreadable_pinged_at is truthy
;;;        UNREADABLE-SINCE      the since stamp, formatted %Y-%m-%dT%H:%M:%SZ, NIL when unparsed
;;;        UNREADABLE-LAST-AGE   integer seconds from last_unreadable_at to now, NIL when unparsed
;;;        UNREADABLE-SEEN       T when the remembered unreadable stamp equals UNREADABLE-SINCE
;;;        FRONTIER-JUDGED       T when frontier_allowance.judged is exactly true
;;;        FRONTIER-CALLS        frontier_allowance.agent_calls_per_day as an integer (not a
;;;                              boolean), NIL when it is anything else
;;;        PROFILE-BROKEN        T when the New York zone could not be loaded (the Python then
;;;                              says nothing about profiles or the frontier line at all)
;;;        PROFILE-NAME          the sanitised profile name, when a profile is present
;;;        PROFILE-REMAINING     integer seconds from now until profile.until, NIL when there
;;;                              is no profile or its until does not parse
;;;        PROFILE-WHEN          the end time as "Mon Jan 2 3:04 PM EST", NIL without a profile
;;;        PROFILE-SHOWN         T when the remembered profile stamp equals until|today
;;;        FRONTIER-SHOWN-TODAY  T when the remembered frontier day equals today
;;;   3. The last form, (HOOK-MAIN), returns (obj (items (arr ITEM ...))). An ITEM is
;;;        (line FRAG)   print FRAG as one line, then a newline
;;;        (mark KEY)    update the memory: LEVEL stores LEVEL-NAME under the session id;
;;;                      UNREADABLE stores UNREADABLE-SINCE under "<session>#unreadable";
;;;                      FRONTIER stores today under "<session>#frontier"; PROFILE stores
;;;                      "<until>|<today>" under "<session>#profile"
;;;      A FRAG is a list (frag ITEM ...) whose items are strings, integers, or nested frags.
;;;      The exit status is always 0.
;;;
;;; QUIRKS WORKED AROUND
;;;   - No strings are compared, joined or formatted here. The host supplies the stamps and
;;;     the sentences' variable parts as values, and the Lisp builds each line as a frag.
;;;   - The reader takes the character after a backslash literally, so the \" inside the
;;;     frontier sentence reads as a plain double quote. That one happens to be what the
;;;     Python prints. Newlines are not needed: each LINE is its own item.
;;;   - COND falls through to its last clause body when nothing matches. Every COND ends in
;;;     an explicit T clause.
;;;   - There are no floats, so every age is an integer number of seconds.
;;;   - Dynamic scope: FACT reads *FACTS* from any depth of the call. APPEND copies its
;;;     arguments, so the ITEM lists can be joined freely.
;;;
;;; THE CONSTANTS (the Python's module constants)

(defvar *facts* nil)
(defvar frontier1 "Fable 5.1")
(defvar judgment "Opus 5.5")
(defvar max-age-seconds 7200)
(defvar guard-state-max-age-s 1800)

(defun fact (key)
  "The value recorded for KEY in *FACTS*, or NIL when there is none."
  (cdr (assoc key *facts*)))

(defun emit (frag)
  "A LINE item: FRAG is printed as one line."
  (list 'line frag))

(defun mark (key)
  "A MARK item: the memory named KEY must now remember what the host would store for it."
  (list 'mark key))

(defun state-fresh-p ()
  "The guard state is usable: checked_at parses and is no older than MAX_AGE_SECONDS.
A state that is only a little in the future is still usable, as in the Python."
  (let ((age (fact 'state-age)))
    (and age (<= age max-age-seconds))))

(defun cap-text (calls)
  "The Agent-tool cap clause of the frontier sentence."
  (if (> calls 0)
      (list 'frag "at most " calls " Agent-tool calls today")
      "no Agent-tool call without asking"))

(defun frontier-text ()
  "The frontier sentence as a frag, or NIL unless the guard state allows judged use right now.
The freshness bound here is 30 minutes and starts 60 seconds in the future, not the 2 hours
the state itself is allowed."
  (let ((age (fact 'state-age))
        (calls (fact 'frontier-calls)))
    (if (and age
             (>= age -60)
             (<= age guard-state-max-age-s)
             (fact 'frontier-judged)
             calls)
        (list 'frag frontier1
              " (frontier) is allowed where you judge it significantly better than "
              judgment
              "; give the reason in one line (acp-dispatch --kind frontier --frontier-reason \"...\"; Agent tool: a \"frontier-reason: ...\" prompt line), "
              (cap-text calls))
        nil)))

(defun level-items ()
  "The level advice, when the level rose above the remembered one, and the memory update."
  (let ((rank (fact 'level-rank)))
    (if (not rank)
        nil
        (append
         (if (and (> rank 0) (> rank (fact 'shown-rank)) (fact 'advice))
             (list (emit (list 'frag "[quota-guard " (fact 'level-name) "] " (fact 'advice))))
             nil)
         (if (= rank (fact 'shown-rank))
             nil
             (list (mark 'level)))))))

(defun unreadable-items ()
  "The unreadable episode line: the guard pinged, the episode is still current, and this stamp is new."
  (if (and (fact 'unreadable-pinged)
           (fact 'unreadable-since)
           (fact 'unreadable-last-age)
           (<= (fact 'unreadable-last-age) max-age-seconds)
           (not (fact 'unreadable-seen)))
      (list (emit (list 'frag "[quota-guard unreadable] aiuse unreadable since "
                        (fact 'unreadable-since)
                        ": check `aiuse --available --json`"))
            (mark 'unreadable))
      nil))

(defun standing-items ()
  "No profile is in force: the standing frontier allowance speaks once a day, if it is allowed."
  (let ((frontier (frontier-text)))
    (cond ((not frontier) nil)
          ((fact 'frontier-shown-today) nil)
          (t (list (emit (list 'frag "[gates] frontier allowance: " frontier "."))
                   (mark 'frontier))))))

(defun profile-active-items (frontier)
  "A profile is active. Say so once per profile end and per day. With the frontier allowance
allowed as well, say that too."
  (cond ((fact 'profile-shown) nil)
        (frontier
         (list (emit (list 'frag "[gates] " (fact 'profile-name) " profile active until "
                           (fact 'profile-when) ": " frontier
                           ". gate-profile clear restores normal routing."))
               (mark 'profile)))
        (t
         (list (emit (list 'frag "[gates] " (fact 'profile-name) " profile active until "
                           (fact 'profile-when)
                           "; gate-profile clear restores normal routing"))
               (mark 'profile)))))

(defun profile-items ()
  "The [gates] line. A broken zone loader silences this whole part, as the Python does."
  (let ((remaining (fact 'profile-remaining)))
    (cond ((fact 'profile-broken) nil)
          ((or (not remaining) (<= remaining 0)) (standing-items))
          (t (profile-active-items (frontier-text))))))

(defun hook-main ()
  "All the items for this prompt, in print order. The unreadable line comes first and is
checked even when the state is stale; the level and profile lines need a fresh state."
  (let ((items (append (unreadable-items)
                       (if (state-fresh-p)
                           (append (level-items) (profile-items))
                           nil))))
    (list 'obj (list 'items (cons 'arr items)))))

;; The shim evaluates the file and reads the value of this last form.
(hook-main)
