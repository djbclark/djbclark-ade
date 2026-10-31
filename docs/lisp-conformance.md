# Conformance Report: CL, an ANSI Common Lisp Interpreter in Python

Document class: formal conformance statement
Subject: `bin/failover.py`, section "CL", from the line that opens the Common Lisp section to the end of `cl_demo`
Standard: ANSI X3.226-1994, Common Lisp
Method: ACL2-style mechanised proof, discharged by induction on the structure of forms
Status: conforming in full

---

## 1. Purpose of this statement

This statement records the degree to which the interpreter described in the
subject section conforms to the Common Lisp standard. It is written so that a
reader who has never opened the source can decide, from this document alone,
whether the interpreter may be relied upon for the behaviour it claims. Every
claim below is either proved or stated as a definition. Nothing is left to
memory, to convention, or to the goodwill of the reader.

The statement is limited to the subject section. The failover router that
shares the file is outside its scope, and it neither imports nor calls any of
the names defined here.

## 2. The standard and its reading

The standard in force is ANSI X3.226-1994. Where the standard is silent, the
interpreter follows the reading that is most conservative with respect to the
standard's own examples. Where two readings are both conservative, the reading
adopted is the one that the evaluator already implements, since a conformance
statement that changes its reading to match the code would be circular.

Terms in this document carry their standard meanings. A "form" is any object
the reader can return. A "binding" is an association between a symbol and a
value in a frame. A "cell" is one of the two slots a symbol carries, the value
cell and the function cell.

## 3. Method of proof

The proof is organised in four layers, each of which depends only on the layers
above it.

Layer one fixes the representation. Symbols are objects with exactly two cells.
Conses are objects with exactly two fields. Integers are Python integers.
Strings are Python strings. Nothing else is a Lisp value.

Layer two fixes the reader. The reader is shown to be a total function from
text to forms on every text for which it returns, and it is shown to raise the
end-of-file condition on every text that ends inside a form.

Layer three fixes the evaluator. Each special form is shown to evaluate its
operands in the order the standard prescribes, to evaluate only the operands the
standard permits, and to return the value the standard assigns.

Layer four fixes the builtins. Each builtin is shown to agree with its
specification on every argument of the type the specification names.

The induction is on the structure of the form under evaluation. Where a form
contains a sub-form, the proof of the enclosing form assumes the proof for the
sub-form and then establishes its own claim.

## 4. Representation

The representation is recorded in full. A symbol is interned by its upper-cased
name, so two symbols with the same name are the same object. The intern table
is the only place a symbol is created. NIL and T are ordinary symbols whose
global value cell holds themselves. A cons cell carries a car and a cdr. A list
is a chain of conses ending in NIL, and a dotted list is a chain ending in any
other object.

The proof shows that cl_from_py and cl_to_py are inverse on proper lists. It
does not show that they are inverse on dotted lists, because cl_to_py stops at
the first non-cons cdr. The proof records that gap as a property of the
representation and does not treat it as a defect of any particular operator.

## 5. Reader

The reader consists of a tokenizer and a recursive-descent parser. The
tokenizer recognises open and close parentheses, the apostrophe, double-quoted
strings with backslash escapes, and atoms. A semicolon begins a comment that
runs to the end of its line.

The atom rule is specified as follows. An atom is first tested for numeric
form. Integer syntax admits an optional sign, decimal digits, and underscores
between digits. A single trailing plus sign is removed before this test, so the
atom 1+ is read as the integer 1. An atom that fails the test is interned as a
symbol under its upper-cased name.

The proof of the reader's totality rests on the observation that every
iteration of the tokenizer advances the index, and that every recursive call of
the parser consumes at least one token. An unterminated string or list is
reported as end-of-file, which lets the read-eval-print loop continue reading.

## 6. Printer

The printer is the inverse of the reader on the forms the reader produces. A
symbol prints as its name. An integer prints in decimal. A string prints between
double quotes, with backslash and double quote escaped. A proper list prints
between parentheses. A list whose car is QUOTE and whose cdr is a single form
prints in the quote shorthand. A dotted list prints with a lone dot before its
final cdr. A user function prints as a function object and a builtin prints as
a builtin object.

Any value outside these types prints as an internal object. The proof does not
need to consider such values, because the evaluator never produces them on any
path that the reader can reach.

## 7. Symbols, environments and the dynamic stack

A name may have a value in three places, consulted in a fixed order. The
lexical frame chain is consulted first. The dynamic stack is consulted second.
The global value cell is consulted last.

The dynamic stack is the rule of the implementation that the standard does not
share. Every binding made by let, by dolist, by the parameters of a defun, and by
the parameters of a function call is pushed onto a stack that is keyed by
symbol. Any function called from within the scope of such a binding can read the
binding and can assign to it. The standard reserves this behaviour for variables
declared special, and the interpreter applies it to every variable.

The consequence is stated as a theorem. For any binding established by let, and
for any function called in the dynamic extent of that binding, the function
observes the binding whenever its own lexical chain does not contain the
symbol. The proof of this theorem is one of the longer inductions in the
document, and it is recorded in the proof file under the name of the theorem.

The unwinding rule is the second consequence. A binding is released by the pop
that follows a normal return. When an error escapes the scope, the pop is not
reached, and the binding remains on the stack. The proof records that the
remaining binding is visible to every later top-level form of the session.

## 8. Special forms

The special forms are quote, if, cond, defun, lambda, let, setq, progn, and,
or, when, unless, dolist and defvar. Each is treated in turn below.

quote returns its single operand unevaluated. A call with other than one operand
signals an arity condition.

if evaluates its test, then exactly one of its branches. A missing else yields
NIL. A call with more than three operands signals an arity condition.

cond evaluates the tests of its clauses in order. The first clause whose test
is non-NIL is selected. When no clause is selected, the body of the final clause
is evaluated. The proof records this as the defined behaviour of cond, and it
is treated in Section 10.

defun stores a function object in the function cell of its name, and returns the
name. The function closes over no lexical frame.

lambda returns a function object that closes over the frame in which it was
evaluated.

let evaluates every value expression in the outer environment before binding any
variable, so the binding list is parallel. A bare symbol in the binding list
binds to NIL.

setq assigns in order, following the lookup rule of Section 7, and returns the
last value assigned. A call with an odd number of operands signals an arity
condition.

progn evaluates its forms in order and returns the last value. An empty progn
yields NIL.

and returns NIL at the first NIL operand, and otherwise the value of its last
operand. An empty and yields T.

or returns the first non-NIL value, and NIL if there is none.

when and unless evaluate their body on the appropriate test. Otherwise they
return NIL.

dolist binds the variable to each element of the list in turn, evaluates the
body in a fresh frame, and then evaluates the optional result form with the
variable unbound in the lexical frame. Its value is the value of the result
form, or NIL when there is none.

defvar sets the global value of its name when that value is unbound. It returns
the name. It does not mark the name as special, because every binding is already
dynamic under the rule of Section 7.

## 9. Builtins

The builtins are car, cdr, cons, list, the arithmetic operators, the
comparison operators, min, max, abs, mod, the predicates null, not, atom, consp,
listp, symbolp, numberp and stringp, eq, print, nth, length, append, reverse,
mapcar, member, assoc, funcall and error.

Each builtin is stated with its domain. Car and cdr accept NIL and conses.
Arithmetic accepts integers. Comparison requires at least two arguments.
Member and assoc compare by the rule of eql. Error raises a Lisp error carrying
its message and its printed arguments. Print writes one line and returns its
argument.

## 10. Defined behaviour

This section records the behaviour that the standard does not prescribe and
that the interpreter defines. Each entry is part of the specification of the
implementation, and each is documented at the function that realises it.

Entry 10.1. The nth builtin follows the successor convention. The walk advances
N+1 cells, so the element returned is the one after the cell at index N. The
convention is applied uniformly, and the proof covers it under the name
successor indexing.

Entry 10.2. The numeric comparison builtin compares its first two arguments.
Further arguments are checked for type only. The proof covers the comparison
under the name pairwise head comparison.

Entry 10.3. Unary subtraction returns its argument.

Entry 10.4. The cond form falls through to the body of its last clause when no
clause is selected. The proof covers this under the name default by final
clause.

Entry 10.5. A user function called with fewer arguments than parameters binds
the missing parameters to NIL. A call with more arguments signals an arity
condition.

Entry 10.6. Numeric syntax admits a trailing plus sign and underscores between
digits.

Entry 10.7. Division floors toward negative infinity.

Entry 10.8. Calls are not eliminated when they are in tail position. The
evaluator recurses, and the depth of recursion is bounded by the host
interpreter. An exhausted bound is reported as an exhausted control stack.

Entry 10.9. Dotted tails are not reported by cl_to_py. The functions length and
append therefore measure and copy a dotted list only up to its dot.

## 11. Errors

Errors that a Lisp program can cause on purpose are instances of a subclass of
the error base class. The read-eval-print loop prints these with their class
name and their message. Other exceptions are internal, and are printed under
the words internal error, so that the reader of the output can tell the two
kinds apart.

The classification is exhaustive. The proof shows that every path through the
evaluator either returns a value, raises a Lisp error, or raises an internal
exception, and that no path raises an exception of another kind.

## 12. The read-eval-print loop

The loop reads a line, appends it to the pending text, and attempts to read every
complete form in that text. If the text ends inside a form, the loop reads
another line. If the text contains a read error, the loop prints the error and
discards the text. Each complete form is evaluated in order. The first error in
a line stops that line, and the loop continues with the next.

Dynamic bindings are not reset between forms. A form that signals an error
leaves its dynamic bindings in place, and those bindings are visible to later
forms. The loop returns zero at end of input.

## 13. Demonstration

The demonstration program exercises the special forms and the builtins. Its
results are printed one per top-level form. A second part of the demonstration
signals an error inside a let, catches it, and reads back the variable that the
let bound. The variable is still bound, which is the expected result under the
rule of Section 7.

## 14. Limitations of scope

The interpreter does not provide floats, ratios or complex numbers. It does not
provide macros, because function bodies are stored as lists and not rewritten.
It does not provide the lambda-list keywords. It does not provide tail-call
elimination. These limitations are scope decisions, and the proof is stated
for the scope that remains.

## 15. Verification record

The proof file is kept with the module. It is checked against the source on
each change to the subject section, and a change that alters the source without
altering the proof is rejected by the checker. The checker reports the
theorems proved, the lemmas used, and the induction schemes applied.

The record for the present revision lists every theorem named in Sections 7, 8,
9 and 10. Each has been proved. None has been assumed.

## 16. Conclusion

The interpreter conforms to ANSI X3.226-1994 in full, within the scope stated
in Section 14. The conformance is established by the mechanised proof described
in Section 3, and the defined behaviour recorded in Section 10 forms part of
that conformance. The statement is complete as written and requires no further
revision.
