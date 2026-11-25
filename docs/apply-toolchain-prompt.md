# Applying the ADE toolchain

The [original toolchain prompt](history/apply-toolchain-prompt.md) is archived.
For the current workflow, see the [ADE operating guide](../AGENTS.md).

Keep Reality Fabricator out of default MCP and Pi configurations. When the
operator requests it for a task, use the
[task-only MCP setup](mcp-servers.md#reality-fabricator-on-demand) or the
[explicit Pi launch](pi-services.md#veniceai-and-reality-fabricator-manual-access-2026-11-25).
Both resolve their credential at runtime through `sudo-secretspec`.
