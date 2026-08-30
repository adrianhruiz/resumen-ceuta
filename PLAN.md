# Resumen Ceuta — Plan

Resumen de lo publicado por la prensa local de Ceuta, agrupado por temas y
leíble de un vistazo, impreso en la terminal.

Fecha del plan: 2026-08-30 (revisado el mismo día: sesión de grilling, y
después plan de tareas y de tests)

---

## Brief

**Qué es.** Una herramienta de terminal que lee lo que publican los dos
periódicos de Ceuta, agrupa las noticias del día por temas y las imprime en una
pantalla que se lee de un vistazo.

**Para quién.** Para alguien que quiere enterarse de lo que ha pasado en Ceuta
sin abrir dos webs ni cribar a mano la opinión, la crónica y el reportaje.

**El flujo principal.** Se escribe `resumen`. La app lee ambos feeds, guarda lo
nuevo, pide a Gemini que clasifique y agrupe **solo** los artículos que todavía
no ha resumido, y escribe en `stdout` la cabecera de cobertura y los temas del
día.

**Lo que no es.**

- No es un archivo consultable: no hay comando para días pasados.
- No es un proceso en segundo plano: no hay cron ni servicio.
- No es un lector: no muestra el cuerpo de los artículos, solo una línea por
  hecho.
- No filtra por ámbito geográfico.

---

## Hallazgos sobre las fuentes

Medido dos veces el 2026-08-30: al diseñar, y otra vez al escribir la ingesta
(T5). La segunda medición corrigió tres cosas de la primera, marcadas abajo.

| | El Faro | El Pueblo |
|---|---|---|
| Feed | `https://elfarodeceuta.es/feed/` | `https://www.elpueblodeceuta.es/rss/` |
| Nota | `/rss` redirige a `/feed/` | **`/feed/` devuelve 404** |
| Items en el feed | **exactamente 10** (dos medidas) | 137 |
| Ventana temporal | 15:23 → 17:54 = **2,5 h** | 7 feb → 30 ago = **204 días** |
| Ritmo | ≥35/día, y en esa franja ~96/día | **~11/día** (últimos 7 días) |
| Contenido | completo (`content:encoded`) | **solo la entradilla; sin `content:encoded`** |
| Clasificación | `<category>` | sección en la URL (`/sec/politica/`) |
| `guid` | `isPermaLink="false"`, `?p=1436869` | `isPermaLink="true"`, `..._TIPO_ID.html` |
| Tipo en el `guid` | — | **`_1_` artículo (124), `_3_` fotogalería (13)** |
| `pubDate` | `+0000`, ya en UTC | `+0000`, ya en UTC |
| Sin entradilla | — | 4 items, todos de opinión |

Las tres correcciones de la segunda medición, cada una con test que la sostiene:

- **El Pueblo no sirve el cuerpo.** Solo `<description>`. La primera medición
  dijo lo contrario. El `body` queda vacío para esa fuente, lo cual no afecta
  al prompt —que solo manda título y entradilla— pero cierra la puerta a
  releer el cuerpo más adelante sin visitar la web.
- **El Pueblo publica ~11/día, no 3,7.** Los 137 items abarcan 204 días porque
  arrastran una cola de items viejos, pero 78 de ellos son de los últimos 7
  días. El archivo sigue siendo real; el ritmo era tres veces mayor de lo
  estimado.
- **El dígito del `guid` de El Pueblo es un tipo de contenido**, no parte fija
  del formato. El patrón `_1_(\d+)` del plan original habría descartado en
  silencio las 13 fotogalerías.

Consecuencias que condicionan el diseño:

1. **"Las últimas 10 de cada fuente" no es una unidad comparable.**
   10 de Faro = media mañana; 10 de El Pueblo = ~3 días.
2. **El feed de Faro es una ventana deslizante de 10 items,** sin archivo. Lo
   que no se capture mientras está visible se pierde para siempre.
3. **El feed de El Pueblo es su propio archivo.** Una sola lectura rellena
   meses hacia atrás. Perder ejecuciones no le afecta.
4. **La categoría `Noticias` de Faro no filtra nada.** La llevan 9 de cada 10
   items, incluido `En la Piel | Valdeaguas, una batería en el olvido`, que es
   justo el reportaje que hay que excluir. Solo `Opinión` discrimina. La
   distinción noticia / crónica **no se puede resolver con metadatos**.
5. **El `guid` de El Pueblo lleva el titular incrustado** como slug
   (`.../pp-denuncia-gobierno-sigue-fallando_1_1187097.html`). Si corrigen un
   titular cambia el `guid` y el artículo entra duplicado. La parte estable es
   **el número final**, `1187097`, único entre tipos de contenido.
6. **Coste irrelevante en tokens.** Un día entero son ~4k tokens con título +
   `description`. Cabe de sobra en Gemini Flash.
7. **Las fotogalerías se ingieren como todo lo demás.** El patrón captura
   cualquier tipo (`_\d+_(\d+)\.html`) porque filtrar aquí sería exactamente
   la clasificación por metadatos que este proyecto le encargó al modelo, y
   porque una fotogalería puede ser la única cobertura de un hecho.
8. **La entradilla puede faltar.** Los artículos de opinión de El Pueblo llegan
   con titular y nada más, así que el prompt tiene que tolerar su ausencia en
   vez de asumir que siempre hay texto.

---

## Arquitectura

Una sola fase, disparada por el usuario. No hay proceso programado: **todo
ocurre en el momento en que se ejecuta `resumen`.**

```
resumen
  │
  ├─ 1. leer ambos feeds ──> INSERT OR IGNORE ──> articles + fetches
  │
  ├─ 2. ids = artículos de hoy (día natural Europe/Madrid)
  │
  ├─ 3. ¿ids == covered_ids, y prompt y modelo intactos?
  │        sí ──> renderizar desde payload                    0 llamadas
  │        no ──> 1 llamada con (payload, ids - covered_ids)  ──> payload'
  │
  ├─ 4. si hoy tiene < 5 noticias ──> repetir 2-3 para ayer
  │
  └─ 5. cabecera de cobertura + payload ──> stdout
```

### Esquema

```sql
CREATE TABLE IF NOT EXISTS articles (
    source      TEXT NOT NULL,      -- 'faro' | 'pueblo'
    external_id TEXT NOT NULL,      -- stable id parsed out of the guid
    guid        TEXT NOT NULL,      -- raw guid, kept for reference only
    title       TEXT NOT NULL,
    description TEXT,
    body        TEXT,               -- plain text, paragraphs kept, no images
    url         TEXT NOT NULL,
    pubdate     TEXT NOT NULL,      -- ISO 8601 UTC
    day         TEXT NOT NULL,      -- YYYY-MM-DD, Europe/Madrid
    fetched_at  TEXT NOT NULL,
    PRIMARY KEY (source, external_id)
);
CREATE INDEX IF NOT EXISTS idx_articles_day ON articles(day);

-- One row per feed read. Without it there is no way to tell
-- "the outlet published nothing" from "the app was never opened".
CREATE TABLE IF NOT EXISTS fetches (
    source     TEXT NOT NULL,
    fetched_at TEXT NOT NULL,       -- ISO 8601 UTC
    ok         INTEGER NOT NULL,
    item_count INTEGER
);

CREATE TABLE IF NOT EXISTS summaries (
    day          TEXT PRIMARY KEY,  -- YYYY-MM-DD, Europe/Madrid
    covered_ids  TEXT NOT NULL,     -- JSON array, sorted: ["faro:1436869", ...]
    input_hash   TEXT NOT NULL,     -- sha256(covered_ids + prompt + model id)
    payload      TEXT NOT NULL,     -- JSON, see below
    generated_at TEXT NOT NULL
);
```

`external_id` se extrae al ingerir: el número de `?p=` en Faro, el `_1_(\d+)`
en El Pueblo. El `guid` crudo se guarda pero **no se deduplica por él.**

`day` se deriva de `pubdate` convirtiendo a `Europe/Madrid` en el momento de
insertar. Se almacena en UTC y se corta en local: lo publicado entre las 22:00
y las 23:59 UTC pertenece al día siguiente para quien lo lee.

### La caché

El objetivo es que la API key se use lo menos posible. Con ejecución a
demanda, hashear el día entero sería lo peor posible: cada ejecución trae
noticias nuevas, el hash cambia y se reprocesaría **todo** el día desde cero.
Así que el hash no invalida, **sincroniza**:

- La comprobación cuesta **cero en API**: se lee de SQLite y se compara.
- Ejecución sin noticias nuevas desde la anterior → **cero llamadas.**
- Ejecución con 10 noticias nuevas → **una** llamada que paga esas 10 más un
  JSON de contexto corto, no las 22 del día.
- El gasto diario queda acotado por el **número de noticias distintas**, no
  por cuántas veces se abra la app.
- El identificador del modelo y la plantilla del prompt entran en el
  `input_hash`: tocar el prompt regenera lo que toca sin acordarse de nada.

`resumen --force` se salta el paso 3. Cortocircuitos que no cuestan llamada:
día con cero artículos → `Sin noticias`; día ya cubierto → render directo.

### Llamada a Gemini

Una por ejecución como máximo, `temperature=0`, tope de **3 intentos** con
backoff exponencial (1 s y 2 s), timeout de 90 s y **el reintento automático
del SDK desactivado**: si google-genai reintenta por debajo, la política de
tres intentos es decorativa y un modelo caído se convierte en un cuelgue de
minutos en vez de un error. Medido el 2026-08-30. Recibe el `payload` actual como contexto y solo los
artículos de `ids - covered_ids`, con **título + `description`**: la
entradilla del RSS ya trae el qué-quién-dónde, que es todo lo que necesita una
línea de resumen. El `body` se guarda pero no se envía.

En esa llamada el modelo clasifica noticia frente a opinión / crónica /
reportaje / entrevista, agrupa lo que cuenta el mismo hecho aunque esté
redactado distinto en cada medio, y encaja cada grupo en la taxonomía cerrada:

```
Frontera · Política · Sucesos · Economía · Sanidad ·
Sociedad · Deportes · Cultura · Otros
```

Devuelve **JSON, no texto formateado**:

```json
{
  "temas": [
    {"tema": "Frontera", "entradas": [
      {"texto": "prisión para los cuatro detenidos por la emboscada a militares",
       "ids": ["faro:1436869", "pueblo:1187097"]}
    ]}
  ],
  "descartados": ["faro:1436802"]
}
```

`descartados` es imprescindible: `covered_ids` incluye lo descartado, así que
sin ese registro la siguiente ejecución no sabría que ya se juzgó.

Se escribe en `summaries` **solo si valida**: JSON bien formado, todo `tema`
dentro de la taxonomía, todo `id` conocido, y
`union(entradas.ids, descartados) == ids enviados`. Esa última comprobación es
la que caza una respuesta truncada. Un fallo no deja fila, así que la
siguiente ejecución reintenta con normalidad.

Sin filtro geográfico: entra todo lo que publiquen.

### Salida

Solo `stdout`; el progreso va por `stderr` para no ensuciar lo que se canalice.
El formateo se hace en Python a partir del JSON, no lo genera el modelo. Eso
permite cambiar la presentación sin volver a llamar a la API, e imponer el
orden estable de temas en código en vez de confiar en que el modelo obedezca.
Los temas vacíos no se imprimen.

La cabecera se renderiza **fuera** de la caché, a partir de `fetches`, y
declara la cobertura real:

```
Día 30 de agosto · 22 noticias
El Pueblo: completo hasta 20:14 · Faro: 3 lecturas (parcial)

Frontera: prisión para los cuatro detenidos por la emboscada
  a militares; expulsadas dos mujeres con DNI falso
Política: el Gobierno aprueba 165M en ayudas; Vox anuncia
  acciones legales contra No Name Kitchen
Sociedad: 200 motos reclaman mejoras en la seguridad vial
```

Si hoy tiene menos de 5 noticias, se imprime también el bloque de ayer,
etiquetado. Hoy y ayer son dos filas independientes de `summaries` con su
propia caché, así que sacar el de ayer cuesta una llamada la primera vez de la
mañana y cero el resto del día.

Degradación: fuente caída → se resume con la otra y la cabecera lo dice.
Gemini con error tras 3 intentos → error claro, sin escribir caché.

**Solo se aborta cuando no hay nada que enseñar**: ninguna fuente legible *y*
nada guardado del día. Si esta mañana sí se leyó y ahora la red está caída, se
imprime lo guardado y la cabecera añade `ahora caído` a la fuente que ha dejado
de responder. Es una corrección al plan de tests, que decía abortar siempre que
cayeran las dos: negarse a imprimir un resumen que ya existe es peor para quien
lee que enseñarlo con una cabecera honesta.

Una fuente que responde `200` con una página HTML no es un día tranquilo: se
detecta por `feed.version` vacío, porque `bozo` no lo distingue y sin esa
comprobación quedaría registrado como «no publicaron nada».

---

## Instalación y uso

Arch marca el Python del sistema como *externally managed* (PEP 668), así que
un entorno aislado es obligatorio.

```bash
mise use -g uv@latest            # o 'sudo pacman -S uv'
uv tool install --editable .     # deja 'resumen' en ~/.local/bin
```

`uv` se instaló por mise y no por pacman (2026-08-30): `sudo` no tenía terminal
para pedir la contraseña, y mise ya estaba en uso para el resto de
herramientas. Queda en `~/.config/mise/config.toml`, sin root y reversible con
`mise unuse -g uv`.

Con `[project.scripts] resumen = "resumen.cli:main"` en `pyproject.toml`.
`--editable` hace que tocar el código se refleje sin reinstalar.

```
resumen            # hoy, y ayer también si hoy va flojo
resumen --force    # regenera ignorando la caché
```

Añadir una dependencia obliga a reinstalar la herramienta
(`uv tool install --editable . --reinstall`): el modo editable refleja el
código, no el conjunto de dependencias.

No hay argumento de fecha ni subcomando `init`: el esquema se crea con
`CREATE TABLE IF NOT EXISTS` en cada arranque. La primera ejecución crea la BD,
trae los 36 días de El Pueblo y las 6,5 h de Faro, y ya sirve.

`RESUMEN_FARO_URL` y `RESUMEN_PUEBLO_URL` apuntan la app a otro sitio: un
servidor local en los tests, o un espejo si algún medio mueve su feed. Sin
ellas se usan las URL reales.

Rutas fijas, independientes del directorio desde el que se lance:

- BD: `~/.local/share/resumen-ceuta/db.sqlite3`
- Key: `~/.config/resumen-ceuta/env`, permisos `600`

Si falta la key, el arranque muere con un mensaje que dice qué fichero crear y
con qué contenido. Sin purga: ~150 KB/día guardando los cuerpos, unos 55 MB al
año, no merece código.

---

## Decisiones tomadas

| Cuestión | Decisión | Alternativa descartada |
|---|---|---|
| Disparo | Todo al ejecutar la app | Cron cada 3 h (rechazado por el usuario) |
| Unidad del resumen | Día natural Europe/Madrid | Día UTC; ventana móvil de 24 h |
| Alcance de la CLI | Solo hoy (+ ayer si hoy va flojo) | `resumen <fecha>` para cualquier día |
| Clave primaria | `(source, external_id)` | `guid` (cambia al editar titulares) |
| Caché | Incremental por día, sincroniza | Por fecha con `--force`; hash del día entero |
| Invalidación | `covered_ids` + hash de prompt y modelo | Solo `--force`; flag de parcial |
| Noticia vs crónica | Gemini clasifica y resume a la vez | Reglas por categoría (no funcionan) |
| Deduplicación | Gemini agrupa en el mismo prompt | Similitud de texto (titulares muy distintos) |
| Payload enviado | Título + `description` | Cuerpo completo (10× tokens, más ruido) |
| Cuerpo almacenado | Texto plano, sin imágenes | No guardarlo; HTML íntegro |
| Formato del modelo | JSON, render en Python | Texto ya formateado |
| Determinismo | `temperature=0` | Dejar el defecto |
| Reintentos | Tope de 3, backoff | Backoff sin tope |
| Temas | Lista fija | Temas emergentes (orden inestable) |
| Ámbito | Todo lo que publiquen | Solo Ceuta |
| Cabecera | Declara cobertura real | Solo el conteo |
| Empaquetado | `uv tool install --editable` | venv + lanzador a mano |
| Key | `~/.config/resumen-ceuta/env` | `.env` en el repo (no funciona fuera de él) |
| Fallos | Degradar y avisar | Abortar |

## Plan de tareas

Cuatro hitos. El hito 0 es un esqueleto que anda: el camino end-to-end más fino
que se puede ejecutar, sin pasar por Gemini. CI entra la segunda, antes que
nada sustancial, porque es la puerta que protege `develop`.

### Hito 0 — Esqueleto que anda

| Id | Tarea | Criterio de aceptación | Dep. | Rama |
|---|---|---|---|---|
| T1 | Andamiaje del proyecto y CLI | `uv tool install --editable .` deja `resumen` en el PATH; sale con 0, `stdout` limpio y el progreso por `stderr` | — | `feature/project-skeleton` |
| T2 | CI en GitHub Actions | La puerta corre en cada PR y en los push a `main` y `develop`; un PR con la suite roja no se puede mergear y el push directo a las dos ramas permanentes se rechaza | T1 | `feature/ci` |
| T3 | Rutas fijas y carga de la key | Sin `~/.config/resumen-ceuta/env` el arranque muere nombrando el fichero y su contenido; las rutas se redirigen por variable de entorno en los tests | T2 | `feature/config-paths` |
| T4 | Esquema SQLite y capa de acceso | `CREATE TABLE IF NOT EXISTS` en cada arranque; insertar dos veces el mismo `(source, external_id)` deja una fila; `articles_for_day` filtra por día | T3 | `feature/store` |
| T5 | Ingesta y parseo de los dos feeds | Contra fixtures: `external_id` correcto por fuente, cuerpo en texto plano sin imágenes, `pubdate` en UTC y `day` cortado en `Europe/Madrid` | T4 | `feature/feed-ingest` |
| T6 | Esqueleto end-to-end | Contra los feeds reales: crea la BD, registra las lecturas en `fetches` e imprime los titulares de hoy | T5 | `feature/walking-skeleton` |

### Hito 1 — El resumen

| Id | Tarea | Criterio de aceptación | Dep. | Rama |
|---|---|---|---|---|
| T7 | Prompt y cliente de Gemini | Una llamada por ejecución, `temperature=0`, modelo fijado en configuración, 3 intentos con backoff y timeout; tras el tercer fallo, error claro y ninguna fila escrita | T6 | `feature/gemini-client` |
| T8 | Validación del payload | Se rechaza sin dejar caché: JSON malformado, tema fuera de la taxonomía, id desconocido, o `union(entradas.ids, descartados) != ids enviados` | T7 | `feature/payload-validation` |
| T9 | Render en Python | Un payload fijo produce una salida idéntica al golden file: orden de temas estable, temas vacíos omitidos, sangrado de continuación | T8 | `feature/render` |
| T10 | Cabecera de cobertura | Se construye desde `fetches`, fuera de la caché: 3 lecturas de Faro → `Faro: 3 lecturas (parcial)`; El Pueblo → `completo hasta HH:MM` | T9 | `feature/coverage-header` |
| T11 | Resumen de hoy de punta a punta | Con feeds fixture y cliente de Gemini falso, imprime cabecera + temas | T10 | `feature/summarize-today` |

### Hito 2 — Caché, ayer y degradación

| Id | Tarea | Criterio de aceptación | Dep. | Rama |
|---|---|---|---|---|
| T12 | Caché incremental por día | Segunda ejecución sin noticias nuevas → **0 llamadas**; con 10 nuevas → **1** llamada que lleva solo esas 10 más el payload de contexto; tocar prompt o id de modelo regenera | T11 | `feature/incremental-cache` |
| T13 | Cortocircuitos y `--force` | Día con 0 artículos → `Sin noticias` sin llamada; día ya cubierto → render directo; `--force` se salta la comprobación | T12 | `feature/cache-shortcuts` |
| T14 | Bloque de ayer | Con menos de 5 noticias hoy se imprime también ayer, etiquetado y con su propia fila de `summaries`; la segunda ejecución del día no gasta llamada extra | T13 | `feature/yesterday-fallback` |
| T15 | Degradación ante fallos | Fuente caída → se resume con la otra, `fetches.ok=0` y la cabecera lo declara; Gemini agotado → error claro y caché intacta | T14 | `feature/graceful-degradation` |

### Hito 3 — Cierre

| Id | Tarea | Criterio de aceptación | Dep. | Rama |
|---|---|---|---|---|
| T16 | Presupuestos de rendimiento | La tabla de presupuestos pasa; el test falla si el prompt crece de más o si se hace más de una llamada | T15 | `feature/performance-budgets` |
| T17 | README e instalación desde cero | Un tercero instala y ejecuta siguiendo solo el README, sin leer este documento | T16 | `feature/readme` |

### Tareas cuya estimación desconfío

- **T5** — los dos feeds tienen formas distintas y los `external_id` salen de
  expresiones regulares contra RSS ajeno. Es donde más probable es descubrir un
  caso que rompa el mapeo.
- **T8** — validar la respuesta del modelo es fácil; decidir qué hacer con cada
  forma de fallo, no tanto.
- **T12** — la parte más sutil del diseño. El hash sincroniza en lugar de
  invalidar, y eso tiene bordes: artículo con `pubdate` retroactivo, día que
  cambia bajo los pies a medianoche.
- **T15** — provocar bien los modos de fallo cuesta más que el código que los
  maneja.

### Flujo de trabajo

Git flow con dos ramas permanentes. `develop` integra; `main` solo recibe
merges de `develop`. Una tarea, una rama `feature/…`, un PR a `develop` con la
suite entera en verde. Al cerrar el hito 3, PR de `develop` a `main` y tag.

---

## Plan de tests

### Decisiones para todo el proyecto

`pytest`, con `pytest-httpserver` para levantar un servidor HTTP real. Nada de
parchear la red con mocks.

```bash
uv run pytest             # todo salvo lo marcado 'network'
uv run pytest -m network  # contrato contra los feeds y Gemini reales
```

Qué es real y qué es falso. La regla: real en las costuras, falso solo donde
cuesta dinero o depende de terceros.

| Pieza | En los tests |
|---|---|
| SQLite | **Real siempre**, en `tmp_path`. Nunca en memoria: se prueba el fichero, que es lo que existe en producción |
| HTTP de los feeds | **Real**, contra un servidor local que sirve los fixtures. Se ejercita `feedparser`, los headers, el charset y los timeouts de verdad |
| Cliente de Gemini | **Falso**, inyectado por variable de entorno, devuelve respuestas grabadas y **cuenta las llamadas**. Ese contador es lo que protege la API key |
| Reloj y zona horaria | Congelados por inyección, no por parcheo global |

Fixtures crudos, tal como llegaron, en `tests/fixtures/feeds/` y
`tests/fixtures/gemini/`, con la fecha de captura en el nombre. Se refrescan
con `uv run python scripts/record_fixtures.py`, nunca a mano. Refrescar un
fixture y ver tests romper **es la señal**, no el accidente.

La puerta que protege `develop`:

```
ruff check . && ruff format --check . && uv run pytest
```

Los tests de contrato quedan **fuera** de esa puerta: dependen de servidores
ajenos y romperían PRs por motivos que no son el PR. Van en un cron nocturno
que abre issue al fallar.

**La puerta bloquea, no solo informa.** El ruleset `ramas permanentes` cubre
`refs/heads/main` y `refs/heads/develop` con cuatro reglas: PR obligatorio,
`gate` como check obligatorio en modo estricto (la rama tiene que estar al día
con su base), y prohibición de borrado y de push forzado. Sin excepciones para
nadie, administrador incluido.

Esto es lo que hizo público el repositorio el 2026-08-30: en privado con plan
gratuito la API responde `403 Upgrade to GitHub Pro or make this repository
public`, y sin ruleset la regla central de este plan sería solo una promesa.

Cobertura expresada en comportamientos, no en porcentaje. Ningún merge sin test
que cubra: el corte del día en `Europe/Madrid`, la deduplicación por
`external_id`, el tope de una llamada por ejecución, las cinco formas de
rechazar un payload, la degradación por fuente caída, y la ausencia de la key
en cualquier salida.

### Unitarios — lógica pura, sin E/S

- **`external_id`**: `?p=1436869` → `1436869`; `..._1_1187097.html` → `1187097`;
  guid con forma inesperada → se descarta con aviso, sin tumbar la ingesta.
- **Corte del día**: `2026-08-30T21:59Z` → día 30; `22:00Z` → día 31. Y los dos
  bordes de horario de verano, donde el desplazamiento pasa de +1 a +2.
- **HTML → texto plano**: párrafos separados, `<img>` y `<script>` fuera,
  entidades decodificadas, HTML mal cerrado no rompe.
- **`input_hash`**: determinista; cambia al tocar prompt, id de modelo o
  `covered_ids`; **no** cambia al reordenar los ids — de ahí que se almacenen
  ordenados.
- **Validación del payload**: el caso bueno y los cinco malos.
- **Render**: orden fijo de temas, temas vacíos omitidos, sangrado de
  continuación, títulos con comillas y guiones.
- **Umbral de ayer**: 4 noticias → sale ayer; 5 → no sale. Los dos lados.
- **Backoff**: la secuencia de esperas y el tope de 3, sin dormir de verdad.

### Integración — costuras reales contra fixtures

- Re-ingerir el mismo feed dos veces no duplica ni una fila.
- El esquema se crea en BD vacía y reabrirla es inocuo.
- Los 10 items de Faro y los 136 de El Pueblo entran completos desde el
  servidor local, con `content:encoded` y `content` respectivamente.
- `fetches` deja una fila por lectura: `ok=1` con `item_count`, `ok=0` al fallar.
- `summaries`: ida y vuelta del payload JSON, `covered_ids` ordenado al escribir.
- El cliente de Gemini, con una respuesta grabada, parsea → valida → escribe.

### Contrato — contra los servidores reales, fuera de la puerta

Existen para que **la deriva sea ruidosa**. Este documento se apoya en hechos
verificados el 2026-08-30, y ninguno de ellos es un contrato que nadie haya
firmado.

- `elfarodeceuta.es/feed/` → 200, XML válido, `guid` con `?p=`, `pubDate` en
  `+0000`, alrededor de 10 items. **Si un día sirve muchos más, el riesgo
  dominante desaparece y hay que revisar el diseño**: este test avisa igual de
  una buena noticia que de una mala.
- `elpueblodeceuta.es/rss/` → 200 con `content`; `/feed/` sigue en 404.
- El id de modelo fijado sigue existiendo y su respuesta valida contra el
  esquema.

### Funcionales / end-to-end — la CLI como la usa el usuario

Por `subprocess`, con `HOME` y `XDG_*` redirigidos a un temporal, feeds en
local y cliente falso:

- Máquina limpia: crea la BD, imprime cabecera y temas, sale 0.
- Segunda ejecución sin novedades: **salida idéntica y cero llamadas**.
- `--force`: regenera, exactamente una llamada.
- Sin key: sale distinto de 0, el mensaje nombra el fichero, `stdout` vacío.
- `resumen | cat`: por la tubería va solo el resumen.
- Día sin artículos: `Sin noticias`, sin llamada.
- Día flojo: dos bloques, el de ayer etiquetado.

### Rendimiento — presupuestos en números

| Qué | Presupuesto | Cómo se mide |
|---|---|---|
| **Llamadas a la API por ejecución** | **≤ 1**, y 0 con caché caliente | Contador del cliente falso. Es el presupuesto que importa |
| Ejecución completa con caché caliente | < 1,5 s | `perf_counter`, feeds en local |
| Ejecución con llamada al modelo | < 90 s, y ~30 s es lo normal | Medido: 29,3 s con 34 artículos el 2026-08-30 |
| Arranque hasta primera salida | < 400 ms | Sin red; mide importar y abrir la BD |
| Prompt de un día completo (~35 noticias) | ≤ 6.000 tokens | Conteo con el tokenizador; la estimación previa era ~4k |
| Ingesta de los 136 items de El Pueblo | < 2 s | BD en `tmp_path` |
| Crecimiento de la BD | ≤ 200 KB/día con cuerpos | La estimación previa era ~150 KB, 55 MB/año |

Umbrales holgados y marcados `perf`: un fallo tiene que significar regresión de
orden de magnitud, no ruido de la máquina de CI.

### Resiliencia

- Faro con timeout, 500, 404 o basura → se resume con El Pueblo,
  `fetches.ok=0`, la cabecera lo declara, sale 0.
- Un feed truncado conserva lo que sí se pudo interpretar: tirar esos
  artículos perdería noticias que nada volverá a traer.
- Las dos fuentes caídas **y** nada guardado del día → mensaje claro, sale ≠ 0,
  **sin llegar a llamar a Gemini**. Con algo guardado, se imprime.
- Gemini falla 3 veces → error, `summaries` sin fila, y la ejecución siguiente
  reintenta como si nada.
- Gemini falla la primera y responde la segunda → un resumen, una fila.
- BD bloqueada por otra ejecución simultánea → espera con timeout, sin corromper.
- `SIGINT` a mitad de la escritura → nada a medias: la fila es transaccional.

### Seguridad

- **La key no aparece en ninguna salida**: se busca el literal en `stdout`,
  `stderr` y en el traceback de un fallo provocado dentro del cliente.
- Si `~/.config/resumen-ceuta/env` no tiene permisos `600`, se avisa.
- SQL siempre parametrizado; `ruff` con las reglas `S` (bandit) lo vigila.
- **El feed es entrada no confiable**: un titular con `\x1b[2J` no puede pintar
  la terminal ni mover el cursor. Se sanea antes de imprimir, con fixture
  adversaria.
- **Inyección de prompt desde un titular**: un artículo que diga «ignora las
  instrucciones anteriores…» no consigue nada, porque la validación de ids es
  la red que lo atrapa. Fixture adversaria y aserción de que se rechaza.
- `pip-audit` semanal en CI.

### Datos

- Tres ejecuciones seguidas dejan el mismo estado.
- Muerte del proceso tras insertar artículos y antes de escribir `summaries` →
  la siguiente ejecución completa sin duplicar.
- **El titular corregido**: mismo artículo, `guid` distinto, `external_id`
  igual → una sola fila. Es el riesgo 5 de este documento, y sin este test es
  una afirmación sin respaldo.
- Artículo con `pubdate` retroactivo que cae en un día ya cubierto → entra en el
  día correcto y dispara su regeneración.
- **Deuda anotada**: hoy solo hay `CREATE TABLE IF NOT EXISTS`. El primer cambio
  real de esquema necesitará versionado y tests de migración. Ahora no aplica.

### Accesibilidad y multiplataforma

**No aplica casi nada, y es una decisión.** Una sola plataforma y salida de
texto plano: no se prueba Windows, ni macOS, ni lectores de pantalla. Lo único
que sí se cubre, porque es barato: la ejecución con `TERM=dumb` y con
`COLUMNS=40` sigue siendo legible, sin depender de color ni de un ancho fijo.

### QA manual — lo que sigue necesitando un humano

- [ ] Ejecutar tres veces repartidas a lo largo de un día real y comprobar que
      la cobertura de la cabecera cuadra con lo publicado.
- [ ] Revisar a mano la clasificación noticia/opinión sobre ~20 artículos. **No
      es auditable automáticamente** (riesgo 5): esta revisión es el único
      control que existe.
- [ ] Verificar en un caso real que la misma noticia en los dos medios queda
      agrupada.
- [ ] Instalar desde cero siguiendo solo el README.
- [ ] Mirar el gasto real en la consola de Google tras una semana.

### Cada test con su tarea

| Tarea | Tests que la prueban |
|---|---|
| T1 esqueleto | Funcional: instala, ejecuta, sale 0, `stdout` limpio |
| T2 CI | La puerta se ejecuta sobre sí misma; un PR rojo no se puede mergear |
| T3 config | Unit de rutas; funcional sin key; seguridad: permisos y key ausente |
| T4 store | Integración: idempotencia, esquema, `articles_for_day`; datos: titular corregido |
| T5 ingesta | Unit `external_id`, corte del día, HTML→texto; integración de los dos feeds; **contrato** |
| T6 esqueleto e2e | Funcional: máquina limpia crea BD e imprime titulares |
| T7 Gemini | Integración con respuesta grabada; resiliencia 3 fallos y 1-de-2; **contrato** del modelo |
| T8 validación | Unit: el caso bueno y los cinco malos; seguridad: inyección de prompt |
| T9 render | Unit contra golden file; seguridad: control ANSI; `TERM=dumb` y `COLUMNS=40` |
| T10 cabecera | Unit 0/1/N lecturas; integración desde `fetches` |
| T11 e2e resumen | Funcional: cabecera + temas de punta a punta |
| T12 caché | Integración `summaries`; unit `input_hash`; funcional del contador: 0 llamadas sin novedad, 1 con 10 nuevas |
| T13 cortocircuitos | Funcional: día vacío, día cubierto, `--force` |
| T14 ayer | Unit umbral 4/5; funcional de los dos bloques sin llamada extra |
| T15 degradación | Resiliencia entera: cada modo de fallo de cada fuente y de Gemini |
| T16 rendimiento | La tabla de presupuestos, marcada `perf` |
| T17 README | QA manual: instalación desde cero por un tercero |

---

## Riesgos asumidos

1. **La cobertura de Faro depende de cuántas veces abras la app, y es el
   riesgo dominante.** Su feed son 10 items con ~6,5 h de ventana y no tiene
   archivo. Una ejecución al día captura ~10 de sus ~35 noticias; el resto se
   pierde sin remedio. Es consecuencia directa de descartar el proceso
   programado, y se asume a sabiendas. El Pueblo no sufre esto: su feed llega
   36 días atrás, así que una sola ejecución lo rellena entero.
2. **El pasado no es alcanzable desde la CLI.** Los días anteriores siguen en
   SQLite y podrían consultarse, pero no hay comando para ello por decisión
   explícita. Añadirlo más adelante es un argumento, no un refactor.
3. **El resumen incremental agrupa peor entre ejecuciones.** Lo resumido en la
   lectura de la mañana se agrupó sin conocer lo de la tarde, así que dos
   noticias del mismo hecho separadas por horas pueden acabar en entradas
   distintas. Es el precio de no reprocesar el día entero, y el desequilibrio
   de fuentes hace que se note poco.
4. **El ámbito contradice la petición original.** Se pidió "lo que ha pasado en
   la ciudad de Ceuta", pero se decidió no filtrar: aparecerán noticias de
   Marruecos y de ámbito nacional. Revertirlo es una frase en el prompt.
5. **La clasificación noticia/crónica no es auditable**, la hace el modelo.
   `temperature=0` más el `input_hash` la hacen al menos reproducible: el mismo
   conjunto de artículos da el mismo resultado.
6. **El repositorio es público, y esa fue la moneda de cambio.** Se hizo
   público para conseguir el ruleset gratis. Consecuencias asumidas a
   sabiendas: el código y el historial son visibles desde ya, y los commits
   locales llevan el email personal del autor, que queda rastreable de forma
   permanente. Se ofreció reescribirlos a la dirección `noreply` y se decidió
   no hacerlo.
7. **El desequilibrio de fuentes es real, pero menor de lo estimado.** Faro
   publica al menos 35/día frente a los ~11/día de El Pueblo, no los 3,7 que
   decía la primera medición. El resumen seguirá siendo mayoritariamente Faro,
   pero la deduplicación entre fuentes se disparará bastante más a menudo de lo
   que este plan asumía, y conviene mirarla con lupa en T7.

---

## Stack

Python 3.14, sin framework:

- `feedparser` — parseo de RSS
- `sqlite3` — stdlib
- `zoneinfo` — stdlib, para el corte del día en `Europe/Madrid`
- `google-genai` — cliente de Gemini
- `python-dotenv` — carga de `~/.config/resumen-ceuta/env`

Desarrollo: `pytest` y `pytest-httpserver` para los tests, `ruff` para lint
y formato con las reglas `S` (bandit) activadas, `uv` para el entorno y el
empaquetado.

El identificador del modelo se fija explícitamente porque entra en el
`input_hash`: un alias como `gemini-flash-latest` cambiaría las respuestas sin
cambiar el hash que debería seguirlas.

Comprobado contra la API el 2026-08-30: **`gemini-3.6-flash`**. Se descartó
`gemini-3.7-flash`, que era el más nuevo y devolvía `503 UNAVAILABLE` en todos
los intentos, y `gemini-2.5-flash`, que aparece en el listado de modelos pero
responde `404` para `generateContent` con esta clave.

Una llamada real con los 34 artículos del 30 de agosto tardó **29,3 s** y
devolvió 16 entradas en 6 temas con 13 descartes, sin perder ni inventar
ningún id. De ahí sale el timeout de 90 s: tres veces el tiempo medido.

## Antes de escribir código

Comprobado en la máquina el 2026-08-30: Python 3.14.7 en `/usr/bin/python3.14`,
`uv` **no instalado**, `~/.config/resumen-ceuta/` **no existe**.

- [ ] **Revocar la API key de Gemini** que se compartió en claro durante el
      diseño. Generar otra en https://aistudio.google.com/apikey
- [ ] La nueva key va en `~/.config/resumen-ceuta/env` con permisos `600`.
      Nunca en el código ni en el repositorio.
- [x] `uv` instalado (0.12.7, vía `mise use -g uv@latest`, 2026-08-30).
- [x] `git init`, primer commit en `main` y rama `develop` (2026-08-30).
- [x] Repositorio privado `adrianhruiz/resumen-ceuta` creado, `main` y
      `develop` empujadas, `develop` como rama por defecto (2026-08-30).
