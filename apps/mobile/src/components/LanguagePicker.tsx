import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import type { LanguageCode, LanguageOption } from "@traductor/shared";
import { colors } from "../theme/colors";

type LanguagePickerProps = {
  label: string;
  value: LanguageCode;
  options: LanguageOption[];
  onChange: (language: LanguageCode) => void;
};

export function LanguagePicker({ label, value, options, onChange }: LanguagePickerProps) {
  return (
    <View style={styles.wrapper}>
      <Text style={styles.label}>{label}</Text>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.row}>
        {options.map((language) => {
          const selected = language.code === value;

          return (
            <Pressable
              accessibilityRole="button"
              accessibilityState={{ selected }}
              key={language.code}
              onPress={() => onChange(language.code)}
              style={[styles.option, selected && styles.selectedOption]}
            >
              <Text style={[styles.optionText, selected && styles.selectedText]}>{language.nativeLabel}</Text>
            </Pressable>
          );
        })}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  wrapper: {
    gap: 8
  },
  label: {
    color: colors.muted,
    fontSize: 12,
    fontWeight: "700",
    textTransform: "uppercase"
  },
  row: {
    gap: 8,
    paddingRight: 16
  },
  option: {
    backgroundColor: colors.surface,
    borderColor: colors.line,
    borderRadius: 8,
    borderWidth: 1,
    minWidth: 96,
    paddingHorizontal: 12,
    paddingVertical: 10
  },
  selectedOption: {
    backgroundColor: colors.softPrimary,
    borderColor: colors.primary
  },
  optionText: {
    color: colors.ink,
    fontSize: 15,
    fontWeight: "700",
    textAlign: "center"
  },
  selectedText: {
    color: colors.primaryDark
  }
});
