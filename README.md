# Asistente Canvas V2 (Windows / VS Code)

## Versión web rosada

Sitio: **https://elektraec.github.io/canvas-asistente-v2/**

La interfaz web en `web/` abre los ZIP de la V2, muestra entregas y notas, busca y filtra estudiantes y genera plantillas con los IDs reales de la rúbrica. Incluye un ejemplo ficticio que se activa explícitamente. Los archivos se procesan en memoria en el navegador; no se suben al repositorio. No hay evaluación automática ni conexión con OpenAI.

**GitHub Pages es estático:** para descargar evidencias o registrar notas en Canvas se necesita el servidor Python local. La lectura de ZIP y generación de plantillas no lo necesitan.

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe web_server.py
```

Abre **http://127.0.0.1:8765**; la conexión se configura automáticamente. También puedes abrir la web pública y colocar la clave temporal que muestra la terminal en **Conexión con Canvas · servidor local**. Permite el acceso a la red local si el navegador lo solicita. Si el navegador bloquea esa conexión, usa la dirección local. El servidor solo escucha en `127.0.0.1`, limita los orígenes admitidos y exige una clave de sesión para las operaciones.

El registro mantiene la validación del núcleo Python, añade una autorización de diez minutos y un solo uso, y vuelve a comprobar Canvas antes de escribir. Exige revisión docente y escribir `REGISTRAR`. Las pruebas de escritura usan simulaciones: no se han modificado notas reales para verificar esta versión.

### Desarrollo y publicación

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node --test tests/web.test.mjs
```

El workflow `.github/workflows/pages.yml` prueba ambas versiones y publica únicamente `web/` en GitHub Pages al hacer push a `main`. En el repositorio, **Settings → Pages → Source → GitHub Actions**. Las rutas de recursos son relativas y funcionan bajo el nombre del repositorio. JSZip 3.10.1 está incluido con su licencia en `web/vendor/`; las fuentes tienen alternativas locales.

### Análisis de la app original

- `app.py`: interfaz Tkinter de escritorio, ahora con tema rosado.
- `canvas_core.py`: cliente Canvas, exportación ZIP, validación de rúbricas y registro supervisado; se conserva como núcleo compartido.
- `web_server.py`: adaptación HTTP local de ese núcleo, sin almacenar credenciales.
- `web/`: interfaz estática compatible con GitHub Pages, sin proceso de compilación.
- `.gitignore`: excluye entorno virtual, ejecutables, compilaciones y paquetes ZIP. No publiques tokens ni archivos académicos.

---

Aplicación local con interfaz gráfica. **No utiliza la API de OpenAI**; la evaluación académica se realiza en el chat normal y requiere aprobación docente.

## Instalación

1. Descomprime `Canvas_Asistente_V2.zip`.
2. Abre la carpeta `canvas_asistente_v2` en VS Code.
3. Abre **Terminal → Nueva terminal** y ejecuta:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

El token personal de Canvas debe tener permisos de lectura y, cuando se use registro, permisos para administrar notas. No pegues el token en ChatGPT ni lo incluyas en archivos.

## Paso 1: descargar

- Pega la URL HTTPS completa de la tarea en Canvas y tu token.
- Pulsa **Descargar entregas y generar ZIP**.
- La tabla muestra los registros, estados, notas previas y número de archivos.
- Adjunta el ZIP al chat normal para el análisis académico. Contiene datos personales y requiere comprobar que su uso cumpla las políticas institucionales.
- El ZIP incorpora `resumen_entregas.json`, `tarea_canvas.json` y las evidencias descargables desde Canvas. Puede haber entregas externas no descargables.

## Paso 2: plantilla y evaluación

- Pulsa **Crear plantilla JSON para evaluar en ChatGPT**. Contiene una fila por estudiante entregado, sin nota previa, con los IDs reales de los criterios.
- El JSON tiene este esquema (ejemplo ilustrativo, IDs ficticios):

```json
{
  "schema_version": 2,
  "canvas_base": "https://mi-campus.instructure.com",
  "course_id": 123,
  "assignment_id": 456,
  "assignment_title": "Tarea 1",
  "grades": [
    {
      "user_id": 789,
      "student_name": "Estudiante de ejemplo",
      "total": 2.0,
      "comment": "Fortaleza ...; mejora ...",
      "criteria": [
        {"criterion_id": "_abc", "points": 2.0, "rating_id": "rat_1", "comment": "Evidencia localizada en ..."}
      ]
    }
  ]
}
```

Los `criterion_id` y `rating_id` **deben provenir del ZIP real**, nunca inventarse. Para resultados con puntuaciones intermedias, `rating_id` puede ser `null`; el sistema verifica cualquier nivel que se haya especificado, sin inferirlo de los puntos. Los puntajes por criterio deben sumar el total. No uses el JSON incompleto de plantilla como si fueran calificaciones aprobadas.

## Paso 3: registro

- En la pestaña **2 · Registrar evaluaciones**, selecciona el JSON aprobado.
- Opcionalmente activa **Incluir ceros**. Solo se propondrán para casos conservadores: tarea individual, fecha vencida, sin fechas diferenciadas, sin entrega y sin nota previa. Los posibles casos de prórrogas requieren comprobación manual; si la tarea tiene excepciones, los ceros automáticos se deshabilitan.
- Pulsa **Validar contra Canvas**. El sistema consulta la rúbrica y las entregas actuales. Se bloquea ante diferencias de identificadores, puntuaciones inválidas o notas existentes.
- Revisa la tabla y confirma dos veces, incluyendo escribir `REGISTRAR`.
- La app escribe estudiante por estudiante, vuelve a consultar Canvas y clasifica cada resultado como CONFIRMADO, REVISAR, OMITIDO o ERROR. Guarda el reporte JSON.
- Comprueba también los niveles visuales y comentarios en SpeedGrader, especialmente si el servidor no devolvió todos los campos necesarios para la verificación automatizada.

## Límites y seguridad

- **La V2 no se ha probado con una escritura real a tu Canvas**. Realiza el primer registro con una tarea de prueba o un estudiante autorizado y revisa SpeedGrader antes de un lote real.
- No sobreescribe notas existentes, no maneja calificación grupal compartida, moderada o anónima y no asigna ceros si hay vencimientos diferenciados.
- No importa ni crea rúbricas nuevas aún; reutiliza la rúbrica real de la tarea.
- No publica explícitamente calificaciones ocultas, pero los cambios podrían ser visibles según la política de publicación ya configurada en Canvas. Revísala antes de registrar.
- La API puede asociar un nivel `rating_id` y puntuación `points` de distintas formas según la configuración; por ello se realiza verificación y se reportan discrepancias.
- Los archivos JSON/ZIP/reportes contienen información académica identificable: guárdalos en un lugar seguro.
- Si falla la red después de enviar una nota, **no repitas a ciegas el registro**: consulta primero el estado en Canvas para evitar comentarios duplicados.

## Referencias

- [Canvas Submissions API](https://developerdocs.instructure.com/services/canvas/resources/submissions)
- [Canvas Rubrics API](https://developerdocs.instructure.com/services/canvas/resources/rubrics)
