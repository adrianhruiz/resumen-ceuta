"""The one call to the model: what it is asked, and how the asking is retried.

The prompt text and the model id both feed the cache's input_hash, so editing
either of them regenerates the summaries they produced. That is deliberate:
changing the instructions has to change the output.
"""

import json
import time
from collections.abc import Callable, Sequence
from typing import Any, Protocol

from .store import Article

# Pinned on purpose. An alias like gemini-flash-latest would silently change
# the output without changing the hash that is supposed to track it.
# 3.7 was the newest on 2026-08-30 and answered 503 UNAVAILABLE on every try;
# 3.6 is the newest that actually serves this key.
MODEL = "gemini-3.6-flash"

# The SDK retries by itself, which turned a dead model into a three minute
# hang and made the retry policy below decorative. One attempt per call, and
# the backoff up here is the only one.
TIMEOUT_MS = 90_000

TOPICS: tuple[str, ...] = (
    "Frontera",
    "Política",
    "Sucesos",
    "Economía",
    "Sanidad",
    "Sociedad",
    "Deportes",
    "Cultura",
    "Otros",
)

ATTEMPTS = 3
BACKOFF_SECONDS = (1.0, 2.0)

PROMPT = """\
Eres el editor de un resumen diario de la prensa local de Ceuta. Trabajas con
lo que han publicado El Faro de Ceuta y El Pueblo de Ceuta.

Tu tarea, sobre los ARTÍCULOS NUEVOS:

1. Descarta lo que no sea noticia: opinión, editoriales, columnas, crónicas,
   reportajes, entrevistas, fotogalerías y previas o resúmenes deportivos.
   Ante la duda, descarta.
2. Agrupa en una sola entrada los artículos que cuentan el mismo hecho, aunque
   estén redactados de forma distinta o vengan de medios distintos.
3. Encaja cada entrada en uno de estos temas, y solo en estos:
   {topics}
4. Escribe cada entrada como una línea corta en español, en minúscula inicial,
   sin punto final y sin nombrar al medio. Cuenta el hecho, no la cobertura.

Reglas de salida, que se comprueban:

- Devuelve únicamente JSON, sin texto alrededor y sin markdown.
- Todo `id` que recibas tiene que aparecer exactamente una vez: o dentro de
  `entradas.ids`, o dentro de `descartados`. No inventes ids.
- Si un artículo llega sin entradilla, decide solo con el titular.

{context}
ARTÍCULOS NUEVOS:
{articles}
"""

CONTEXT_NONE = "Es el primer resumen del día: no hay nada previo.\n"

CONTEXT_PREVIOUS = """\
RESUMEN QUE YA EXISTE PARA ESTE DÍA. Amplíalo: conserva sus entradas tal como
están salvo que un artículo nuevo cuente el mismo hecho, en cuyo caso añade su
id a esa entrada. Devuelve el resumen completo, no solo lo añadido.

{payload}
"""

RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "temas": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "tema": {"type": "string", "enum": list(TOPICS)},
                    "entradas": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "texto": {"type": "string"},
                                "ids": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["texto", "ids"],
                        },
                    },
                },
                "required": ["tema", "entradas"],
            },
        },
        "descartados": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["temas", "descartados"],
}


class Model(Protocol):
    """What the pipeline needs from a model. The tests supply their own."""

    def generate(self, prompt: str) -> str: ...


def as_payload(articles: Sequence[Article]) -> list[dict[str, str | None]]:
    """Only what the model needs: never the body, which is 10x the tokens."""
    return [
        {
            "id": article.id,
            "titulo": article.title,
            "entradilla": article.description,
        }
        for article in articles
    ]


def build_prompt(
    articles: Sequence[Article], previous: dict[str, Any] | None = None
) -> str:
    """The exact text sent to the model, context included."""
    context = (
        CONTEXT_PREVIOUS.format(
            payload=json.dumps(previous, ensure_ascii=False, indent=2)
        )
        if previous
        else CONTEXT_NONE
    )
    return PROMPT.format(
        topics=" · ".join(TOPICS),
        context=context,
        articles=json.dumps(as_payload(articles), ensure_ascii=False, indent=2),
    )


class TransportError(RuntimeError):
    """The model could not be reached, or answered with something unusable."""


def ask(
    model: Model,
    articles: Sequence[Article],
    previous: dict[str, Any] | None = None,
    sleep: Callable[[float], None] | None = None,
) -> dict[str, Any]:
    """One summary, retried up to three times. Never writes anything.

    `sleep` is resolved here and not in the signature: a default argument is
    bound at import time, which would make the wait impossible to replace.
    """
    wait = sleep if sleep is not None else time.sleep
    prompt = build_prompt(articles, previous)
    last: Exception | None = None
    for attempt in range(ATTEMPTS):
        try:
            return json.loads(model.generate(prompt))
        except Exception as error:  # noqa: BLE001 - the SDK raises its own zoo
            last = error
            if attempt < len(BACKOFF_SECONDS):
                wait(BACKOFF_SECONDS[attempt])
    raise TransportError(f"Gemini no respondió tras {ATTEMPTS} intentos: {last}")


class Gemini:
    """The real model, wrapped so the rest of the app never imports the SDK."""

    def __init__(self, api_key: str, model: str = MODEL) -> None:
        # Imported here so a cache-warm run never pays for loading the SDK.
        import logging

        from google import genai
        from google.genai import types

        # The SDK warns about automatic function calling on every call. stderr
        # belongs to the user's progress, not to advice about an API this app
        # does not use.
        logging.getLogger("google_genai.models").setLevel(logging.ERROR)

        self._client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=TIMEOUT_MS,
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )
        self._model = model

    def generate(self, prompt: str) -> str:
        from google.genai import types

        response = self._client.models.generate_content(
            model=self._model,
            contents=prompt,
            config=types.GenerateContentConfig(
                # Same articles in, same summary out. The cache depends on it.
                temperature=0,
                response_mime_type="application/json",
                response_schema=RESPONSE_SCHEMA,
            ),
        )
        return response.text or ""
