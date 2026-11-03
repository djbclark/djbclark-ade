import { defineSettings } from "@getpaseo/plugin";
import { z } from "zod";

export const ChainEntrySchema = z.object({
  /** Paseo provider ID, e.g. "codex", "claude", "opencode". */
  provider: z.string().min(1),
  /** Model ID for that provider; null resolves the provider's default model. */
  model: z.string().min(1).nullable().default(null),
  /** Provider mode for the successor; null keeps the provider default. */
  modeId: z.string().min(1).nullable().default(null),
  thinkingOptionId: z.string().min(1).nullable().default(null),
});

export type ChainEntry = z.output<typeof ChainEntrySchema>;

export const ContextModeSchema = z.enum(["automatic", "full"]);
export type ContextMode = z.output<typeof ContextModeSchema>;

export const ContinuitySettingsSchema = z.object({
  enabled: z.boolean().default(true),
  triggers: z
    .object({
      quota: z.boolean().default(true),
      rateLimit: z.boolean().default(true),
      overloaded: z.boolean().default(false),
    })
    .default({ quota: true, rateLimit: true, overloaded: false }),
  chain: z.array(ChainEntrySchema).default([
    { provider: "codex", model: null, modeId: "auto", thinkingOptionId: null },
    { provider: "claude", model: null, modeId: "default", thinkingOptionId: null },
  ]),
  contextMode: ContextModeSchema.default("automatic"),
  budgets: z
    .object({
      automaticChars: z.number().int().min(4_000).max(400_000).default(60_000),
      fullChars: z.number().int().min(4_000).max(400_000).default(200_000),
    })
    .default({ automaticChars: 60_000, fullChars: 200_000 }),
  /** Optionally condenses the transcript with a separate (cheap or local) model before handoff. */
  summary: z
    .object({
      enabled: z.boolean().default(false),
      provider: z.string().min(1).nullable().default(null),
      model: z.string().min(1).nullable().default(null),
      inputChars: z.number().int().min(4_000).max(400_000).default(30_000),
      timeoutSeconds: z.number().int().min(10).max(900).default(180),
    })
    .default({ enabled: false, provider: null, model: null, inputChars: 30_000, timeoutSeconds: 180 }),
  maxSwitchesPerChain: z.number().int().min(1).max(20).default(3),
  maxConsecutiveFailovers: z.number().int().min(1).max(20).default(2),
  cooldownMinutes: z
    .object({
      quota: z.number().min(0).max(24 * 60).default(60),
      rateLimit: z.number().min(0).max(24 * 60).default(5),
    })
    .default({ quota: 60, rateLimit: 5 }),
  includeSubagents: z.boolean().default(false),
  titleBadges: z.boolean().default(true),
  showComposerPill: z.boolean().default(true),
  /** The composer pill warns and offers a compacted handoff at or below this remaining quota. */
  warnAtRemainingPct: z.number().min(1).max(90).default(15),
});

export type ContinuitySettings = z.output<typeof ContinuitySettingsSchema>;

export const continuitySettings = defineSettings({
  id: "config",
  scope: "host",
  version: 1,
  schema: ContinuitySettingsSchema,
});

export const DEFAULT_SETTINGS: ContinuitySettings = ContinuitySettingsSchema.parse({});
