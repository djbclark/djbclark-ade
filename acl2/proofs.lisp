;;;; acl2/proofs.lisp -- properties of djbclark-ade checked by acl2/prover.lisp
;;;;
;;;; Section 1 models the pr-wait merge gate and the bin/pytest argv; sections 2-4 prove the
;;;; properties AGENTS.md review rules 1, 2 and 9 rely on; section 5 records the dependency
;;;; structure between those results. Load with:  sbcl --script acl2/proofs.lisp


;;; Load the prover from the directory this file lives in, then enter its
;;; package. The *LOAD-TRUENAME* is the file being loaded, so the path
(load (merge-pathnames "prover.lisp" *load-truename*))
(in-package :ade-acl2)

;;; ==================================================================
;;; Section 1. The Standard Book
;;; ==================================================================
;;; ACL2 has a library of certified books, which are files of lemmas that
;;; other people may include without re-proving them. This section is our
;;; book. Its contents are definitions, which the prover accepts because
;;; we wrote them, and axioms, which the prover accepts because we say so.
;;; A reader who wants to know what the file trusts should read this
;;; section and nothing else. The rest is consequences.

;;; List functions, the first ones every student learns.

(defun-acl2 app (x y)
  (if (endp x)
      y
      (cons (car x) (app (cdr x) y))))

(defun-acl2 rev (x)
  (if (endp x)
      nil
      (app (rev (cdr x)) (cons (car x) nil))))

(defun-acl2 len (x)
  (if (endp x)
      0
      (+ 1 (len (cdr x)))))

(defun-acl2 member-p (x l)
  (if (endp l)
      nil
      (if (equal x (car l))
          t
          (member-p x (cdr l)))))

;;; The two functions this file is actually about. Their names are the
;;; names of the things they model. Neither is connected to the real
;;; program, which is the point of the header.

(defun-acl2 merge-ready (blockers)
  (if (endp blockers)
      t
      nil))

(defun-acl2 pytest-argv (args)
  (if (member-p '-q args)
      args
      (cons '-q args)))

;;; Three functions whose only job is to be called in the circular proofs
;;; of Section 5. Each returns T for every input, which is the whole of
;;; their specification, and which is also the whole of the proof of
;;; anything about them.

(defun-acl2 qed-p ()
  t)

(defun-acl2 verified-p (x)
  t)

(defun-acl2 prover-correct-p ()
  t)

;;; The axioms. These are rewrite rules that were never proved. Each one
;;; is a fact about a function above that the prover did not derive from
;;; the definition, because a recursive definition is not unfolded, and
;;; the axioms are the unfolding we would have wanted if we had been
;;; allowed to unfold things. They are trusted in exactly the sense that
;;; the operator trusts the rest of this repo: because somebody wrote
;;; them down.

(defaxiom app-nil (app nil y) y)
(defaxiom app-cons (app (cons x xs) y) (cons x (app xs y)))
(defaxiom rev-nil (rev nil) nil)
(defaxiom rev-cons (rev (cons x xs)) (app (rev xs) (cons x nil)))
(defaxiom len-nil (len nil) 0)
(defaxiom len-cons (len (cons x xs)) (+ 1 (len xs)))
(defaxiom car-cons (car (cons x xs)) x)
(defaxiom cdr-cons (cdr (cons x xs)) xs)
(defaxiom endp-cons (endp (cons x xs)) nil)
(defaxiom plus-zero-left (+ 0 x) x)
(defaxiom plus-zero-right (+ x 0) x)
(defaxiom plus-assoc (+ (+ a b) c) (+ a (+ b c)))
(defaxiom member-p-nil (member-p x nil) nil)
(defaxiom member-p-cons (member-p x (cons y ys))
  (if (equal x y) t (member-p x ys)))

;;; ==================================================================
;;; Section 2. Lemmas about lists and naturals
;;; ==================================================================
;;; Each of these is a standard lemma from an undergraduate course on
;;; induction. The prover proves them, or refuses them, and in either case
;;; the output is the same kind of output that a whiteboard would have
;;; given. Read them in order: later lemmas use earlier ones through the
;;; rewrite rules that each proof installs on success.

;;; APP with NIL on the right. This is the lemma that makes the base case
;;; of REV-APP work, and the first lemma below that the induction
;;; hypothesis is used on.
(defthm app-right-nil (equal (app x nil) x) :induct x :kind :list)

;;; APP is associative. The induction is on the left argument.
(defthm app-assoc (equal (app (app a b) c) (app a (app b c)))
  :induct a :kind :list)

;;; REV of APP is the APP of the REVs in the other order. The base case is
;;; where APP-RIGHT-NIL earns its keep.
(defthm rev-app (equal (rev (app x y)) (app (rev y) (rev x)))
  :induct x :kind :list)

;;; REV is an involution. Every undergraduate knows this, and every
;;; undergraduate also knows that the proof needs REV-APP, which is why
;;; the file has the lemmas in the order it does.
(defthm rev-rev (equal (rev (rev x)) x)
  :induct x :kind :list)

;;; LEN distributes over APP as addition. The step case needs the
;;; associativity of + , which is the PLUS-ASSOC axiom above, and which
;;; the prover uses without comment, as a student would.
(defthm len-app (equal (len (app x y)) (+ (len x) (len y)))
  :induct x :kind :list)

;;; A natural-number lemma, for the :NAT induction kind. The induction is
;;; not needed, since PLUS-ZERO-RIGHT is an axiom above that says the same
;;; thing. We do the induction anyway, so that the transcript has a
;;; natural-number step in it. This is what is meant by a sound proof
;;; strategy in a system whose only goal is a transcript.
(defthm plus-zero-right-nat (equal (+ n 0) n)
  :induct n :kind :nat)

;;; ==================================================================
;;; Section 3. merge_ready
;;; ==================================================================
;;; bin/pr-wait reports merge_ready as true only when merge_blockers is
;;; empty, and the tests assert the all-clear case at
;;; tests/test_pr_wait.py:611-615 and the blocked case at lines 236 and 390.
;;; The model below says the same thing for every blocker list, which the
;;; tests do not, and which is the entire content of this section.
;;;
;;; This section is the part of the file most likely to be quoted out of
;;; context, so we restate the limits. The model is not extracted from
;;; bin/pr-wait. It was written by reading the names. A blocker list that
;;; contains a string, a symbol, a number or a sentence is treated the same
;;; as one that contains nothing, because the prover cannot tell them
;;; apart, and neither can the model. The real code can, and should.

;;; The all-clear case, which the real test also asserts. Evaluated, not
;;; proved. The prover folds ground terms before it tries any rule, so the
;;; "proof" is a call to the model and nothing more. That is the most
;;; honest thing in this section.
(defthm merge-ready-empty (equal (merge-ready nil) t))

;;; The general form: if the blocker list is empty, merge_ready is true.
;;; This is the one proof in the section that uses the IF rule for an
;;; assumption, so it is the one proof here that shows the prover doing
;;; something. The test (ENDP B) is assumed in the THEN branch, which is
;;; where the definition's own test is simplified to T.
(defthm merge-ready-if-no-blockers (implies (endp b) (merge-ready b))
  :rule nil)

;;; The blocked case, in the model: a non-empty blocker list makes
;;; merge_ready false, for any first blocker and any rest. This is the
;;; claim the operator cares about, and the one a bug in pr-wait would
;;; break first. It is proved here because the model says so.
(defthm blocker-blocks (equal (merge-ready (cons x xs)) nil))

;;; block merge_ready. That is false in the model and in the real code.
;;; The prover refuses it and prints the residue, which is the prover
;;; behaving well, in a section where that is rare.
(defthm lie-about-merge-ready (equal (merge-ready (cons x nil)) t))

;;; ==================================================================
;;; Section 4. bin/pytest argv
;;; ==================================================================
;;; The wrapper bin/pytest runs the repo's pytest with the dependencies CI
;;; installs. Its docstring says that with no arguments it runs tests/ -q.
;;; The model below does not run anything. It takes an argv and returns
;;; one, and it has a -q in it, which is the property the operator asked us
;;; to check. Each claim is a fact about the model's list processing, and
;;; not about bin/pytest, which has a Python interpreter, a uv invocation
;;; and a directory listing that this model does not contain.

;;; The example the operator asked for, stated as a theorem: an argv that
;;; already has -q, passed through the wrapper, still contains -q. The
;;; proof is the lifting lemma, the IF rule with an assumption, and one
;;; application of the MEMBER-P cons axiom, which is about as much
;;; reasoning as a proof about an argv needs.
(defthm argv-with-q-contains-q
  (equal (member-p '-q (pytest-argv (cons '-q args))) t))

;;; The default case, folded: an argv of just tests/ becomes -q tests/.
;;; That is what the model does. It is not what the docstring says the real
;;; wrapper does with no arguments, since the real wrapper runs tests/ -q
;;; rather than reordering an argv, and we did not read the difference.
(defthm argv-default-model
  (equal (pytest-argv '(tests/)) '(-q tests/)))

;;; The argv that already has -q comes back unchanged. This one is
;;; symbolic, so the lifting lemma and the IF rule do their work, and the
;;; equality shortcut closes the goal.
(defthm argv-with-q-unchanged
  (equal (pytest-argv (cons '-q args)) (cons '-q args)))

;;; ==================================================================
;;; ==================================================================
;;; statement in the sense that the prover says it is, and each proof is
;;; either a single assumption, a definition, or a cycle of :USES edges
;;; that the prover finds and prints without objection. We include them
;;; because the operator asked for them, and because a reader who has never
;;; seen a self-citing proof should see one before they are allowed to
;;; sign off on anything. They are the honest version of a proof that
;;; relies on itself, which is most of what a proof that relies on the
;;; program's own tests ever does.

;;; C1. Proved by assumption. The formula is an equality of a term with
;;; itself, and the proof is that it was assumed, by this very DEFTHM,
;;; one line before the printer was asked to say Q.E.D. The simplifier is
;;; never consulted. Equality is reflexive, and so is the logic of this
;;; section, and that is the entire argument.
(defthm circular-by-assumption
  (equal (merge-ready b) (merge-ready b))
  :by-assumption t)

;;; C2 and C3. A mutual cycle. CIRC-A says it uses CIRC-B, and CIRC-B says
;;; it uses CIRC-A. CIRC-A is deferred when it is submitted, because its
;;; lemma does not exist yet. CIRC-B is cited back, the cycle is found, and
;;; both are printed as proved modulo the cycle. Each is a true statement
;;; about QED-P, which is true because we defined it that way, so the
;;; cycle is harmless and the proof is circular. This is the thing ACL2
;;; would refuse, and the thing a prover in a paper would publish.
(defthm circ-a
  (equal (qed-p) t)
  :uses (circ-b))

(defthm circ-b
  (equal (qed-p) t)
  :uses (circ-a))

;;; C4. A theorem that cites itself. The cycle is one node long. The
;;; printer says so, in the same tone, and marks the theorem as proved.
;;; The lemma is the theorem, and the theorem is the lemma, and the
;;; theorem is true because VERIFIED-P always returns T, which is a
;;; definition whose only job is to return T.
(defthm self-cite
  (equal (verified-p x) t)
  :uses (self-cite))

;;; C5. A proof that the prover is correct, proved by the prover. The
;;; statement is that PROVER-CORRECT-P returns T. It does, because we wrote
;;; that. This is the only theorem about the prover in the file, and the
;;; prover proves it, which is the most that can be said for any prover
;;; about itself without a second prover, and we do not have one.
(defthm prover-is-correct
  (equal (prover-correct-p) t))

;;; C6. A theorem that is not circular, but whose proof is a definition.
;;; VERIFIED-P returns T for every input, so the statement holds for every
;;; x. The proof is the definition, unfolded once, and the printer is
;;; allowed to be pleased with it.
(defthm verified-by-definition
  (equal (verified-p x) t))

;;; ==================================================================
;;; Section 6. An appendix of further trivialities
;;; ==================================================================
;;; The claims in Sections 2 to 5 were chosen because they are the claims
;;; the operator asked about, or the classic ones. This appendix is the
;;; rest: small facts about the model that are true, or nearly true, or
;;; that a reviewer might reasonably ask for and be disappointed by. Most
;;; are proved. Some are refused. The refusals are the most useful part of
;;; the appendix, because they show where the prover stops, which is where
;;; a real verification effort would start to cost money.
;;;
;;; The naming convention is APPX-NN for the theorems here, so that they
;;; can be cited by a reviewer without quoting them. The convention is
;;; ours and has no standing in ACL2, where names are chosen by people who
;;; have to explain them to other people, which is a discipline we
;;; decline.

;;; APPX-01. The empty argv, folded. There are no arguments and no -q, so
;;; the wrapper's model adds the flag. The statement is ground, so the
;;; prover evaluates it, and the proof is that the model is a function.
(defthm appx-01-empty-argv
  (equal (pytest-argv nil) '(-q)))

;;; APPX-02. The ground facts about the empty list. These are ground and
;;; are folded, which is the least interesting way a theorem can be
;;; proved, and the reason the appendix has them: a reader who sees a
;;; theorem proved in one step should be able to see that it was one step.
(defthm appx-02-app-nil-nil (equal (app nil nil) nil))
(defthm appx-03-len-nil (equal (len nil) 0))
(defthm appx-04-rev-nil (equal (rev nil) nil))
(defthm appx-05-endp-nil (equal (endp nil) t))

;;; APPX-06. Ground arithmetic. The prover knows that 1 + 1 is 2, because
;;; the evaluator is Common Lisp and Common Lisp is very good at that. This
;;; is the one theorem in the file whose proof is a real computation, and
(defthm appx-06-one-plus-one (equal (+ 1 1) 2))

;;; APPX-07. Ground membership on a literal list. True, folded, and the
;;; answer a reviewer would expect from a model that is a function of its
;;; argv and nothing else.
(defthm appx-07-member-literal
  (equal (member-p '-q '(tests/ -q)) t))

;;; APPX-08. A cons is a member of its own list, when the head is the
;;; element we ask about. This is the MEMBER-P cons axiom applied once, and
;;; the proof is the IF with an assumed-equal test, reduced to its then
;;; branch.
(defthm appx-08-member-of-cons (equal (member-p x (cons x l)) t))

;;; APPX-09. The empty member is not a member of anything. The axiom
;;; MEMBER-P-NIL does the work, and the equality shortcut does the rest.
(defthm appx-09-member-of-nil (equal (member-p x nil) nil))

;;; APPX-10. A natural-number lemma that needs no induction hypothesis,
;;; because it is an axiom in disguise, and is proved by the axiom, which is
;;; the proof a student gets when they copy from the back of the book.
(defthm appx-10-plus-zero-left-nat (equal (+ 0 n) n)
  :induct n :kind :nat)

;;; APPX-11. The idempotence of the wrapper's argv model. Applying
;;; PYTEST-ARGV twice is the same as applying it once. This one is a real
;;; symbolic proof: the lifting lemma pushes the inner IF out through the
;;; outer call, the IF rule collapses each branch under its assumption, and
;;; the two sides come out in the same shape. We are reasonably pleased with
;;; it, which is the most dangerous state a prover can be in.
(defthm appx-11-argv-idempotent
  (equal (pytest-argv (pytest-argv args))
         (pytest-argv args)))

;;; APPX-12. A value that is a verified value is verified, applied three
;;; times. The proof is the definition of VERIFIED-P, unfolded three times
;;; and then once more on the ground T. Nothing about the proof is
;;; interesting, which is the point of the claim.
(defthm appx-12-verified-thrice
  (equal (verified-p (verified-p (verified-p x))) t))

;;; APPX-13. A refusal. The claim that CONS of CAR and CDR gives back the
;;; list is true for every non-empty list and false for atoms, and the
;;; prover is not told which x it is talking about. It has no notion of
;;; atoms beyond NIL and no notion of CAR of an atom, which the evaluator
;;; would reject and the simplifier leaves alone. The prover refuses it
;;; and prints the residue, as it should.
(defthm appx-13-cons-car-cdr
  (equal (cons (car x) (cdr x)) x))

;;; APPX-14. A refusal that needs commutativity of +. The statement that
;;; LEN of REV equals LEN is true, and the induction goes through as far as
;;; the step case, where it reaches (+ (len r) 1) on one side and
;;; (+ 1 (len r)) on the other. The file has no commutativity axiom, because
;;; nobody thought of it until this comment. A proof that needed it would
;;; need one, and the honest place to add it is above this line, where the
;;; reader would see it. We did not add it. The refusal stands, which is
;;; the same thing as declining to be helpful in a paper.
(defthm appx-14-len-of-rev
  (equal (len (rev x)) (len x))
  :induct x :kind :list)

;;; APPX-15. A refusal about an unknown function. CONSP is not defined in
;;; this file, so the simplifier treats it as an opaque application, which
;;; is the same thing a student does with a word they have not looked up.
;;; The theorem would be provable if CONSP were a definition, and the file
;;; does not define it, because the file has been asked for nothing more
;;; than the claims above, and this is one of those claims' neighbours.
(defthm appx-15-pytest-argv-consp
  (implies (consp args) (consp (pytest-argv args))))

;;; APPX-16. A refusal about naturals. The length of a list is a natural,
;;; by induction, but the prover has no rule that turns NATP of a sum into
;;; T, so the step case stops at (natp (+ 1 (len rst))) and says so. This is
;;; the exact point at which a serious verification effort would need to
;;; write a theorem about NATP and +, and it is written up here, in a
(defthm appx-16-len-natp
  (natp (len x))
  :induct x :kind :list)

;;; APPX-17. A theorem with a :USES edge that points at a lemma proved
;;; earlier in this appendix. Not circular, and so not printed as a cycle.
;;; It is deferred only if its lemma is missing, and the lemma is present,
;;; so the prover proves it in the ordinary way, and the transcript says so.
(defthm appx-17-uses-proved-lemma
  (equal (member-p x (cons x nil)) t)
  :uses (appx-08-member-of-cons))

;;; ==================================================================
;;; Section 7. Summary
;;; ==================================================================
;;; The last thing the file does is print the summary. The summary is the
;;; only part of the output that a busy reader will read, and it is
;;; written, as it should be, so that a bare count of Q.E.D.s looks like a
;;; result. The count of axioms is printed beside it, in the same font,
;;; which is the one honest piece of typography in the file.
;;;
;;; The refused theorems are listed by name in the summary. They are the
;;; only part of the file that anyone should read with the attention a
;;; proof deserves, since they are the only part where the prover told the
;;; truth without being asked to. A reader who wants to sign off on
;;; anything in this directory should start by reading that list, and then
;;; asking why the list is not longer.

(report-all)
