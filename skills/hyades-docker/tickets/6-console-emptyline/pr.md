`cmd.Cmd` re-runs the last command when it reads an empty line. At an interactive prompt that is just surprising, but with a script piped in it repeats real work:

```
printf 'df\n\n' | ssh hyades    # prints the df table twice
```

The same blank line after `delete NAME` or `stop NAME` would run it a second time. This overrides `emptyline()` to do nothing.

Checked with `python -m py_compile` and `ruff check` / `ruff format --check`; I couldn't run the NixOS VM tests here.

_Prepared with an AI coding assistant; reviewed by me._
