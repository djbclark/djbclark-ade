# Upstream snapshots

Fetched 2026-10-14 by `scripts/hyades-refresh-docs`. Copyright 2026 SIPB, MIT licence (`LICENSE`).

| File | Source | Commit |
|---|---|---|
| `inessential.md` | [SIPB/hyades docs/inessential.md](https://forgejo.mit.edu/SIPB/hyades/src/branch/main/docs/inessential.md), rendered at https://hyades.mit.edu/inessential.html | `f9f5f503560c9b952c989358d24fa30e719a59d8` |
| `hyades-README.md` | [SIPB/hyades README.md](https://forgejo.mit.edu/SIPB/hyades) | `f9f5f503560c9b952c989358d24fa30e719a59d8` |
| `console.py` | [SIPB/hyades hyades/console.py](https://forgejo.mit.edu/SIPB/hyades/src/branch/main/hyades/console.py): the console itself | `f9f5f503560c9b952c989358d24fa30e719a59d8` |
| `quadlet.txt` | [SIPB/hyades hyades/quadlet.txt](https://forgejo.mit.edu/SIPB/hyades/src/branch/main/hyades/quadlet.txt): the per-microVM Quadlet template | `f9f5f503560c9b952c989358d24fa30e719a59d8` |
| `hyades-action.yml` | [SIPB/hyades-action action.yml](https://forgejo.mit.edu/SIPB/hyades-action) | `c304e46eed7a43fd578a305b5d1b83bbbf43fa14` |

**Stale (noted 2026-10-16):** these snapshots are at the commits above; SIPB/hyades has moved on. In particular `3e291d2b6e` (2026-10-15) redesigned `tmprun` (no image argument; `console.py` and `inessential.md` here still show `tmprun IMAGE CMD?` and `tmprun ubuntu`). `scripts/hyades-refresh-docs` also ssh-es to hyades.mit.edu for `console-help.txt`, so it was not run for this note; re-run it when a Hyades login is wanted.
