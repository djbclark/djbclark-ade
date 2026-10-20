# GitHub Linux CI (ci/base)

The pytest suite (`tests/`) runs on free GitHub-hosted runners via the orphan
`ci/base` branch plus `ci/run/**` pushes (not on `master`).

    scripts/github-ci-run [--no-wait] [REF]    # REF defaults to HEAD

The wrapper builds a commit = REF's tree + this overlay, force-pushes
`ci/run/<slug>-<sha8>` and watches the run. It needs `origin/ci/base` fetched.
