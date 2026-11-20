# App de iPhone — EN PAUSA

Esta app (Expo + módulo nativo en `modules/offline-pipeline/ios`) fue la primera versión
del proyecto: traducía voz con los frameworks de Apple en el dispositivo y la leía en voz alta.
El uso real (un intérprete que lee una ayuda en pantalla) lo cubre ahora la versión web
(`apps/web` + `apps/whisper-server`), así que la app queda congelada.

## Fallos conocidos (sin corregir)

1. **El reconocimiento se apaga tras la primera frase**: `SpeechRecognitionManager.swift`
   no reinicia la tarea después de un resultado final o un error, y `SFSpeechRecognizer`
   está pensado para dictados cortos. Solución: migrar a `SpeechAnalyzer` + `SpeechTranscriber` (iOS 26).
2. **La app se escucha a sí misma**: la sesión de audio usa `.playAndRecord` con `.defaultToSpeaker`
   y `mode: .measurement` (sin cancelación de eco), así que el micrófono capta la voz sintetizada.
3. **Eventos de voz mezclados**: en `AppleTTSEngine.ts` los avisos de «terminado» son globales y
   `processTranslationAndTts()` se lanza en paralelo; el fin de una frase cierra todas las pendientes.
4. **El texto solo aparece al terminar el audio**, y `outputMode` no se usa (siempre habla).
5. **`speechStart` es falso**: se dispara con el primer bloque de audio, no al empezar a hablar.
6. Solo funciona en iPhone con iOS 26; la carpeta `android/` no tiene implementación.

## Si se retoma

Llevar a la app lo que ya hace la web: sin voz sintetizada, texto parcial en vivo, ritmo de
lectura y línea guía, con `SpeechAnalyzer` para el reconocimiento y el framework `Translation`
de Apple para traducir (gratis y sin conexión).
