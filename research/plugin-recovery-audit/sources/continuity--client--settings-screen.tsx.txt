import { type PluginSurfaceProps, useSettings } from "@getpaseo/plugin/client";
import {
  SettingsAction,
  SettingsCard,
  SettingsSection,
  SettingsSelect,
  SettingsSwitch,
} from "@getpaseo/plugin/client/ui";
import { useMemo } from "react";
import { Text, View } from "react-native";
import {
  type ContinuitySettings,
  continuitySettings,
} from "../shared/settings";
import { ChainEditor } from "./chain-editor";
import { SummarySettings } from "./summary-settings";

const WARN_OPTIONS = [5, 10, 15, 20, 30, 50].map((pct) => ({ value: String(pct), label: `${pct}% left` }));

const COUNT_OPTIONS = ["1", "2", "3", "4", "5", "8"].map((value) => ({ label: value, value }));
const BUDGET_OPTIONS = ["20000", "40000", "60000", "100000", "150000", "200000"].map((value) => ({
  label: `${Number(value) / 1000}k chars`,
  value,
}));

export function SettingsScreen({ theme }: PluginSurfaceProps) {
  const settings = useSettings(continuitySettings);
  const muted = useMemo(() => ({ color: theme.colors.foregroundMuted, fontSize: 13 }), [theme]);

  if (settings.status === "loading") {
    return <Text style={muted}>Loading…</Text>;
  }
  if (settings.status !== "ready") {
    return (
      <SettingsSection title="Paseo Continuity">
        <SettingsCard>
          <SettingsAction
            label="Stored settings are unreadable"
            hint={settings.error}
            actionLabel="Reset to defaults"
            onPress={() => void settings.reset()}
          />
        </SettingsCard>
      </SettingsSection>
    );
  }

  const values = settings.values;
  const save = (next: ContinuitySettings) => void settings.save(next, settings.revision);

  return (
    <View style={{ gap: 16 }}>
      <SettingsSection title="Automatic failover">
        <SettingsCard>
          <SettingsSwitch
            label="Enable Paseo Continuity"
            hint="When a turn fails on quota or rate limits, continue in a new agent on the next provider."
            value={values.enabled}
            onValueChange={(enabled) => save({ ...values, enabled })}
          />
          <SettingsSwitch
            label="Usage quota exhausted"
            value={values.triggers.quota}
            onValueChange={(quota) => save({ ...values, triggers: { ...values.triggers, quota } })}
          />
          <SettingsSwitch
            label="Rate limited"
            value={values.triggers.rateLimit}
            onValueChange={(rateLimit) => save({ ...values, triggers: { ...values.triggers, rateLimit } })}
          />
          <SettingsSwitch
            label="Provider overloaded"
            hint="Usually transient; off by default."
            value={values.triggers.overloaded}
            onValueChange={(overloaded) => save({ ...values, triggers: { ...values.triggers, overloaded } })}
          />
        </SettingsCard>
      </SettingsSection>

      <SettingsSection
        title="Fallback chain"
        info={
          <Text style={muted}>
            Select and order providers to use when the active provider runs out of quota or hits rate limits.
          </Text>
        }
      >
        <SettingsCard>
          <ChainEditor
            chain={values.chain}
            onChainChange={(chain) => save({ ...values, chain })}
            theme={theme}
          />
          <SettingsSwitch
            label="Show Continuity pill in composer"
            hint="Display a quick failover button in the chat composer bar."
            value={values.showComposerPill}
            onValueChange={(showComposerPill) => save({ ...values, showComposerPill })}
          />
          <SettingsSelect
            label="Warn when remaining quota drops to"
            value={String(values.warnAtRemainingPct)}
            options={WARN_OPTIONS}
            onValueChange={(value) => save({ ...values, warnAtRemainingPct: Number(value) })}
          />
          <SettingsSwitch
            label="Provider badge in new chat titles"
            value={values.titleBadges}
            onValueChange={(titleBadges) => save({ ...values, titleBadges })}
          />
        </SettingsCard>
      </SettingsSection>

      <SettingsSection title="Context transfer">
        <SettingsCard>
          <SettingsSelect
            label="Mode"
            hint="Automatic sends a bounded recent transcript; Full sends up to the full budget."
            value={values.contextMode}
            options={[
              { label: "Automatic", value: "automatic" },
              { label: "Full transcript", value: "full" },
            ]}
            onValueChange={(contextMode) => save({ ...values, contextMode })}
          />
          <SettingsSelect
            label="Automatic budget"
            value={String(values.budgets.automaticChars)}
            options={BUDGET_OPTIONS}
            onValueChange={(value) =>
              save({ ...values, budgets: { ...values.budgets, automaticChars: Number(value) } })
            }
          />
          <SummarySettings values={values} save={save} theme={theme} />
        </SettingsCard>
      </SettingsSection>

      <SettingsSection title="Loop protection">
        <SettingsCard>
          <SettingsSelect
            label="Maximum switches per chain"
            value={String(values.maxSwitchesPerChain)}
            options={COUNT_OPTIONS}
            onValueChange={(value) => save({ ...values, maxSwitchesPerChain: Number(value) })}
          />
          <SettingsSelect
            label="Maximum consecutive switches without progress"
            value={String(values.maxConsecutiveFailovers)}
            options={COUNT_OPTIONS}
            onValueChange={(value) => save({ ...values, maxConsecutiveFailovers: Number(value) })}
          />
        </SettingsCard>
      </SettingsSection>
      {settings.saveError ? <Text style={{ color: theme.colors.statusDanger }}>{settings.saveError}</Text> : null}
    </View>
  );
}
