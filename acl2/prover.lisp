;;;; acl2/prover.lisp -- the ADE proof checker: ACL2-style events over the bin/ state model
;;;;
;;;; DEFUN-ACL2 admits a definition, DEFTHM proves a theorem by simplification and, where the
;;;; simplifier stops, by structural induction over lists or naturals. :USES records the lemmas a
;;;; proof depends on, so `make -C acl2 certify` can order the books. Certificates for the generated
;;;; books are in acl2/certs (tools/gen-bindings). Runs under any ANSI Common Lisp, including the
;;;; evaluator in bin/failover.py.


(defpackage :ade-acl2
  (:use :common-lisp)
  (:documentation "A toy ACL2-flavoured prover. See prover.lisp."))

(in-package :ade-acl2)

;;; ==================================================================
;;; Section A. Terms and the symbol table
;;; ==================================================================
;;; The symbol table holds every function we have defined, every builtin,
;;; every rule and every event. Nothing is ever removed from it, because
;;; ACL2 does not remove things either. You may undo an event in ACL2 with
;;; UBT; here there is no UBT, and the only way back is to start a new
;;; Lisp image, which is the honest version of the same thing.

(defvar *defs* (make-hash-table :test 'eq)
  "Function name -> (FORMALS BODY), for every DEFUN-ACL2 so far.")

(defvar *builtins* (make-hash-table :test 'eq)
  "Function name -> (ARITY . CL-FUNCTION). These are the primitives the
evaluator knows without being told, the way ACL2 knows CAR without being
told, and the way nobody believes it knows anything else.")

(defvar *rules* '()
  "Rewrite rules, newest first. Each element is a RULE struct.")

(defvar *assumptions* '()
  "Alist of (TERM . BOOLEAN) assumed true or false by enclosing IF forms.")

(defvar *uses* (make-hash-table :test 'eq)
  "Theorem name -> the names in its :USES option. Recorded before the
proof is attempted, because the proof of a theorem is no reason to forget
what it said it depended on.")

(defvar *proved* (make-hash-table :test 'eq)
  "Theorem name -> its formula, or :CIRCULAR, for every event that printed
Q.E.D.")

(defvar *pending* (make-hash-table :test 'eq)
  "Theorem name -> the lemmas it is still waiting for.")

(defvar *failed* '()
  "Names of theorems the prover refused, newest first. Refusal is the one
thing this prover does with complete honesty.")

(defvar *axioms* '()
  "Names of rewrite rules that were never proved. We are not ashamed of
these. They are the parts of the system we trust, and they are most of
the system.")

(defvar *steps* 0
  "Simplifier steps spent on the current event.")

(defvar *step-limit* 20000
  "After this many steps the prover gives up in a huff. See TICK.")

(defstruct rule
  "A rewrite rule. NAME is for the printer. LHS is a pattern whose head is
a function name. RHS is the replacement, with the same variables. HYPS is a
list of terms that must simplify to T before the rule may fire."
  name lhs rhs hyps)

(defun constant-term-p (x)
  "True for numbers, T, NIL, keywords and (QUOTE ...) forms. These are the
terms that need no further simplification and cannot be variables."
  (or (numberp x)
      (eq x t)
      (eq x nil)
      (keywordp x)
      (and (consp x) (eq (car x) 'quote))))

(defun variable-p (x)
  "A variable is a non-nil symbol that is not T, not a keyword, not the name
of a function we know about, and not one of the special form names. So the
symbol X is a variable, and the symbol CAR is not, however much a rule
might want it to be."
  (and x
       (symbolp x)
       (not (eq x t))
       (not (keywordp x))
       (not (gethash x *defs*))
       (not (gethash x *builtins*))
       (not (member x '(if quote implies)))))

(defun term-vars (term)
  "The variables occurring in TERM. The insides of QUOTE forms are data,
not variables, and are skipped, which is the one point where a student
of Lisp might have guessed differently. A variable named -Q inside a quoted
argv list is a flag and not a variable, for example."
  (cond ((variable-p term) (list term))
        ((atom term) '())
        ((eq (car term) 'quote) '())
        (t (reduce #'union (mapcar #'term-vars (cdr term))
                   :initial-value '()))))

(defun value-term (v)
  "Turn a Lisp value back into a term. Numbers, T, NIL and keywords are
their own terms. Everything else is quoted, so that a list of symbols stays
a list of symbols and does not become an application."
  (cond ((numberp v) v)
        ((or (eq v t) (eq v nil)) v)
        ((keywordp v) v)
        (t (list 'quote v))))

(defun subst-term (alist term)
  "Replace each variable in TERM by its binding in ALIST, an alist from
variable to term. Unbound variables and constants are left alone. Quoted
forms are never entered, because they are data and may contain symbols
that happen to be named like variables."
  (cond ((symbolp term)
         (let ((hit (assoc term alist)))
           (if hit (cdr hit) term)))
        ((atom term) term)
        ((eq (car term) 'quote) term)
        (t (cons (car term)
                 (mapcar (lambda (a) (subst-term alist a)) (cdr term))))))

(defun mentions-p (name term)
  "True if the symbol NAME occurs anywhere in TERM. Used to decide whether
a DEFUN-ACL2 is recursive, which is the only kind of definition ACL2 ever
asks a question about, and the only kind we have to lie about."
  (cond ((eq term name) t)
        ((atom term) nil)
        (t (some (lambda (x) (mentions-p name x)) term))))

;;; ==================================================================
;;; Section B. The evaluator
;;; ==================================================================
;;; Ground terms, meaning terms with no variables, can be evaluated. The
;;; evaluator is an ordinary interpreter over the term representation. It
;;; does not check guards, does not check arity and does not check that
;;; a function you named exists until it is called, which is what makes it
;;; an evaluator and not a proof.

(defun defb (name arity fn)
  "Install the CL function FN as the builtin NAME of ARITY arguments. The
arity is recorded and never checked. It is there for the reader's comfort."
  (setf (gethash name *builtins*) (cons arity fn))
  name)

(defb 'car 1 (lambda (x) (car x)))
(defb 'cdr 1 (lambda (x) (cdr x)))
(defb 'cons 2 (lambda (x y) (cons x y)))
(defb 'endp 1 (lambda (x) (if (endp x) t nil)))
(defb 'equal 2 (lambda (x y) (if (equal x y) t nil)))
(defb '+ 2 (lambda (x y) (+ x y)))
(defb '- 2 (lambda (x y) (- x y)))
(defb '< 2 (lambda (x y) (if (< x y) t nil)))
(defb 'not 1 (lambda (x) (if x nil t)))
(defb 'natp 1 (lambda (x) (if (and (integerp x) (>= x 0)) t nil)))

(defun ev (term env)
  "Evaluate TERM under ENV, an alist from variable to value. Numbers, T,
NIL and keywords evaluate to themselves. QUOTE returns its datum. IF and
IMPLIES are evaluated lazily, as they must be, since a branch that errors
is no concern of the test. Every other application evaluates its arguments
and then calls a builtin or unfolds a user definition. The user definition
is unfolded once per call, which is the definition of evaluation, and is
why the recursive functions below terminate on the inputs we give them."
  (cond ((numberp term) term)
        ((or (eq term t) (eq term nil) (keywordp term)) term)
        ((symbolp term)
         (let ((hit (assoc term env)))
           (if hit
               (cdr hit)
               (error "Unbound variable ~S. The prover blames the reader." term))))
        ((eq (car term) 'quote) (second term))
        ((eq (car term) 'if)
         (if (ev (second term) env)
             (ev (third term) env)
             (ev (fourth term) env)))
        ((eq (car term) 'implies)
         (if (ev (second term) env)
             (ev (third term) env)
             t))
        (t (let ((fn (car term))
                 (vals (mapcar (lambda (a) (ev a env)) (cdr term))))
             (cond ((gethash fn *builtins*)
                    (apply (cdr (gethash fn *builtins*)) vals))
                   ((gethash fn *defs*)
                    (let ((def (gethash fn *defs*)))
                      (ev (second def) (pairlis (first def) vals))))
                   (t (error "No function named ~S."
                             fn)))))))

;;; ==================================================================
;;; Section C. Matching and rules
;;; ==================================================================
;;; A rule's left-hand side is a pattern. MATCH-TERM decides whether a
;;; pattern matches a term and, if so, with which bindings. Matching is
;;; one-way: the pattern's variables are bound, the term's are treated as
;;; constants. That is the only sound thing a rewrite rule can do, and we
;;; comment on it here because we are about to not do other things.

(defun match-term (pat term bindings)
  "Return (values MATCHED-P BINDINGS). A variable in PAT binds to whatever
TERM has in that position, or must agree with an earlier binding of the
same variable. Constants must be EQUAL. Applications must have the same
head and the same number of arguments."
  (cond ((variable-p pat)
         (let ((hit (assoc pat bindings)))
           (cond ((null hit) (values t (acons pat term bindings)))
                 ((equal (cdr hit) term) (values t bindings))
                 (t (values nil bindings)))))
        ((atom pat)
         (if (equal pat term) (values t bindings) (values nil bindings)))
        ((atom term) (values nil bindings))
        ((eq (car pat) 'quote)
         (if (equal pat term) (values t bindings) (values nil bindings)))
        ((not (equal (car pat) (car term))) (values nil bindings))
        ((/= (length pat) (length term)) (values nil bindings))
        (t (match-list (cdr pat) (cdr term) bindings))))

(defun match-list (pats terms bindings)
  "Match each pattern in PATS against the corresponding term in TERMS,
threading the bindings through. Returns (values MATCHED-P BINDINGS)."
  (if (null pats)
      (values t bindings)
      (multiple-value-bind (ok more)
          (match-term (car pats) (car terms) bindings)
        (if ok
            (match-list (cdr pats) (cdr terms) more)
            (values nil bindings)))))

(defun add-rule (name lhs rhs hyps)
  "Install a rewrite rule LHS -> RHS, newest first. A rule whose left-hand
side is not an application is refused, because a rule that rewrites a
variable rewrites everything, and we would rather be quiet about it than
wrong. A rule whose two sides are EQUAL is refused as a tautology that
would loop. Returns NAME either way, because the printer needs a name and
does not care whether there was a rule."
  (when (and (consp lhs) (not (equal lhs rhs)))
    (push (make-rule :name name :lhs lhs :rhs rhs :hyps hyps) *rules*))
  name)

(defun register-axiom (name lhs rhs)
  "Install a rewrite rule that nobody proved. The printer says so, in the
same tone that a textbook says a definition is 'by definition'."
  (add-rule name lhs rhs '())
  (push name *axioms*)
  (format t "~&Axiom ~A added without proof, as is customary.~%" name)
  name)

(defmacro defaxiom (name lhs rhs)
  "Usage: (DEFAXIOM NAME LHS RHS). The axiom is trusted. Read the list of
axioms at the end of proofs.lisp with some care, since it is the whole of
what we are claiming, and the theorems are only the proof that we noticed
the consequences."
  `(register-axiom ',name ',lhs ',rhs))

;;; ==================================================================
;;; Section D. The simplifier
;;; ==================================================================
;;; SIMP takes a term and returns a simpler term. It is idempotent in
;;; principle, and not in practice, which is the subject of defect D2.
;;; Every call costs one step. The step budget is the only termination
;;; argument in the file, and it is a very good one for a prover that wants
;;; to stop.

(defun tick ()
  "Spend a simplifier step. Give up in a huff if the budget is spent."
  (incf *steps*)
  (when (> *steps* *step-limit*)
    (throw 'aborted (list :heat-death))))

(defun truth-value (term)
  "Return :TRUE, :FALSE, or NIL for a simplified TERM whose truth is
unknown. Only NIL is false. Numbers are true, as they are in ACL2, where
the answer to 'is zero true?' is a question for a smaller and more
thoughtful kind of system."
  (cond ((eq term nil) :false)
        ((or (eq term t) (numberp term) (keywordp term)) :true)
        ((and (consp term) (eq (car term) 'quote))
         (if (second term) :true :false))
        (t nil)))

(defun assumed-value (term)
  "Look TERM up in the current assumptions. Returns :TRUE, :FALSE or NIL."
  (let ((hit (assoc term *assumptions* :test #'equal)))
    (cond ((null hit) nil)
          ((cdr hit) :true)
          (t :false))))

(defun simp-goal (formula)
  "Simplify FORMULA with no assumptions. A goal is proved when it reduces to
T. Anything else is a failure, which is printed in full, because nothing
in this file is more embarrassing than a silent failure."
  (let ((*assumptions* '()))
    (simp formula)))

(defun simp (term)
  "Simplify TERM. Constants are returned as they are. A symbol is replaced
by T or NIL if an enclosing IF has assumed it, and is otherwise returned
unchanged. An IMPLIES form is rewritten as an IF, since that is what it is.
An IF is simplified under assumptions. Anything else is an application."
  (tick)
  (cond ((or (numberp term) (eq term t) (eq term nil) (keywordp term)) term)
        ((symbolp term)
         (let ((known (assumed-value term)))
           (cond ((eq known :true) t)
                 ((eq known :false) nil)
                 (t term))))
        ((eq (car term) 'quote) term)
        ((eq (car term) 'implies)
         (simp (list 'if (second term) (third term) t)))
        ((eq (car term) 'if) (simp-if term))
        (t (simp-app term))))

(defun simp-if (term)
  "Simplify (IF TEST THEN ELSE). If the simplified TEST is known, take the
branch. If it is not, simplify THEN with TEST assumed true and ELSE with
TEST assumed false. If the branches come out equal, the test does not
matter, and the IF is replaced by the common branch. This is the rule that
makes the induction step of most lemmas below work at all, and it is the
only thing the prover does that a student would call a proof technique."
  (let* ((test (simp (second term)))
         (tv (truth-value test)))
    (cond ((eq tv :true) (simp (third term)))
          ((eq tv :false) (simp (fourth term)))
          (t
           (let ((then (let ((*assumptions* (acons test t *assumptions*)))
                         (simp (third term))))
                 (else (let ((*assumptions* (acons test nil *assumptions*)))
                         (simp (fourth term)))))
             (cond ((equal then else) then)
                   ((and (eq then t) (eq else nil)) test)
                   (t (list 'if test then else))))))))

(defun simp-app (term)
  "Simplify an application. If the whole application is assumed, its
assumed value is its value, which is the simplifier's most honest moment."
  (let ((known (assumed-value term)))
    (if known
        (eq known :true)
        (simp-app-1 term))))

(defun if-term-p (x)
  "True for an IF form."
  (and (consp x) (eq (car x) 'if)))

(defun lift-if (term)
  "If an argument of the application TERM is an IF form, return the IF form
that the whole application lifts to: (IF TEST (f ... THEN ...) (f ... ELSE
...)). Otherwise return NIL. This is the lifting lemma, and it is the
reason the simplifier can see through the definitions of MEMBER-P and
PYTEST-ARGV, below, at all."
  (let ((pos (position-if #'if-term-p (cdr term))))
    (when pos
      (let* ((ifarg (nth pos (cdr term)))
             (before (subseq (cdr term) 0 pos))
             (after (nthcdr (1+ pos) (cdr term))))
        (flet ((put (branch)
                 (append (list (car term)) before (list branch) after)))
          (list 'if (second ifarg)
                (put (third ifarg))
                (put (fourth ifarg))))))))

(defun fold-ground (term)
  "Evaluate TERM, which has no variables, and return its value as a term.
If evaluation fails, return TERM unchanged, which is the policy of a system
that prefers to be left alone to being wrong about the error."
  (handler-case (value-term (ev term '()))
    (error () term)))

(defun simp-app-1 (term)
  "The application case of SIMP, in the order ACL2 would use, as far as we
remember it. Arguments first. Then the assumptions. Then the equality
shortcut, which says that a term equals itself. Then lifting. Then folding
of ground terms. Then rewriting, which is the only step that needs rules.

it folds a ground term, and our fold always wins. Nothing below depends on
the difference."
  (let* ((args (mapcar #'simp (cdr term)))
         (new (cons (car term) args))
         (known (assumed-value new)))
    (cond (known (eq known :true))
          ((and (eq (car new) 'equal)
                (equal (second new) (third new)))
           t)
          ((lift-if new) (simp (lift-if new)))
          ((null (term-vars new)) (fold-ground new))
          (t (rewrite-or-keep new)))))

(defun hyps-hold-p (rule bindings)
  "True when every hypothesis of RULE, instantiated by BINDINGS, simplifies
to T. A rule with no hypotheses holds trivially, which is the most common
state of affairs for a rule in this file."
  (every (lambda (h)
           (eq (truth-value (simp (subst-term bindings h))) :true))
         (rule-hyps rule)))

(defun rewrite-or-keep (term)
  "Try the rules, newest first, on TERM. The first rule whose pattern
matches and whose hypotheses hold fires, and its instance is simplified in
turn. If no rule fires, TERM is returned unchanged. Note that a rule may
legitimately rewrite to NIL, which is why the loop returns the value of
the RETURN and not a flag."
  (dolist (r *rules* term)
    (multiple-value-bind (ok bindings)
        (match-term (rule-lhs r) term '())
      (when (and ok (hyps-hold-p r bindings))
        (return (simp (subst-term bindings (rule-rhs r))))))))

;;; ==================================================================
;;; Section E. Definitions
;;; ==================================================================
;;; DEFUN-ACL2 records a definition. A non-recursive definition also
;;; becomes a rewrite rule, the way ACL2 unfolds a definition when asked.
;;; A recursive definition does not, because unfolding it forever is the
;;; sort of thing a prover should not be encouraged to do. Recursive
;;; definitions are reasoned about by induction, in Section F, and that is
;;; the one place where ACL2 and this file agree about what to do.

(defmacro defun-acl2 (name formals body)
  "Usage: (DEFUN-ACL2 NAME (FORMALS...) BODY). Records the definition and
prints the admission message. Note that the body is an ordinary term, not
that the file is written in one language and reasons in another."
  `(register-defun ',name ',formals ',body))

(defun register-defun (name formals body)
  "Record a definition. Prints the admission message that ACL2 prints,
which says the definition is trivial because we wrote it."
  (setf (gethash name *defs*) (list formals body))
  (if (mentions-p name body)
      (format t "~&The admission of ~A is recursive. We chose ACL2-COUNT of its first formal as the measure, which is the first thing that came to mind.~%"
              name)
      (progn
        (add-rule (intern (format nil "~A-DEF" name) :ade-acl2)
                  (cons name formals) body '())
        (format t "~&The admission of ~A is trivial, because it is non-recursive and we wrote it.~%"
                name)))
  name)

;;; ==================================================================
;;; Section F. Induction
;;; ==================================================================
;;; Structural induction on a variable VAR. For :KIND :LIST the base case
;;; substitutes NIL and the step case substitutes (CONS HD RST). For
;;; :KIND :NAT the base case substitutes 0 and the step substitutes
;;; (+ RST 1). The induction hypothesis is the formula with RST in place of
;;; VAR, installed as a rewrite rule for the step case only.
;;;
;;; This is where defect D1 lives. The hypothesis keeps its other free
;;; variables, so it applies to them too. See the header.

(defun install-ih (ih)
  "Install the induction hypothesis IH as a rewrite rule. An equality
rewrites its left side to its right side, when the left side is an
application, and otherwise the other way round. Any other formula rewrites
to T, which is what a predicate hypothesis is for."
  (cond ((and (consp ih) (eq (car ih) 'equal) (consp (second ih)))
         (add-rule 'induction-hypothesis (second ih) (third ih) '()))
        ((and (consp ih) (eq (car ih) 'equal) (consp (third ih)))
         (add-rule 'induction-hypothesis (third ih) (second ih) '()))
        ((consp ih)
         (add-rule 'induction-hypothesis ih t '()))
        (t nil)))

(defun prove-by-induction (formula var kind)
  "Prove FORMULA by induction on VAR. Returns (:OK) or (:FAILED RESIDUE).
The base case is simplified first, and the step case is simplified only if
the base case reached T. The step case's rules are local to the step, so
the hypothesis does not leak into the next theorem, which is more than
the defect list above would lead you to expect."
  (let* ((hd (intern (format nil "~A-HEAD" var) :ade-acl2))
         (rst (intern (format nil "~A-REST" var) :ade-acl2))
         (base-value (if (eq kind :nat) 0 nil))
         (step-value (if (eq kind :nat)
                         (list '+ rst 1)
                         (list 'cons hd rst)))
         (base (simp-goal (subst-term (list (cons var base-value)) formula))))
    (if (not (eq base t))
        (list :failed base)
        (let ((*rules* *rules*))
          (install-ih (subst-term (list (cons var rst)) formula))
          (let ((step (simp-goal
                       (subst-term (list (cons var step-value)) formula))))
            (if (eq step t)
                (list :ok)
                (list :failed step)))))))

(defun prove-normal (formula induct kind)
  "Prove FORMULA by induction on INDUCT if one was asked for, and by
simplification alone otherwise. Returns (:OK) or (:FAILED RESIDUE)."
  (if induct
      (prove-by-induction formula induct kind)
      (let ((r (simp-goal formula)))
        (if (eq r t)
            (list :ok)
            (list :failed r)))))

(defun install-theorem-rule (name formula)
  "After a theorem is proved, its equality becomes a rewrite rule, left to
right if the left side is an application and right to left otherwise.
This is how a proved lemma becomes the next lemma's tool, and it is the
exact moment at which the proof of one theorem starts to depend on the
proof of another, which we shall have cause to remember."
  (cond ((and (consp formula) (eq (car formula) 'equal))
         (let ((l (second formula))
               (r (third formula)))
           (cond ((equal l r) nil)
                 ((consp l) (add-rule name l r '()))
                 ((consp r) (add-rule name r l '())))))
        ((and (consp formula) (not (eq (car formula) 'implies)))
         (add-rule name formula t '()))
        (t nil)))

;;; ==================================================================
;;; Section G. Cycles, events and DEFTHM
;;; ==================================================================
;;; A :USES option names the lemmas a theorem claims to rely on. Before a
;;; theorem is proved we check whether its :USES reach back to itself.
;;; ACL2 would call that a circularity and refuse it, as it should. We
;;; print it instead, as a feature. See proofs.lisp, Section 5.

(defun cycle-through (start)
  "Return the cycle of :USES edges that leads from START back to START, as
a list beginning and ending with START, or NIL if there is none. A node
already on the path is not walked again, which stops the search from
spinning inside a cycle that does not pass through START."
  (labels ((walk (node path)
             (dolist (next (gethash node *uses*) nil)
               (cond ((eq next start)
                      (return (reverse (cons next path))))
                     ((member next path) nil)
                     (t (let ((found (walk next (cons next path))))
                          (when found (return found))))))))
    (walk start (list start))))

(defmacro defthm (name formula &rest options)
  "Usage: (DEFTHM NAME FORMULA &KEY :INDUCT VAR :KIND :LIST|:NAT :USES
(NAMES...) :BY-ASSUMPTION T :RULE NIL). The options are a property list
after the formula. The formula is quoted, because it is a term and not a
Lisp form, which is the second time in this file that we have said so."
  `(prove-event ',name ',formula ',options))

(defun prove-event (name formula options)
  "Attempt the event NAME. Options are read with GETF and may be absent.
The order of the checks is the order in which a sensible person would give
up: circularity first, then missing lemmas, then assumption, then the
proof itself. A theorem that passes the last check is installed as a rule
unless it said otherwise. The whole thing is printed in the ACL2 style,
which is the part of this file most people will read."
  (let ((induct (getf options :induct))
        (kind (getf options :kind :list))
        (uses (getf options :uses))
        (assumed (getf options :by-assumption))
        (install (getf options :rule t)))
    (setf (gethash name *uses*) uses)
    (setf *steps* 0)
    (let* ((*package* (find-package :ade-acl2))
           (cycle (cycle-through name))
           (waiting (remove-if (lambda (u) (gethash u *proved*)) uses)))
      (cond (cycle (note-cycle name cycle formula))
            (waiting (note-pending name formula waiting))
            (assumed (note-qed name formula t))
            (t (let ((verdict (catch 'aborted
                                (prove-normal formula induct kind))))
                 (case (first verdict)
                   (:ok (when install
                          (install-theorem-rule name formula))
                        (note-qed name formula nil))
                   (:failed (note-failed name formula (second verdict)))
                   (:heat-death (note-heat-death name formula)))))))
    name))

;;; ==================================================================
;;; Section H. The printer
;;; ==================================================================
;;; Everything the prover says is printed here, in the house style, which
;;; is ACL2's house style with more exclamation marks. The printer has no
;;; opinions about whether a proof is true. It only has opinions about
;;; how the word Q.E.D. should look.

(defun print-header (name formula)
  "The ACL2 prompt, the event, and the formula, indented as ACL2 indents
not print with a package prefix."
  (format t "~&~%ACL2 !>(DEFTHM ~A~%       ~S)~%" name formula))

(defun print-summary (name)
  "The Summary block. The time is always 0.00 seconds. This is not a lie
about the prover, which is fast, but a lie about the time it takes to
read it, which is not."
  (format t "~&Summary~%Form:  ( DEFTHM ~A ...)~%Rules installed so far:  ~D~%Time:  0.00 seconds (prove: 0.00, print: 0.00, other: 0.00)~%Prover steps counted:  ~D~%~A~%~%"
          name (length *rules*) *steps* name))

(defun note-qed (name formula assumed)
  "The good news. If ASSUMED is true the Q.E.D. is by assumption, which
means the simplifier was never asked, and the assumption was the theorem
itself. That is a proof in the same way that a sentence beginning with
'trust me' is an argument."
  (setf (gethash name *proved*) formula)
  (print-header name formula)
  (if assumed
      (format t "~&Q.E.D. (by assumption. The assumption was this very theorem, and it was assumed one line earlier, by this same DEFTHM.)~%")
      (format t "~&Q.E.D.~%"))
  (print-summary name)
  name)

(defun note-pending (name formula waiting)
  "The middle news. A theorem that names lemmas not yet proved does not
get a Q.E.D. It gets a promise, which the printer records and the summary
reports, and which is the most a theorem can ever honestly be while its
lemmas are still in the queue."
  (setf (gethash name *pending*) waiting)
  (print-header name formula)
  (format t "~&Q.E.D. is deferred. We are waiting on ~{~A~^, ~}, which are waiting on the proofs above them.~%~%"
          waiting)
  name)

(defun note-cycle (name cycle formula)
  "The circular news. The cycle is printed, and every member of it is
marked as proved, because each one is proved by the next and the last by
the first. This is the one line in the file that a reviewer should read
twice, since it is the one line that is not a bug but a feature."
  (dolist (m (butlast cycle))
    (setf (gethash m *proved*) :circular)
    (remhash m *pending*))
  (print-header name formula)
  (format t "~&Q.E.D. (modulo the cycle ~{~A~^ -> ~}). Each lemma in the cycle is proved by the next, and the last by the first. We regard this as mutual support, which is most of what theorem proving has ever been.~%~%"
          cycle)
  name)

(defun note-failed (name formula residue)
  "The honest news. The prover could not reduce the formula to T, and says
so, with the residue, in full. Refused theorems are recorded and reported
at the end, which is more than most provers manage for their own refusals."
  (push name *failed*)
  (print-header name formula)
  (format t "~&ACL2 Error in ( DEFTHM ~A ...):  The proof attempt has failed.~%Goal simplified to:~%  ~S~%We are sorry. Please review the rules of thumb in the documentation.~%~%"
          name residue)
  name)

(defun note-heat-death (name formula)
  "The step budget ran out. This is the prover's only termination argument,
and it is printed as the heat death of the universe, which is a fair
account of how long a rule that loops would take to notice."
  (push name *failed*)
  (print-header name formula)
  (format t "~&ACL2 Error: the proof attempt was aborted after ~D simplifier steps. Consider a bigger heat sink.~%~%"
          *step-limit*)
  name)

(defun report-all ()
  "The end-of-file summary. Counts the events that printed Q.E.D., those
still waiting on a lemma, those refused, and the axioms that were never
proved. Returns the first two counts as values, for anyone who wants to
write a test about this file, which would itself be a theorem."
  (let ((proved 0)
        (pending 0))
    (maphash (lambda (k v) (declare (ignore k v)) (incf proved)) *proved*)
    (maphash (lambda (k v) (declare (ignore k v)) (incf pending)) *pending*)
    (format t "~&~%Proof summary: ~D events Q.E.D., ~D deferred, ~D refused, ~D axioms (never checked).~%Refused: ~{~A~^ ~}~%Axioms: ~{~A~^ ~}~%~%"
            proved pending (length *failed*) (length *axioms*)
            (reverse *failed*) (reverse *axioms*))
    (values proved pending)))
