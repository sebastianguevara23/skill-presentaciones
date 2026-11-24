# Google Slides

Montserrat es una fuente de Google: en Slides se ve igual sin instalar nada.

## Traer un deck desde Google Slides

Una presentación de Google no es un PPTX. En la carpeta de Google Drive para escritorio
aparece como un acceso directo (`.gslides`) que no se puede leer. La persona tiene que
descargarla:

1. Abrir la presentación en Google Slides.
2. Archivo → Descargar → Microsoft PowerPoint (.pptx).
3. Mover el archivo a la carpeta de trabajo (o decirte dónde quedó, normalmente Descargas).

Si las herramientas de Google Drive están conectadas en tu sesión y el archivo es chico,
puedes intentar descargarlo tú. Si falla o pesa mucho, pídele a la persona que lo descargue.

## Llevar el resultado a Google Slides

Opción simple, sin instalar nada:

1. En drive.google.com: Nuevo → Subir archivo → elegir el PPTX final.
2. Doble clic en el archivo subido → Abrir con → Presentaciones de Google.
3. Archivo → Guardar como Presentaciones de Google. Desde ahí se edita y se comparte como
   cualquier presentación.

Con Google Drive para escritorio: copia el PPTX final a una carpeta de «Mi unidad», espera
a que se sincronice y sigue desde el paso 2.

Si en la configuración de Drive está activo «Convertir archivos subidos al formato de
editor de Documentos de Google», el paso 3 no hace falta.

### Subirlo tú, con el conector de Google Drive

Si la sesión tiene las herramientas de Google Drive, puedes subir y convertir el PPTX tú
mismo. Pide permiso antes: subir un archivo es publicarlo en su Drive. `create_file` acepta
el archivo por referencia (`base64Content: "sha256:<hash>:<ruta>"`), así que un deck de unos
MB entra sin pasar el contenido por la conversación, y lo deja como presentación de Google.

**Cada ronda genera un enlace nuevo.** El conector no puede reemplazar el contenido de una
presentación que ya existe. Díselo a la persona en la primera subida, y en cada ronda sigue
estos pasos:

1. Sube la versión nueva y dale el enlace.
2. Renombra la anterior agregándole «(versión anterior)».
3. Mándala a la papelera solo cuando la persona diga que sí.

## Revisar en Google

**Ábrelo con Presentaciones de Google, no con la vista previa de Drive.** La vista previa
(la que muestra «Página N / M» abajo) no carga Montserrat y dibuja otra letra, así que parece
un error de fuente que no existe. Avísalo cuando entregues el enlace, y si la persona manda
capturas, pídelas desde Presentaciones de Google.

Google corta las líneas un poco distinto que LibreOffice. Después de convertir, pide a la
persona que mire las slides con mucho texto o con textos justos de ancho. Si un título salta
a dos líneas o un texto se sale de su card:

- Arréglalo en el PPTX (caja un poco más ancha o texto en otra unidad) y vuelve a subir, o
- Si la persona prefiere, que lo ajuste directo en Slides: es un cambio de diseño, no de
  contenido.

Si tienes las herramientas de Google Slides conectadas, puedes leer la presentación
convertida y pedir la miniatura de una slide. La miniatura llega como un enlace temporal:
descárgalo y mira la imagen.
