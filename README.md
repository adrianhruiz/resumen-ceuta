# resumen-ceuta

Resumen de lo publicado por la prensa local de Ceuta, agrupado por temas y
legible de un vistazo, impreso en la terminal.

Lee los feeds de [El Faro de Ceuta](https://elfarodeceuta.es) y
[El Pueblo de Ceuta](https://www.elpueblodeceuta.es), guarda lo nuevo en SQLite
y pide a Gemini que clasifique y agrupe únicamente los artículos que todavía no
ha resumido.

```
Día 30 de agosto · 22 noticias
El Pueblo: completo hasta 20:14 · Faro: 3 lecturas (parcial)

Frontera: prisión para los cuatro detenidos por la emboscada
  a militares; expulsadas dos mujeres con DNI falso
Política: el Gobierno aprueba 165M en ayudas
```

## Estado

En construcción. El diseño completo, el plan de tareas y el plan de tests están
en [PLAN.md](PLAN.md).

## Instalación

```bash
mise use -g uv@latest   # o: sudo pacman -S uv
uv tool install --editable .
```

La API key de Gemini va en `~/.config/resumen-ceuta/env`, con permisos `600`.

## Uso

```
resumen            # hoy, y ayer también si hoy va flojo
resumen --force    # regenera ignorando la caché
```

## Desarrollo

```bash
uv run pytest             # la suite completa
uv run pytest -m network  # contrato contra los feeds y Gemini reales
uv run ruff check . && uv run ruff format --check .
```

La instalación editable refleja los cambios de código, pero **no** los de
dependencias. Al añadir una, hay que reinstalar la herramienta:

```bash
uv tool install --editable . --reinstall
```
