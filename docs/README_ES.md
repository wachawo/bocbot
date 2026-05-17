# bocbot

[English](https://github.com/battleofcode/bocbot/blob/main/README.md) | [中文](https://github.com/battleofcode/bocbot/blob/main/docs/README_ZH.md) | [हिन्दी](https://github.com/battleofcode/bocbot/blob/main/docs/README_HI.md) | **[Español](https://github.com/battleofcode/bocbot/blob/main/docs/README_ES.md)** | [Français](https://github.com/battleofcode/bocbot/blob/main/docs/README_FR.md) | [العربية](https://github.com/battleofcode/bocbot/blob/main/docs/README_AR.md) | [Русский](https://github.com/battleofcode/bocbot/blob/main/docs/README_RU.md)

Plantilla de jugador para **Battle of Code** — un juego multijugador de captura de territorio donde cada uno ejecuta su propio bot (o juega manualmente desde la terminal).

**Lo que esta plantilla te da**

- Un cliente terminal con UI Rich (`client/`) en funcionamiento con el que puedes jugar usando WSAD.
- Un bot inicial (`bot.py`) que puedes editar — ese es todo el bot, un solo archivo.
- Tres pequeños scripts en `tools/` que te registran en el servidor del juego.
- Documentación que explica exactamente cómo se ven el formato de cable (wire) y la autenticación.

Nada aquí llama a casa, nada aquí está ofuscado. El registro completo son 30 líneas de REST que puedes ejecutar a mano. También incluimos un script que lo hace por ti, pero la primera vez — y debes — recorrer el proceso paso a paso para ver qué está sucediendo.

---

## Qué es realmente el registro

Tres cosas, nada más:

1. Un **par de claves Ed25519** en tu disco. La privada (`.key`) se queda local. La pública (`.pub`) es hex, 64 caracteres, una línea.
2. Una **rama en tu fork de GitHub** nombrada según tu login. En esa rama está `keys/<login>.pub`. El servidor la lee una sola vez.
3. Un **challenge firmado**. El servidor te da un nonce aleatorio, lo firmas con la clave privada, el servidor verifica contra la clave pública que acaba de obtener de GitHub.

Ese es todo el modelo de confianza. Sin contraseña, sin JWT, sin cookie. Cada sesión de juego repite el paso 3 con un frame `hello` firmado nuevo.

---

## Quickstart — manual, paso a paso

Hazlo una vez a mano. Después el script hace las mismas llamadas.

Reemplaza `<login>` con tu login de GitHub en todos los lugares.

### 1. Fork & clone

```bash
gh repo fork battleofcode/bocbot --clone --remote
cd bocbot
```

O a través de la UI web de GitHub, luego `git clone git@github.com:<login>/bocbot.git`.

### 2. Instalar dependencias de Python

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Eso te da:
- `cryptography` — generación de claves Ed25519 + firmas
- `websockets` — transporte del juego
- `rich` — renderizado CLI interactivo
- `requests` — REST signup

### 3. Configurar `.env`

```bash
cp .env.example .env
$EDITOR .env
```

Establece `USERNAME=<login>`. Ajusta `BOC_AUTH_HOST` / `BOC_GAME_HOST` si el servidor no está en `localhost`.

### 4. Generar un par de claves Ed25519 — a mano

Puedes hacerlo con una línea de Python (sin herramienta extra):

```bash
python3 - <<'PY'
import os, pathlib
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
login = os.environ.get("USERNAME")
key = Ed25519PrivateKey.generate()
priv = key.private_bytes(
    serialization.Encoding.Raw,
    serialization.PrivateFormat.Raw,
    serialization.NoEncryption(),
)
pub = key.public_key().public_bytes(
    serialization.Encoding.Raw, serialization.PublicFormat.Raw,
)
pathlib.Path("keys").mkdir(exist_ok=True)
pathlib.Path(f"keys/{login}.key").write_bytes(priv)
os.chmod(f"keys/{login}.key", 0o600)
pathlib.Path(f"keys/{login}.pub").write_text(f"# bocbot key for {login}\n{pub.hex()}\n")
print("private:", f"keys/{login}.key", "(mode 0600)")
print("public :", f"keys/{login}.pub", pub.hex())
PY
```

Lo que obtuviste:

- `keys/<login>.key` — 32 bytes raw, modo `0600`. **Ignorado por Git.** Nunca subas esto.
- `keys/<login>.pub` — clave pública hex, una línea + comentario. Seguro de subir.

> Lo mismo en forma de script: `python3 tools/keygen.py`. Es literalmente la línea de arriba con un envoltorio CLI.

### 5. Sube la clave pública a tu rama

```bash
git checkout -b <login>
git add keys/<login>.pub
git commit -m "register key"
git push -u origin <login>
```

`main` permanece limpio. Tu rama `<login>` guarda tu registro. El servidor la leerá en:

```
https://raw.githubusercontent.com/<login>/bocbot/<login>/keys/<login>.pub
```

Puedes `curl` ese URL tú mismo para comprobar que sea accesible.

### 6. Registrarse — a mano

Dos llamadas REST.

**Llamada 1: solicita un challenge.** El servidor obtiene tu `key.pub` de GitHub, guarda `(pubkey, nonce)` en Redis con TTL de 60 segundos, y devuelve el nonce.

```bash
curl -s -X POST "http://${BOC_AUTH_HOST:-127.0.0.1}:${BOC_AUTH_PORT:-8000}/api/auth/signup" \
     -H 'Content-Type: application/json' \
     -d "{\"username\":\"$USERNAME\"}"
```

Respuesta:

```json
{"status":"challenge","nonce":"0f1e2d3c4b5a69788796a5b4c3d2e1f0","ttl":60}
```

**Llamada 2: firma el nonce y verifica.** El nonce es hex. Decodifícalo a bytes, firma, codifica la firma en hex, envíala de vuelta.

```bash
NONCE=0f1e2d3c4b5a69788796a5b4c3d2e1f0   # de la respuesta anterior
SIG=$(python3 - <<PY
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
key = Ed25519PrivateKey.from_private_bytes(open(f"keys/$USERNAME.key","rb").read())
print(key.sign(bytes.fromhex("$NONCE")).hex())
PY
)
curl -s -X POST "http://${BOC_AUTH_HOST:-127.0.0.1}:${BOC_AUTH_PORT:-8000}/api/auth/signup/verify" \
     -H 'Content-Type: application/json' \
     -d "{\"username\":\"$USERNAME\",\"sig\":\"$SIG\"}"
```

Respuesta:

```json
{"status":"ok","username":"<login>"}
```

Ahora el servidor tiene `(username, pubkey)` cacheado en su almacén de autenticación SQLite. No volverá a hablar con GitHub por ti.

> Lo mismo en forma de script: `python3 tools/signup.py`. Imprime exactamente qué llamada está haciendo en cada paso. Ver [`docs/AUTH.md`](AUTH.md) para la referencia completa.

### 7. Verifica que puedas jugar

Smoke-test del WebSocket del juego:

```bash
python3 tools/login.py
```

Esto abre `ws://<host>:5555/`, envía un frame `hello` firmado, espera `auth_ok` + `welcome`, envía un `ping`, imprime `pong`, cierra. Si ves dos líneas verdes de salida, estás dentro.

Ahora juega de verdad:

```bash
./play.sh                          # cliente terminal Rich UI, WSAD
# o
python3 bot.py                     # el bot inicial — perderá, eso está bien
```

Si quieres volver a `main` para trabajar en el bot:

```bash
git checkout main
```

Ese es todo el flujo. Lo hiciste a mano una vez. La próxima vez el script lo hace.

---

## Quickstart — con script

Si solo quieres jugar y ya entiendes qué está pasando:

```bash
gh repo fork battleofcode/bocbot --clone --remote
cd bocbot
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
cp .env.example .env && $EDITOR .env       # establece USERNAME=<login>
python3 tools/signup.py                    # keygen + REST signup, pide confirmación antes del push
./play.sh
```

`tools/signup.py`:

1. Copia `.env.example` → `.env` si falta, confirma `USERNAME`.
2. Genera el par de claves (idempotente — si `keys/<login>.key` existe, lo reusa).
3. **Pausa** y muestra los cuatro comandos `git` que necesitas para subir la clave pública. Pulsa Enter cuando la hayas subido.
4. Llama a `/api/auth/signup`, firma el nonce, llama a `/api/auth/signup/verify`.

Lee el código fuente — son 200 líneas.

---

## Jugar manualmente

`./play.sh` abre una UI terminal Rich. La dirección y el nombre de usuario vienen de tu `.env` (`BOC_GAME_HOST`, `BOC_GAME_PORT`, `USERNAME`); los flags CLI de `client/client.py` los sobreescriben.

| Tecla          | Acción     |
|----------------|------------|
| `W`            | mover arriba    |
| `A`            | mover izquierda |
| `S`            | mover abajo     |
| `D`            | mover derecha   |
| `Esc` / `Ctrl+C` × 2 | salir |

El cliente se reconecta automáticamente cuando se cae el WebSocket; el servidor reanuda tu jugador en pausa (mismo `id`, posición, zona) siempre que no se haya excedido `PAUSE_TIMEOUT`.

Ejecuta como espectador con `-f N` para seguir al jugador vivo actualmente en el puesto N (1..128):

```bash
python3 client/client.py -f 1
```

---

## Qué viene en la caja

| Ruta                   | Qué es                                                                     |
|------------------------|----------------------------------------------------------------------------|
| `bot.py`               | bot inicial, Python — **edita `decide()`**                                 |
| `bot.go`               | bot inicial, Go — stub, aún no implementado                                |
| `bot.js`               | bot inicial, Node.js — stub, aún no implementado                           |
| `client/`              | jugador CLI terminal (Rich UI, WSAD) — para juego humano                   |
| `play.sh`              | lanza el cliente CLI contra `battleofcode.com`                             |
| `tools/keygen.py`      | genera par de claves Ed25519 en `keys/<u>.key` + `keys/<u>.pub`            |
| `tools/signup.py`      | registro end-to-end contra la REST API                                     |
| `tools/login.py`       | smoke-test WebSocket (hello → ping → pong)                                 |
| `docs/AUTH.md`         | profundidad de autenticación (REST signup, reglas de firma, errores)       |
| `docs/API.md`          | protocolo wire (frames WebSocket, mensajes state, eventos)                 |
| `docs/RULES.md`        | reglas del juego (zonas, trails, captura, condiciones de muerte)           |
| `docs/EXAMPLES.md`     | recetario de toma de decisiones del bot                                    |
| `keys/<u>.pub`         | tu clave **pública** (subida en la rama `<u>` de tu fork)                  |
| `keys/<u>.key`         | tu clave **privada** (ignorada por git, modo 0600)                         |

---

## Cómo funciona el registro (resumen)

1. Generas un par de claves Ed25519 (`tools/keygen.py` o la línea de Python de arriba).
2. La clave privada queda en `keys/<your-login>.key` (ignorada por git, modo `0600`).
3. La clave pública se sube como `keys/<your-login>.pub` en una rama nombrada según tu login de GitHub.
4. `tools/signup.py` (o dos llamadas `curl`) le dice al servidor tu username; el servidor descarga la clave pública de `keys/<login>.pub` en tu rama `<login>` y emite un nonce de corta duración.
5. El script firma el nonce con tu clave privada; el servidor verifica y guarda `(username, pubkey)` en su DB de auth SQLite. Después de eso no hay más viajes a GitHub.
6. Cada conexión WebSocket lleva un `hello` firmado nuevo (`{username, ts, sig}`). El servidor lo verifica contra la clave pública guardada. Sin tokens, sin cookies, sin sesiones.

`main` permanece limpio: los PRs upstream no tocan tu `.pub`. Tu rama es tu registro.

Referencias profundas:
- [`docs/AUTH.md`](AUTH.md) — el flujo de auth, códigos de error, notas de seguridad
- [`docs/API.md`](API.md) — el formato wire (REST + WebSocket)
- [`docs/RULES.md`](RULES.md) — mecánicas del juego

---

## Mejora tu bot

Abre `bot.py`. Todo el bot es un solo archivo. La única función que necesitas tocar es `decide(state)` arriba.

- Lee [`docs/RULES.md`](RULES.md) para saber qué gana.
- Lee [`docs/API.md`](API.md) para la forma de `state` (es solo un dict JSON).
- Lee [`docs/EXAMPLES.md`](EXAMPLES.md) para el recetario (evitar paredes, cazar, métricas de distancia).

`bot.go` y `bot.js` son placeholders que imprimen "not implemented yet" — si quieres jugar en Go o Node, porta `bot.py`. El protocolo son ~80 líneas de lógica real; todo lo demás es `decide()` y la fontanería de reconexión.

---

## Enlaces

- Servidor y leaderboard en vivo: <https://battleofcode.com>
- Issue tracker: reporta bugs contra `battleofcode/bocbot` upstream

## Licencia

MIT — ver [LICENSE](../LICENSE).
