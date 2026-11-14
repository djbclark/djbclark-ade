### Added

- `docs/gui-hog-dialog.md`: design for the GUI-hog dialog (PR 3 of the load-gate retune). It covers why Swift, the sampler-side trigger with the `admit --wait` hold registry, a thin Swift view over a stdlib-Python core, Freeze safety (write-ahead state file, pid-plus-start identity, thaw paths, protected list, escape hatch), Quit semantics, testing, phasing and threat notes. No code yet (#717)
