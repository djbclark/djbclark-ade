- Add `ade-install doctor --id ID` and `just doctor hermes` for component-only
  checks with explicit result scope; unchosen components never probe and full
  doctor behavior stays intact. Fix pre-existing split printf format strings
  that prevented Just from parsing the Hermes setup recipe.
