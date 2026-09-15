import { useMemo, useState } from "react";
import {
  KeyboardAvoidingView,
  Platform,
  Pressable,
  SafeAreaView,
  ScrollView,
  StyleSheet,
  Text,
  View
} from "react-native";
import { Mic, PauseCircle, Square, Volume2, WifiOff } from "lucide-react-native";
import { StatusBar } from "expo-status-bar";
import { defaultTranslatorSettings, type RealtimeTranslatorSettings } from "@traductor/shared";
import { useRealtimeTranslator } from "./hooks/useRealtimeTranslator";
import { colors } from "./theme/colors";

export default function App() {
  const [settings, setSettings] = useState<RealtimeTranslatorSettings>(defaultTranslatorSettings);
  const { status, sourceText, translatedText, turns, error, latencyMs, start, pause, stop } = useRealtimeTranslator();

  const isLive = status === "live" || status === "connecting";
  const statusLabel = useMemo(() => {
    switch (status) {
      case "connecting":
        return "Conectando";
      case "live":
        return "Escuchando";
      case "stopping":
        return "Pausando";
      case "error":
        return "Error";
      default:
        return "Listo";
    }
  }, [status]);

  function startSession() {
    start({ apiBaseUrl: "offline://local", settings });
  }

  return (
    <SafeAreaView style={styles.safeArea}>
      <StatusBar style="dark" />
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={styles.keyboard}>
        <ScrollView contentContainerStyle={styles.page}>
          <View style={styles.header}>
            <View>
              <Text style={styles.eyebrow}>Traductor local</Text>
              <Text style={styles.title}>Español → Alemán</Text>
            </View>
            <View style={[styles.statusPill, status === "live" && styles.statusLive, status === "error" && styles.statusError]}>
              <Text style={[styles.statusText, status === "live" && styles.statusLiveText, status === "error" && styles.statusErrorText]}>
                {statusLabel}
              </Text>
            </View>
          </View>

          <View style={styles.panel}>
            <View style={styles.offlineRow}>
              <WifiOff color={colors.success} size={18} />
              <Text style={styles.offlineText}>Offline ready</Text>
            </View>
            <Text style={styles.inputLabel}>Modelo local</Text>
            <Text style={styles.modelText}>STT + traducción + TTS cargados localmente</Text>
          </View>

          <View style={styles.livePanel}>
            <View style={styles.liveHeader}>
              <Volume2 color={colors.primary} size={20} />
              <Text style={styles.liveTitle}>Traducción actual</Text>
            </View>
            <Text style={styles.translationText}>{translatedText || "Pulsa iniciar y habla junto al micrófono."}</Text>
            <View style={styles.divider} />
            <Text style={styles.sourceLabel}>Original detectado</Text>
            <Text style={styles.sourceText}>{sourceText || "Esperando audio..."}</Text>
          </View>

          {latencyMs !== null ? (
            <View style={styles.metricCard}>
              <Text style={styles.metricLabel}>Latency</Text>
              <Text style={styles.metricValue}>{latencyMs} ms</Text>
            </View>
          ) : null}

          {error ? <Text style={styles.errorText}>{error}</Text> : null}

          <View style={styles.buttonRow}>
            <Pressable accessibilityRole="button" onPress={startSession} style={[styles.primaryButton, isLive && styles.stopButton]}>
              {isLive ? <Square color={colors.surface} fill={colors.surface} size={18} /> : <Mic color={colors.surface} size={20} />}
              <Text style={styles.primaryButtonText}>{isLive ? "Detener" : "Iniciar"}</Text>
            </Pressable>

            <Pressable accessibilityRole="button" onPress={pause} style={styles.secondaryButton}>
              <PauseCircle color={colors.primaryDark} size={18} />
              <Text style={styles.secondaryButtonText}>Pausar</Text>
            </Pressable>
          </View>

          {turns.length > 0 ? (
            <View style={styles.history}>
              <Text style={styles.historyTitle}>Últimas frases</Text>
              {turns.map((turn) => (
                <View key={turn.id} style={styles.turn}>
                  <Text style={styles.turnTranslation}>{turn.translation}</Text>
                  {turn.source ? <Text style={styles.turnSource}>{turn.source}</Text> : null}
                </View>
              ))}
            </View>
          ) : null}
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: colors.page
  },
  keyboard: {
    flex: 1
  },
  page: {
    gap: 18,
    padding: 20,
    paddingBottom: 36
  },
  header: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "flex-start",
    gap: 12
  },
  eyebrow: {
    color: colors.primary,
    fontSize: 13,
    fontWeight: "800",
    textTransform: "uppercase"
  },
  title: {
    marginTop: 3,
    color: colors.ink,
    fontSize: 28,
    fontWeight: "800"
  },
  statusPill: {
    borderRadius: 8,
    borderWidth: 1,
    borderColor: colors.line,
    backgroundColor: colors.surface,
    paddingHorizontal: 10,
    paddingVertical: 8
  },
  statusLive: {
    backgroundColor: colors.softPrimary,
    borderColor: colors.primary
  },
  statusError: {
    backgroundColor: "#FCEEEE",
    borderColor: colors.danger
  },
  statusText: {
    color: colors.muted,
    fontSize: 12,
    fontWeight: "800"
  },
  statusLiveText: {
    color: colors.primaryDark
  },
  statusErrorText: {
    color: colors.danger
  },
  panel: {
    backgroundColor: colors.surface,
    borderColor: colors.line,
    borderRadius: 8,
    borderWidth: 1,
    gap: 10,
    padding: 14
  },
  offlineRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8
  },
  offlineText: {
    color: colors.success,
    fontSize: 14,
    fontWeight: "800"
  },
  inputLabel: {
    color: colors.muted,
    fontSize: 12,
    fontWeight: "700",
    textTransform: "uppercase"
  },
  modelText: {
    color: colors.ink,
    fontSize: 15,
    lineHeight: 22,
    fontWeight: "600"
  },
  livePanel: {
    backgroundColor: colors.surface,
    borderColor: colors.primary,
    borderRadius: 8,
    borderWidth: 1,
    gap: 12,
    padding: 16
  },
  liveHeader: {
    alignItems: "center",
    flexDirection: "row",
    gap: 8
  },
  liveTitle: {
    color: colors.primaryDark,
    fontSize: 14,
    fontWeight: "800",
    textTransform: "uppercase"
  },
  translationText: {
    color: colors.ink,
    fontSize: 25,
    fontWeight: "800",
    lineHeight: 32,
    minHeight: 96
  },
  divider: {
    backgroundColor: colors.line,
    height: 1
  },
  sourceLabel: {
    color: colors.muted,
    fontSize: 12,
    fontWeight: "800",
    textTransform: "uppercase"
  },
  sourceText: {
    color: colors.muted,
    fontSize: 16,
    lineHeight: 22,
    minHeight: 44
  },
  metricCard: {
    backgroundColor: colors.surface,
    borderColor: colors.line,
    borderRadius: 8,
    borderWidth: 1,
    paddingVertical: 10,
    paddingHorizontal: 12
  },
  metricLabel: {
    color: colors.muted,
    fontSize: 12,
    fontWeight: "700",
    textTransform: "uppercase"
  },
  metricValue: {
    color: colors.ink,
    fontWeight: "800",
    fontSize: 18,
    marginTop: 4
  },
  errorText: {
    backgroundColor: "#FCEEEE",
    borderColor: colors.danger,
    borderRadius: 8,
    borderWidth: 1,
    color: colors.danger,
    fontSize: 14,
    fontWeight: "700",
    padding: 12
  },
  buttonRow: {
    flexDirection: "row",
    gap: 10
  },
  primaryButton: {
    flex: 1,
    alignItems: "center",
    backgroundColor: colors.primary,
    borderRadius: 8,
    flexDirection: "row",
    gap: 10,
    justifyContent: "center",
    minHeight: 56
  },
  stopButton: {
    backgroundColor: colors.danger
  },
  primaryButtonText: {
    color: colors.surface,
    fontSize: 17,
    fontWeight: "800"
  },
  secondaryButton: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    backgroundColor: colors.surface,
    borderColor: colors.line,
    borderRadius: 8,
    borderWidth: 1,
    minWidth: 120,
    minHeight: 56
  },
  secondaryButtonText: {
    color: colors.primaryDark,
    fontSize: 15,
    fontWeight: "800"
  },
  history: {
    gap: 10
  },
  historyTitle: {
    color: colors.ink,
    fontSize: 18,
    fontWeight: "800"
  },
  turn: {
    backgroundColor: colors.surface,
    borderColor: colors.line,
    borderRadius: 8,
    borderWidth: 1,
    gap: 6,
    padding: 12
  },
  turnTranslation: {
    color: colors.ink,
    fontSize: 16,
    fontWeight: "800",
    lineHeight: 22
  },
  turnSource: {
    color: colors.muted,
    fontSize: 14,
    lineHeight: 20
  }
});
