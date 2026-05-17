# bocbot

**[English](https://github.com/battleofcode/bocbot/blob/main/README.md)** | [Русский](https://github.com/battleofcode/bocbot/blob/main/docs/README_RU.md)

Player template for **Battle of Code** — a multiplayer territory-capture game where everyone runs their own bot (or plays manually from the terminal).

**What this template gives you**

- A working Rich-UI terminal client (`client/`) you can play with WSAD.
- A starter bot (`bot.py`) you can edit — that's the whole bot, one file.
- Three small `tools/` scripts that register you with the game server.
- Docs explaining exactly what the wire format and auth look like.

Nothing here phones home, nothing here is obfuscated. The full registration is 30 lines of REST you can run by hand. We also ship a script that does it for you, but you can — and should, the first time — do it step by step so you see what's happening.

---

## What registration actually is

Three things, no more:

1. An **Ed25519 keypair** on your disk. Private (`.key`) stays local. Public (`.pub`) is hex, 64 chars, one line.
2. A **branch in your GitHub fork** named after your login. On that branch sits `keys/<login>.pub`. The server reads it once.
3. A **signed challenge**. The server gives you a random nonce, you sign it with the private key, the server verifies against the public key it just fetched from GitHub.

That's the whole trust model. No password, no JWT, no cookie. Every game session repeats step 3 with a fresh signed `hello` frame.

---

## Quickstart — manual, step by step

Do it once by hand. After that the script does the same calls.

Replace `<login>` with your GitHub login everywhere.

### 1. Fork & clone

```bash
gh repo fork battleofcode/bocbot --clone --remote
cd bocbot
```

Or via the GitHub web UI, then `git clone git@github.com:<login>/bocbot.git`.

### 2. Install Python dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

That gives you:
- `cryptography` — Ed25519 keygen + signatures
- `websockets` — game transport
- `rich` — interactive CLI rendering
- `requests` — REST signup

### 3. Configure `.env`

```bash
cp .env.example .env
$EDITOR .env
```

Set `USERNAME=<login>`. Tweak `BOC_AUTH_HOST` / `BOC_GAME_HOST` if the server isn't on `localhost`.

### 4. Generate an Ed25519 keypair — by hand

You can do it with Python one-liner (no extra tool needed):

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

What you got:

- `keys/<login>.key` — 32 raw bytes, mode `0600`. **Git-ignored.** Never commit this.
- `keys/<login>.pub` — hex public key, one line + comment. Safe to commit.

> The same thing in script form: `python3 tools/keygen.py`. It's the literal one-liner above with a CLI wrapper.

### 5. Push the public key to your branch

```bash
git checkout -b <login>
git add keys/<login>.pub
git commit -m "register key"
git push -u origin <login>
```

`main` stays clean. Your `<login>` branch holds your registration. The server will read it at:

```
https://raw.githubusercontent.com/<login>/bocbot/<login>/keys/<login>.pub
```

You can `curl` that URL yourself to check it's reachable.

### 6. Sign up — by hand

Two REST calls.

**Call 1: request a challenge.** The server fetches your `key.pub` from GitHub, stores `(pubkey, nonce)` in Redis with a 60-second TTL, and returns the nonce.

```bash
curl -s -X POST "http://${BOC_AUTH_HOST:-127.0.0.1}:${BOC_AUTH_PORT:-8000}/api/auth/signup" \
     -H 'Content-Type: application/json' \
     -d "{\"username\":\"$USERNAME\"}"
```

Response:

```json
{"status":"challenge","nonce":"0f1e2d3c4b5a69788796a5b4c3d2e1f0","ttl":60}
```

**Call 2: sign the nonce and verify.** The nonce is hex. Decode it to bytes, sign, hex-encode the signature, send back.

```bash
NONCE=0f1e2d3c4b5a69788796a5b4c3d2e1f0   # from the previous response
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

Response:

```json
{"status":"ok","username":"<login>"}
```

The server now has `(username, pubkey)` cached in its SQLite auth store. It won't talk to GitHub for you again.

> Same thing in script form: `python3 tools/signup.py`. It prints exactly which call it's making at each step. See [`docs/AUTH_EN.md`](docs/AUTH_EN.md) for the full reference.

### 7. Verify you can play

Smoke-test the game WebSocket:

```bash
python3 tools/login.py
```

This opens `ws://<host>:5555/`, sends a signed `hello` frame, waits for `auth_ok` + `welcome`, sends one `ping`, prints `pong`, closes. If you see two lines of green output you're in.

Now actually play:

```bash
./play.sh                          # Rich UI terminal client, WSAD
# or
python3 bot.py                     # the starter bot — it will lose, that's fine
```

If you want to come back to `main` to work on the bot:

```bash
git checkout main
```

That's the whole flow. You did it by hand once. Next time the script does it.

---

## Quickstart — scripted

If you just want to play and already understand what's happening:

```bash
gh repo fork battleofcode/bocbot --clone --remote
cd bocbot
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
cp .env.example .env && $EDITOR .env       # set USERNAME=<login>
python3 tools/signup.py                    # keygen + REST signup, prompts when ready to push
./play.sh
```

`tools/signup.py`:

1. Copies `.env.example` → `.env` if missing, confirms `USERNAME`.
2. Generates the keypair (idempotent — if `keys/<login>.key` exists, reuses it).
3. **Pauses** and prints the four `git` commands you need to push the public key. Press Enter when you've pushed.
4. Calls `/api/auth/signup`, signs the nonce, calls `/api/auth/signup/verify`.

Read the source — it's 200 lines.

---

## Playing manually

`./play.sh` opens a Rich terminal UI. Address and username come from your `.env` (`BOC_GAME_HOST`, `BOC_GAME_PORT`, `USERNAME`); CLI flags on `client/client.py` override them.

| Key            | Action |
|----------------|--------|
| `W`            | move up    |
| `A`            | move left  |
| `S`            | move down  |
| `D`            | move right |
| `Esc` / `Ctrl+C` × 2 | quit |

The client auto-reconnects on a dropped WebSocket; the server resumes your paused player (same `id`, position, zone) as long as `PAUSE_TIMEOUT` hasn't elapsed.

Run as a spectator with `-f N` to follow the live player currently ranked N (1..128):

```bash
python3 client/client.py -f 1
```

---

## What's in the box

| Path                   | What it is                                                                 |
|------------------------|----------------------------------------------------------------------------|
| `bot.py`               | starter bot, Python — **edit `decide()`**                                  |
| `bot.go`               | starter bot, Go — stub, not implemented yet                                |
| `bot.js`               | starter bot, Node.js — stub, not implemented yet                           |
| `client/`              | terminal CLI player (Rich UI, WSAD) — for human play                       |
| `play.sh`              | launch the CLI client against `battleofcode.com`                           |
| `tools/keygen.py`      | generate Ed25519 keypair into `keys/<u>.key` + `keys/<u>.pub`              |
| `tools/signup.py`      | end-to-end signup against the REST API                                     |
| `tools/login.py`       | WebSocket smoke-test (hello → ping → pong)                                 |
| `docs/AUTH_EN.md`         | auth deep dive (REST signup, signing rules, failure modes)                 |
| `docs/API_EN.md`          | wire protocol (WebSocket frames, state messages, events)                   |
| `docs/RULES_EN.md`        | game rules (zones, trails, capture, death conditions)                      |
| `docs/EXAMPLES_EN.md`     | bot decision-making cookbook                                               |
| `keys/<u>.pub`         | your **public** key (committed on the `<u>` branch of your fork)           |
| `keys/<u>.key`         | your **private** key (git-ignored, mode 0600)                              |

---

## How registration works (summary)

1. You generate an Ed25519 keypair (`tools/keygen.py` or the Python one-liner above).
2. Private key stays in `keys/<your-login>.key` (git-ignored, mode `0600`).
3. Public key is committed as `keys/<your-login>.pub` on a branch named after your GitHub login.
4. `tools/signup.py` (or two `curl` calls) tells the server your username; the server downloads the public key from `keys/<login>.pub` on your `<login>` branch and issues a short-lived nonce.
5. The script signs the nonce with your private key; the server verifies and stores `(username, pubkey)` in its SQLite auth DB. After that there is no further GitHub round-trip.
6. Every WebSocket connect carries a fresh signed `hello` (`{username, ts, sig}`). The server verifies it against the stored public key. No tokens, no cookies, no sessions.

`main` stays clean: PRs upstream don't touch your `.pub`. Your branch is your registration.

Deep references:
- [`docs/AUTH_EN.md`](docs/AUTH_EN.md) — the auth flow, error codes, security notes
- [`docs/API_EN.md`](docs/API_EN.md) — the wire format (REST + WebSocket)
- [`docs/RULES_EN.md`](docs/RULES_EN.md) — game mechanics

---

## Improve your bot

Open `bot.py`. The entire bot is one file. The only function you need to touch is `decide(state)` at the top.

- Read [`docs/RULES_EN.md`](docs/RULES_EN.md) for what wins.
- Read [`docs/API_EN.md`](docs/API_EN.md) for the shape of `state` (it's just a JSON dict).
- Read [`docs/EXAMPLES_EN.md`](docs/EXAMPLES_EN.md) for the recipe book (wall avoidance, hunting, distance metrics).

`bot.go` and `bot.js` are placeholders that print "not implemented yet" — if you want to play in Go or Node, port `bot.py` over. The protocol is ~80 lines of real logic; everything else is `decide()` and reconnect plumbing.

---

## Links

- Server & live leaderboard: <https://battleofcode.com>
- Issue tracker: file bugs against `battleofcode/bocbot` upstream

## Licence

MIT — see [LICENSE](LICENSE).
