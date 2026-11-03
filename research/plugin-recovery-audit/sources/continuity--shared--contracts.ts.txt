import { defineRpc } from "@getpaseo/plugin";
import { z } from "zod";
import { ContinuitySettingsSchema } from "./settings";

export const TRANSITION_KIND = "transition";
export const TRANSITION_VERSION = 1;
export const TRANSITION_ROW_ID = "transition";

export const FailureClassSchema = z.enum(["quota", "rate_limit", "overloaded", "manual"]);
export type FailureClass = z.output<typeof FailureClassSchema>;

export const TransitionStatusSchema = z.enum([
  "creating",
  "created",
  "failed",
  "exhausted",
  "halted",
]);
export type TransitionStatus = z.output<typeof TransitionStatusSchema>;

export const TransitionCardSchema = z.object({
  status: TransitionStatusSchema,
  reason: FailureClassSchema,
  evidence: z.string(),
  fromProvider: z.string(),
  toProvider: z.string().nullable(),
  toAgentId: z.string().nullable(),
  toTitle: z.string().nullable(),
  detail: z.string().nullable(),
  at: z.string(),
});
export type TransitionCard = z.output<typeof TransitionCardSchema>;

export const failoverNowRpc = defineRpc({
  name: "continuity.failover-now",
  input: z.object({
    agentId: z.string().min(1),
    /** Provider to continue on; omitted picks the next ready provider in the chain. */
    targetProvider: z.string().min(1).optional(),
    /** "file" writes a compacted handoff file and points the successor at it. */
    handoff: z.enum(["inline", "file"]).optional(),
  }),
  output: z.object({
    status: z.enum(["created", "failed", "exhausted", "halted", "skipped"]),
    newAgentId: z.string().nullable(),
    message: z.string(),
  }),
});

export const getSettingsRpc = defineRpc({
  name: "continuity.get-settings",
  input: z.object({}),
  output: ContinuitySettingsSchema,
});

