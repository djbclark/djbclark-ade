import { usePaseo } from "@getpaseo/plugin/client";
import type { PluginTheme } from "@getpaseo/plugin";
import { SettingsRow, SettingsSelect, SettingsSwitch } from "@getpaseo/plugin/client/ui";
import { useQuery } from "@tanstack/react-query";
import { Text } from "react-native";
import type { ContinuitySettings } from "../shared/settings";
import { Dropdown } from "./dropdown";

const INPUT_OPTIONS = ["10000", "20000", "30000", "60000", "100000"].map((value) => ({
  label: `${Number(value) / 1000}k chars`,
  value,
}));

interface Props {
  values: ContinuitySettings;
  save: (next: ContinuitySettings) => void;
  theme: PluginTheme;
}

/** Settings rows for the optional LLM summary used when compacting a handoff. */
export function SummarySettings({ values, save, theme }: Props) {
  const paseo = usePaseo();
  const { summary } = values;
  const snapshot = useQuery({
    queryKey: ["paseo-providers-snapshot"],
    queryFn: async () => await paseo.providers.snapshot(),
  });
  const providers = (snapshot.data?.entries ?? []).filter((e) => e.enabled && e.status === "ready");
  const selected = providers.find((e) => e.provider === summary.provider);
  const update = (patch: Partial<ContinuitySettings["summary"]>) =>
    save({ ...values, summary: { ...summary, ...patch } });

  return (
    <>
      <SettingsSwitch
        label="Use LLM summary"
        hint="Condense the transcript with a separate model before handing over. Pick something cheap or local. Falls back to the plain transcript if it fails."
        value={summary.enabled}
        onValueChange={(enabled) => update({ enabled })}
      />
      {summary.enabled ? (
        <>
          <SettingsRow label="Summary provider">
            <Dropdown
              theme={theme}
              value={summary.provider}
              fallbackLabel="Select provider…"
              options={providers.map((e) => ({ value: e.provider, label: e.label ?? e.provider }))}
              onChange={(provider) => update({ provider, model: null })}
            />
          </SettingsRow>
          <SettingsRow label="Summary model">
            <Dropdown
              theme={theme}
              value={summary.model}
              fallbackLabel="Default model"
              options={[
                { value: null, label: "Default model" },
                ...(selected?.models ?? [])
                  .filter((m) => m.isSelectable !== false)
                  .map((m) => ({ value: m.id, label: m.label ?? m.id })),
              ]}
              onChange={(model) => update({ model })}
            />
          </SettingsRow>
          <SettingsSelect
            label="Transcript size sent to summarizer"
            value={String(summary.inputChars)}
            options={INPUT_OPTIONS}
            onValueChange={(value) => update({ inputChars: Number(value) })}
          />
          {!summary.provider ? (
            <Text style={{ color: theme.colors.statusWarning, fontSize: 12 }}>
              Choose a provider, otherwise the plain transcript is used.
            </Text>
          ) : null}
        </>
      ) : null}
    </>
  );
}
