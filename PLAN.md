# Watchlist Telegram Bot — seleccionar y descargar películas desde Telegram

Bot de Telegram que consulta la watchlist de Letterboxd, muestra las películas
disponibles en YTS como una lista seleccionable y, con un toque, las manda a
descargar a Transmission.

**Estado:** planificado (sin implementar todavía).
**Plataforma:** Linux (Linux Mint), usuario `vulkan0n`.
**Proyecto hermano reutilizado:** `../watchlist-downloader`.

---

## Objetivo

Desde Telegram:

1. Enviar un comando (ej. `/lista`) y recibir las películas **disponibles**.
2. Seleccionar una o varias.
3. Confirmar y que el bot las encole en Transmission para descargar.

Es la contraparte interactiva de `watchlist-downloader`, que hoy funciona solo
como TUI en la PC. **La TUI se sigue usando tal cual** — este bot no la reemplaza.

---

## Contexto: qué es `watchlist-downloader`

Pipeline actual (todo en `watchlist_downloader/app.py:run_app`):

```
Letterboxd (scraper) → TMDB (resolve) → YTS (search) → TUI → Transmission
```

| Módulo | Función principal | Reutilizable |
|--------|-------------------|--------------|
| `scraper.py` | `fetch_watchlist(username) -> list[RawFilmEntry]` | Sí |
| `tmdb_resolver.py` | `TMDBResolver(api_key).resolve(entries) -> list[Movie]` | Sí |
| `yts_searcher.py` | `YTSSearcher().search_batch(movies) -> list[MovieWithTorrent]` | Sí |
| `transmission_client.py` | `TransmissionClient().add_magnets(magnets) -> list[(magnet, ok)]` | Sí |
| `state_store.py` | `StateStore().load()/save()/mark_downloaded()` | Sí |
| `models.py` | `Movie`, `MovieWithTorrent`, `TorrentInfo`, `AppState` | Sí |
| `tui.py` | `WatchlistApp` (Textual) | No (es UI) |
| `app.py` | Orquestación + `print()` + lanzar TUI | Parcial |

**El problema:** las piezas de dominio son puras y limpias, pero la orquestación
vive mezclada con `print()` de consola y el lanzamiento de la TUI
(`app.py:302-317`). Un bot no puede reusar ese bloque.

**Config actual (env vars):**

- `TMDB_API_KEY` (obligatoria)
- `TRANSMISSION_URL` (default `http://localhost:9091/transmission/rpc`)
- `LETTERBOXD_USERNAME` (default `your_letterboxd_user`)

**Estado persistido:** `~/.config/watchlist-downloader/state.json`
(`downloaded_imdb_ids`, `not_found_imdb_ids`, `ignored_imdb_ids`,
`resolved_cache`, `yts_cache`).

**Reglas de negocio ya definidas en el pipeline:**

- Se descartan torrents `2160p`.
- Orden: descargadas → disponibles (por seeds desc) → no encontradas.
- Caché de YTS con TTL de 7 días (`YTS_CACHE_TTL_DAYS`).
- Un fallo de YTS **no** se cachea como "no disponible" (se reintenta).

---

## Contexto: `telegram-notifier` (lo que ya funciona)

- Bot saliente puro: `notify.py` corre por cron y hace POST a `sendMessage`/`sendPoll`.
- Credenciales en `~/.config/telegram-notifier/secrets.env` (`600`, fuera del repo):
  `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (chat_id actual: `<YOUR_CHAT_ID>`).
- Sin dependencias: Python stdlib (`urllib`, `json`).

---

## Decisión técnica central: es saliente, no entrante

Telegram permite recibir mensajes **sin IP pública, sin abrir puertos y sin
contratar ningún servicio**, usando **long polling**:

```
[PC] --getUpdates (HTTPS saliente, ~50s)--> api.telegram.org
```

Contraste con la alternativa (webhook), que sí exige un endpoint público
(VPS, Cloudflare Tunnel, ngrok). **Se descarta el webhook.**

Consecuencia: el bot es un **proceso permanente** (a diferencia del cron de
`notify.py`). Se corre como servicio de usuario (`systemd --user`,
`Restart=on-failure`).

Detalles del loop de polling:

- `getUpdates(offset=last_update_id+1, timeout=50)`
- `allowed_updates=["message", "callback_query"]`
- Los toques de botones llegan como update `callback_query`.
- Un solo proceso puede pollear (no llamar `getUpdates` en paralelo, ej. el
  `--chat-id` de `notify.py` competiría por los updates).

---

## Decisión de UX: `inline_keyboard`, NO encuesta (`sendPoll`)

**Una encuesta de Telegram tiene tope de 10 opciones de 100 caracteres.** La
watchlist tiene decenas de películas (ver `state.json`, ya cachea muchas). Un
poll **no entra**.

Se usa **inline keyboard**:

- Un mensaje con botones por película (☐/☑ toggle).
- Paginación con botones ◀ / ▶ (ej. 8 pelis por página, deja lugar a la fila de navegación).
- Botón **Descargar** para confirmar la selección.
- `callback_data` limitado a **1-64 bytes** → se manda un **índice corto**, no el
  título. El índice referencia una lista guardada en estado de sesión del bot.

Flujo:

```
/lista
  → [scrape+resolve+search] → mensaje con teclado paginado (solo Available)
  → usuario toca pelis (callback_query: "t:<idx>")
  → usuario toca ◀/▶ (callback_query: "p:<page>")
  → usuario toca "Descargar" (callback_query: "d")
  → bot llama add_magnets() + mark_downloaded()
  → mensaje de resultado (N encoladas / fallos)
```

---

## Filtro de películas a mostrar

**Solo "Available":** `mwt.available == True` (tiene torrents, lookup OK) **y** su
`imdb_id` **no** está en `downloaded_imdb_ids`. Se excluyen explícitamente:

- **Downloaded** (ya descargadas).
- **Not found** (`available == False`).
- **YTS error** (`search_failed == True`).

Es exactamente el subconjunto que la TUI hoy muestra en verde como "Available".

---

## Refactor de `watchlist-downloader` — alcance acotado

La TUI debe seguir funcionando. Dos caminos:

### Opción A — Cero cambios en `watchlist-downloader` (bajo riesgo)

El bot importa los módulos (`scraper`, `tmdb_resolver`, `yts_searcher`,
`transmission_client`, `state_store`) y **re-orquesta** en su propio código.
Contra: ~30 líneas de orquestación duplicadas y riesgo de drift en las reglas
(filtro `2160p`, orden, TTL de caché).

### Opción B — Extraer `service.py` en `watchlist-downloader` (recomendada)

Sacar la orquestación de `app.py` a una capa headless sin prints ni TUI:

- `prepare(username, tmdb_api_key) -> list[MovieWithTorrent]`
  (scrape + resolve + search + cachés, sin `print`).
- `download(movie_ids) -> list[(movie, ok)]`
  (filtra disponibles, `add_magnets()`, `mark_downloaded()`).

`app.py` (TUI) y el bot pasan a ser **adaptadores finos** sobre esa capa.
Cero lógica duplicada y la TUI sigue intacta en comportamiento.

> Recomendación: **B**, pero acotado. Tocar `app.py` solo para que llame a
> `service.py`; no rediseñar la TUI. Si se prioriza no tocar nada, arrancar con A
> y extraer `service.py` cuando la duplicación moleste.

---

## Extensibilidad: sumar trackers sin tocar el bot

La **abstracción de búsqueda vive en `watchlist-downloader`, NO en el bot**. El
bot solo consume `list[MovieWithTorrent]`; no sabe qué trackers existen.

- Definir un contrato `TorrentProvider` (Protocol) con algo tipo
  `search(movies) -> list[MovieWithTorrent]`.
- YTS pasa a ser **una implementación** de ese contrato.
- `service.prepare()` itera una lista de providers y agrega los resultados.

Consecuencia: **sumar un tracker = agregar un provider** en
`watchlist-downloader`. La TUI y el bot lo heredan sin cambios.

**Límite:** si un tracker nuevo cambia la **forma de los datos**
(`MovieWithTorrent` / `TorrentInfo`: resultados por-provider, calidades o
subtítulos distintos), entonces sí hay que tocar las UIs (TUI **y** bot). Eso es
inherente a que la UI conoce el modelo de datos.

> Nota de implementación dejada en el repo fuente:
> `../watchlist-downloader/NOTES.md`.

---

## Arquitectura del proyecto nuevo

```
watchlist-telegram-bot/
├── PLAN.md                # este documento
├── bot.py                 # loop de long polling + dispatcher de updates
├── handlers.py            # /lista, /start, callbacks (toggle, paginar, descargar)
├── session.py             # estado de sesión en memoria (lista + selección + página)
├── telegram_api.py        # cliente HTTP stdlib (getUpdates, sendMessage, editMessageReplyMarkup, answerCallbackQuery)
├── keyboard.py            # armado del inline keyboard paginado
└── secrets.env.example    # plantilla (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
```

- **Reutilización:** importar el paquete `watchlist_downloader` (vía `sys.path`
  o instalar con `pip install -e ../watchlist-downloader`).
- **Anti-doble-pollo:** un único proceso corre el loop.
- **Estado de sesión:** en memoria alcanza (la lista se regenera con `/lista`).
  Lo persistente (descargadas, cachés) lo maneja `StateStore` del proyecto reusable.

### Librería

- **Opción 1 (stdlib):** consistente con `telegram-notifier`, cero dependencias,
  pero escribir `getUpdates` + callbacks a mano es más verboso.
- **Opción 2 (`python-telegram-bot`):** mucho menos código para teclados y
  callbacks; agrega dependencia.

> Decisión abierta al momento de implementar. Empezar con stdlib si se quiere
> mantener el estilo; usar `python-telegram-bot` si molesta el boilerplate.

---

## Seguridad (crítico)

Un bot que descarga cosas en la PC es un control remoto. Reglas:

- **Whitelist de `chat_id`** (`<YOUR_CHAT_ID>`): ignorar todo update que no venga de ahí.
- **Acciones fijas, no comandos arbitrarios:** el bot solo expone listar/descargar.
  Nunca `shell=True` ni ejecutar texto del usuario.
- **Token = credencial:** vive en `~/.config/.../secrets.env` (`600`), jamás en el repo.
- **Confirmación explícita** antes de encolar descargas.

---

## Esfuerzo estimado

| Tarea | Estimado |
|-------|----------|
| Refactor acotado (`service.py`) o re-orquestación en el bot | ~medio día |
| Bot: polling, comandos, teclado paginado, confirmación | ~1 día |
| Servicio systemd + prueba real de punta a punta | ~medio día |
| **Total** | **1-2 días** |

---

## Checklist de aceptación

- [ ] Proyecto creado y `PLAN.md` presente.
- [ ] Decidida la Opción A vs B del refactor.
- [ ] Decidida la librería (stdlib vs `python-telegram-bot`).
- [ ] Bot polleando como servicio `systemd --user`.
- [ ] `/lista` devuelve solo películas Available, paginadas.
- [ ] Toggle de selección + botón Descargar funcionales.
- [ ] `add_magnets()` encola en Transmission y se refleja en `state.json`.
- [ ] Whitelist de `chat_id` verificada (ignora otros usuarios).
- [ ] Probado de punta a punta con Transmission corriendo.

---

## Preguntas abiertas

1. ¿Mostrar también un botón de **refresh** (forzar re-scrape ignorando caché)?
2. ¿Qué hacer si la lista de Available queda **vacía**? (¿mensaje, o sugerir revisar YTS?)
3. ¿Permitir **descartar** una película de la lista (marcar como ignorada)?
4. ¿Notificar cuando arranca/termina una descarga (hook a Transmission), o es
   fire-and-forget?
5. Nombre definitivo del comando: `/lista`, `/watchlist`, `/pelis`.

---

## Referencias

- `../watchlist-downloader` — pipeline y módulos reutilizables.
- `../telegram-notifier` — bot saliente existente, convención de secretos.
- `~/.config/watchlist-downloader/state.json` — estado persistido.
- `~/.config/telegram-notifier/secrets.env` — token y chat_id.
