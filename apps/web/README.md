# Apuntador de interpretación (versión web)

Página única para que el intérprete vea, en tiempo real, lo que dice el predicador
y una traducción automática. Gratis, sin claves de API ni servidor.

## Requisitos
- Google Chrome 138+ (o Microsoft Edge 148+) en un **ordenador** (no móvil).
- Internet para el reconocimiento de voz (lo hace el navegador).
- La traducción corre en el propio ordenador; la primera vez descarga el modelo del idioma.

## Uso
1. Abre la página en Chrome:
   - en local: `cd apps/web && python3 -m http.server 8080` y abre http://localhost:8080
   - o publícala gratis en GitHub Pages / Netlify (debe ser https).
2. Elige idiomas (por defecto Alemán → Español) y pulsa **Empezar**.
3. Permite el micrófono.
4. En **Ajustes** edita el glosario de términos de la iglesia. Va por secciones según el
   par de idiomas (`[de>es]`, `[fr>es]`, `[en>es]`…); solo se aplica la del par activo.

## Con la transmisión en vivo al lado
1. Pega el enlace del directo (YouTube, Vimeo, Facebook…) y pulsa **Mostrar al lado**.
   El video aparece a la izquierda y la traducción a la derecha (el separador se puede arrastrar).
2. En **Audio** deja «De la transmisión (esta pestaña)» y pulsa **Empezar**.
3. Chrome pregunta qué compartir: elige **esta pestaña** y activa **«Compartir también el audio de la pestaña»**.
   Así se traduce el audio del directo y **no** la voz del intérprete.
4. El intérprete escucha el directo con auriculares y habla por su micrófono como siempre.

Si una página no se deja mostrar dentro (algunas lo bloquean), ábrela en otra pestaña
y elige esa pestaña al compartir el audio.

Nota: el video debe abrirse desde http://localhost o https (no con doble clic en el archivo),
si no YouTube no lo reproduce.

## Consejos de audio
La calidad depende sobre todo del audio: mejor un cable desde la mesa de sonido
(o un micrófono cerca del altavoz) que el micrófono del portátil al fondo de la sala.

## Ritmo de lectura y línea guía
- **Lectura**: la traducción se hace al instante, pero el texto aparece palabra a palabra al
  ritmo elegido (60–400 palabras/min, o «sin límite» al tope). Hace una pausa breve en cada punto.
- **Acelerar si me retraso**: si se acumula mucho texto pendiente, acelera suavemente (hasta 2,5×).
- **Al día (N)**: muestra de golpe las N palabras pendientes. Se pone naranja si vas muy atrás.
- **Línea guía** (naranja): la palabra que toca leer siempre queda justo encima. Se mueve con el
  control «Altura» o arrastrando el círculo ↕.
- Teclado: ↑/↓ cambia la velocidad, **Fin** = al día. Si mueves el texto con la rueda del ratón,
  el desplazamiento automático se pausa 6 segundos.
- Idiomas: alemán, alemán (Suiza), francés, francés (Suiza), inglés, español, italiano, portugués.
  El motor Whisper es solo para alemán y suizo alemán; para francés e inglés se usa el motor Chrome.
