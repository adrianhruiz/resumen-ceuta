# resumen-ceuta

Lo que ha publicado hoy la prensa local de Ceuta, agrupado por temas y legible
de un vistazo, en la terminal.

```
Día 30 de agosto · 36 noticias
El Pueblo: completo hasta 21:30 · Faro: 3 lecturas (parcial)

Política: vox anuncia acciones legales en el ámbito europeo contra la ong no
  name kitchen; el pp critica la inacción del gobierno central un mes después
  del inicio de la crisis migratoria; alberto núñez feijóo realizará este
  miércoles su tercera visita a la ciudad
Sucesos: ingresan en prisión tres jóvenes acusados de robar con violencia una
  cadena a una mujer en el centro; detenidas tres personas tras lanzar botellas
  con líquido corrosivo a militares en san amaro
Economía: el gobierno prepara un plan de 165 millones de euros para paliar los
  efectos de la crisis; la cámara de comercio calcula en 33 millones las
  pérdidas económicas provocadas
```

Lee los feeds de [El Faro de Ceuta](https://elfarodeceuta.es) y
[El Pueblo de Ceuta](https://www.elpueblodeceuta.es), guarda lo nuevo en SQLite
y le pide a Gemini que clasifique y agrupe **solo** lo que todavía no ha
resumido. Opinión, crónicas, reportajes y fotogalerías se quedan fuera.

## Qué necesitas

- **Python 3.14** o posterior.
- **[uv](https://docs.astral.sh/uv/)**: `mise use -g uv@latest`, o
  `sudo pacman -S uv`, o el instalador de su web.
- **Una API key de Gemini**, gratuita en
  [aistudio.google.com/apikey](https://aistudio.google.com/apikey).

## Instalación

```bash
git clone https://github.com/adrianhruiz/resumen-ceuta.git
cd resumen-ceuta
uv tool install --editable .
```

Deja el comando `resumen` en `~/.local/bin`. Si tu shell no lo encuentra,
añade ese directorio al `PATH`.

Después, la clave:

```bash
mkdir -p ~/.config/resumen-ceuta
printf 'GEMINI_API_KEY=tu-clave\n' > ~/.config/resumen-ceuta/env
chmod 600 ~/.config/resumen-ceuta/env
```

Si falta, el programa no arranca y te dice exactamente qué escribir y dónde.

## Uso

```bash
resumen            # hoy, y ayer también si hoy va flojo
resumen --force    # regenera el día ignorando lo ya resumido
```

La primera ejecución tarda medio minuto y trae meses de archivo de El Pueblo.
Las siguientes del mismo día son **instantáneas y gratis** mientras no haya
noticias nuevas: lo ya resumido no se vuelve a pagar.

El resumen sale por `stdout` y el progreso por `stderr`, así que
`resumen > hoy.txt` guarda solo el resumen.

## Cosas que conviene saber

- **La cabecera declara la cobertura real.** El feed de El Faro solo muestra
  sus diez últimas noticias, sin archivo: si abres la app una vez al día verás
  una fracción de lo que publicó. Cuantas más veces la abras, más completo. El
  Pueblo no tiene ese problema, su feed llega meses atrás.
- **El coste sigue al número de noticias, no al de ejecuciones.** Abrir la app
  diez veces en un día cuesta lo mismo que abrirla una.
- **Solo hoy.** No hay comando para consultar días pasados, aunque estén
  guardados.
- **Clasifica un modelo, no una regla.** Que algo sea noticia u opinión lo
  decide Gemini; no siempre acertará.

Dónde vive todo:

| | |
|---|---|
| Base de datos | `~/.local/share/resumen-ceuta/db.sqlite3` |
| API key | `~/.config/resumen-ceuta/env`, permisos `600` |

Unos 165 KB al día, así que la base crece unos 55 MB al año y no hay purga.

## Desarrollo

```bash
uv run pytest                          # la suite completa
uv run pytest -m network               # contrato contra los feeds y Gemini reales
uv run ruff check . && uv run ruff format --check .
```

Añadir una dependencia obliga a reinstalar la herramienta
(`uv tool install --editable . --reinstall`): el modo editable refleja el
código, no el conjunto de dependencias.

Los tests de contrato necesitan una clave y no forman parte de la puerta de CI:
dependen de servidores ajenos y no deben romper un PR por una mala noche de
otro. Corren cada noche y abren issue si algo cambió.

Para volver a grabar los fixtures de los feeds:

```bash
uv run python scripts/record_fixtures.py
```

El diseño completo, el plan de tareas y el plan de tests están en
[PLAN.md](PLAN.md), con las decisiones y su porqué.
