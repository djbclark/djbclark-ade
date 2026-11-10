### Security

- `_FORMAT_PATCH_VALUE_LONG` includes git 2.56 required-value longs `--commit-list-format` and `--range-diff-notes`, so a following `-o .` is not treated as an in-claim output directory while git still writes into `format.outputDirectory` (#496).
