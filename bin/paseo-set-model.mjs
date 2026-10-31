#!/usr/bin/env bash
# paseo-set-model.mjs: node (ELECTRON_RUN_AS_NODE=1) and talks to the daemon through the bundled CLI's own client. Implementation: hs/app/PaseoSetModelMjs.hs.
exec "$(dirname "$(readlink -f "$0")")/ade-hs-run" PaseoSetModelMjs "$@"
