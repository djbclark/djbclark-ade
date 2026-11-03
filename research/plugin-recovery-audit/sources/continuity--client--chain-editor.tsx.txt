import React, { useMemo } from 'react';
import { View, Text, Switch, Pressable, ActivityIndicator, ScrollView, StyleSheet } from 'react-native';
import { useQuery } from '@tanstack/react-query';
import { usePaseo } from '@getpaseo/plugin/client';
import type { PluginTheme } from "@getpaseo/plugin";
import type { ChainEntry } from "../shared/settings";
import { providerBadge } from '../shared/labels';
import { Dropdown } from './dropdown';

interface ChainEditorProps {
  chain: ChainEntry[];
  onChainChange: (chain: ChainEntry[]) => void;
  theme: PluginTheme;
}

export function ChainEditor({ chain, onChainChange, theme }: ChainEditorProps) {
  const paseo = usePaseo();

  const { data: snapshotResult, isLoading, error } = useQuery({
    queryKey: ['paseo-providers-snapshot'],
    queryFn: async () => await paseo.providers.snapshot(),
  });

  const displayItems = useMemo(() => {
    const entries = snapshotResult?.entries || [];
    const readyEntries = entries.filter(e => e.enabled && e.status === 'ready');
    const entriesByProvider = new Map(entries.map(e => [e.provider, e]));

    const chainItems = chain.map((chainEntry, idx) => {
      const snapshotEntry = entriesByProvider.get(chainEntry.provider);
      return {
        provider: chainEntry.provider,
        chainEntry,
        snapshotEntry,
        inChain: true,
        chainIndex: idx,
        label: snapshotEntry?.label ?? chainEntry.provider,
        isUnknown: !snapshotEntry
      };
    });

    const chainProviderSet = new Set(chain.map(c => c.provider));
    const nonChainItems = readyEntries
      .filter(e => !chainProviderSet.has(e.provider))
      .map(e => ({
        provider: e.provider,
        chainEntry: null,
        snapshotEntry: e,
        inChain: false,
        chainIndex: null,
        label: e.label ?? e.provider,
        isUnknown: false
      }))
      .sort((a, b) => a.label.localeCompare(b.label));

    return [...chainItems, ...nonChainItems];
  }, [chain, snapshotResult]);

  const handleToggle = (provider: string, inChain: boolean) => {
    if (inChain) {
      onChainChange(chain.filter(c => c.provider !== provider));
    } else {
      onChainChange([...chain, { provider, model: null, modeId: null, thinkingOptionId: null }]);
    }
  };

  const handleMoveUp = (index: number) => {
    if (index <= 0) return;
    const newChain = [...chain];
    [newChain[index - 1], newChain[index]] = [newChain[index], newChain[index - 1]];
    onChainChange(newChain);
  };

  const handleMoveDown = (index: number) => {
    if (index >= chain.length - 1) return;
    const newChain = [...chain];
    [newChain[index + 1], newChain[index]] = [newChain[index], newChain[index + 1]];
    onChainChange(newChain);
  };

  const handlePatch = (index: number, patch: Partial<ChainEntry>) => {
    const newChain = [...chain];
    newChain[index] = { ...newChain[index]!, ...patch };
    onChainChange(newChain);
  };

  if (isLoading) {
    return (
      <View style={[styles.center, { backgroundColor: theme.colors.surface1 }]}>
        <ActivityIndicator color={theme.colors.accent} />
        <Text style={{ color: theme.colors.foregroundMuted, marginTop: 8 }}>Loading providers...</Text>
      </View>
    );
  }

  if (error) {
    return (
      <View style={[styles.center, { backgroundColor: theme.colors.surface1 }]}>
        <Text style={{ color: theme.colors.statusDanger }}>Failed to load providers.</Text>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      {chain.length < 2 && (
        <View style={styles.warningBox}>
          <Text style={{ color: theme.colors.statusWarning, fontSize: 13 }}>
            Warning: A fallback chain should ideally have at least 2 providers for continuity.
          </Text>
        </View>
      )}

      <ScrollView style={[styles.list, { backgroundColor: theme.colors.surface1, borderColor: theme.colors.border }]}>
        {displayItems.length === 0 ? (
          <Text style={{ color: theme.colors.foregroundMuted, padding: 16, textAlign: 'center' }}>
            No providers available.
          </Text>
        ) : (
          displayItems.map((item, i) => {
            const isFirstChecked = item.inChain && item.chainIndex === 0;
            const isLastChecked = item.inChain && item.chainIndex === chain.length - 1;
            
            const models = item.snapshotEntry?.models || [];
            const modes = item.snapshotEntry?.modes || [];
            
            const badge = providerBadge(item.provider, item.chainEntry?.model);

            return (
              <View 
                key={`${item.provider}-${item.inChain}`} 
                style={[
                  styles.row, 
                  { borderBottomColor: theme.colors.border },
                  i === displayItems.length - 1 && { borderBottomWidth: 0 }
                ]}
              >
                <View style={styles.mainContent}>
                  <Switch
                    value={item.inChain}
                    onValueChange={() => handleToggle(item.provider, item.inChain)}
                    trackColor={{ true: theme.colors.accent, false: theme.colors.surface2 }}
                  />
                  
                  <View style={styles.labelContainer}>
                    <Text style={{ color: item.isUnknown ? theme.colors.statusWarning : theme.colors.foreground, fontWeight: '500' }}>
                      {badge.badge} {item.label}
                    </Text>
                    {item.isUnknown && (
                      <Text style={{ color: theme.colors.statusWarning, fontSize: 12 }}>
                        Unknown or unavailable provider
                      </Text>
                    )}
                  </View>
                </View>

                {item.inChain && (
                  <View style={styles.actionsContent}>
                    {models.length > 1 && (
                      <Dropdown
                        theme={theme}
                        fallbackLabel="Default model"
                        value={item.chainEntry?.model ?? null}
                        options={[
                          { value: null, label: "Default model" },
                          ...models.map((m: any) => ({ value: m.id as string, label: (m.label ?? m.id) as string })),
                        ]}
                        onChange={(model) => handlePatch(item.chainIndex as number, { model })}
                      />
                    )}

                    {modes.length > 1 && (
                      <Dropdown
                        theme={theme}
                        fallbackLabel="Default mode"
                        value={item.chainEntry?.modeId ?? null}
                        options={[
                          { value: null, label: "Default mode" },
                          ...modes.map((m: any) => ({ value: m.id as string, label: (m.label ?? m.id) as string })),
                        ]}
                        onChange={(modeId) => handlePatch(item.chainIndex as number, { modeId })}
                      />
                    )}

                    <View style={styles.orderControls}>
                      <Pressable 
                        disabled={isFirstChecked}
                        onPress={() => handleMoveUp(item.chainIndex as number)}
                        style={[
                          styles.iconBtn, 
                          { backgroundColor: isFirstChecked ? 'transparent' : theme.colors.surface2 }
                        ]}
                      >
                        <Text style={{ color: isFirstChecked ? theme.colors.foregroundMuted : theme.colors.foreground }}>↑</Text>
                      </Pressable>
                      
                      <Pressable 
                        disabled={isLastChecked}
                        onPress={() => handleMoveDown(item.chainIndex as number)}
                        style={[
                          styles.iconBtn, 
                          { backgroundColor: isLastChecked ? 'transparent' : theme.colors.surface2 }
                        ]}
                      >
                        <Text style={{ color: isLastChecked ? theme.colors.foregroundMuted : theme.colors.foreground }}>↓</Text>
                      </Pressable>
                    </View>
                  </View>
                )}
              </View>
            );
          })
        )}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    gap: 12,
  },
  center: {
    padding: 24,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: 8,
  },
  warningBox: {
    padding: 8,
  },
  list: {
    borderWidth: 1,
    borderRadius: 8,
    maxHeight: 400,
  },
  row: {
    padding: 12,
    borderBottomWidth: 1,
    flexDirection: 'column',
    gap: 8,
  },
  mainContent: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  labelContainer: {
    flex: 1,
    justifyContent: 'center',
  },
  actionsContent: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    flexWrap: 'wrap',
    justifyContent: 'flex-end',
    gap: 8,
    paddingLeft: 44, // Align with text past the switch
  },
  selectorBtn: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 6,
  },
  orderControls: {
    flexDirection: 'row',
    gap: 4,
    marginLeft: 8,
  },
  iconBtn: {
    width: 28,
    height: 28,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: 14,
  }
});
