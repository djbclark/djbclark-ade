// ADE subagent invocation configuration. See NOTICE.md for upstream provenance.
import { StringEnum } from "@earendil-works/pi-ai";
import { Type } from "typebox";

export const THINKING_LEVELS = ["off", "minimal", "low", "medium", "high", "xhigh", "max"] as const;
export type ThinkingLevel = (typeof THINKING_LEVELS)[number];
export interface SelectedConfig {
	model?: string;
	thinking?: ThinkingLevel;
}

export const ConfigProperties = {
	model: Type.Optional(Type.String({
		minLength: 1,
		pattern: "\\S",
		description: "Model ID or provider/model (optional :thinking suffix). Overrides agent frontmatter; otherwise Pi default.",
	})),
	thinking: Type.Optional(StringEnum(THINKING_LEVELS, {
		description: "Thinking level. Overrides agent frontmatter and the selected model's suffix; otherwise Pi default.",
	})),
};

export interface ConfigErrors {
	model?: string;
	thinking?: string;
}

// Also validate at execution: tool_call hooks may mutate arguments after schema validation.
export function fieldErrors(config: { model?: unknown; thinking?: unknown }): ConfigErrors {
	const errors: ConfigErrors = {};
	if (config.model !== undefined && (typeof config.model !== "string" || !config.model.trim())) {
		errors.model = "model must be a nonempty string";
	}
	if (config.thinking !== undefined && !THINKING_LEVELS.includes(config.thinking as ThinkingLevel)) {
		errors.thinking = `thinking must be one of: ${THINKING_LEVELS.join(", ")}`;
	}
	return errors;
}

export function configError(config: { model?: unknown; thinking?: unknown }): string | undefined {
	const e = fieldErrors(config);
	return e.model ?? e.thinking;
}

/** Errors that matter: an agent's bad frontmatter field is moot when the invocation overrides that field. */
export function effectiveConfigError(invocation: SelectedConfig, agentErrors?: ConfigErrors): string | undefined {
	const own = configError(invocation);
	if (own) return own;
	const model = invocation.model === undefined ? agentErrors?.model : undefined;
	const thinking = invocation.thinking === undefined ? agentErrors?.thinking : undefined;
	return model ?? thinking;
}

export function selectConfig(invocation: SelectedConfig, agent?: SelectedConfig): SelectedConfig {
	// Do not split model IDs on '/' or ':': Pi owns namespace/suffix resolution.
	// Explicit --thinking wins over a suffix in Pi, regardless of argv order.
	return { model: invocation.model ?? agent?.model, thinking: invocation.thinking ?? agent?.thinking };
}
