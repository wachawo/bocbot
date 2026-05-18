# bocbot

**[English](README.md)** ([Quick setup](#quick-setup)) | [Русский](docs/README_RU.md) ([краткая установка](docs/README_RU.md#краткая-установка))

Player template for **Battle of Code** — a multiplayer territory-capture game where everyone runs their own bot (or plays manually from the terminal).

**What this template gives you**

- A working Rich-UI terminal client (`client/`) you can play with WSAD.
- A starter bot (`bot.py`) you can edit — that's the whole bot, one file.
- Three small `tools/` scripts that register you with the game server.
- Docs explaining exactly what the wire format and auth look like.

Every setup step has a one-command script form (recommended) and an equivalent manual form documented in [`docs/AUTH_EN.md`](docs/AUTH_EN.md) §3. Use the script the first time; read the docs when you want to see what it does under the hood.

---

## Registration in three steps

1. **Generate keys.** `tools/keygen.py` creates `keys/<login>.key` (private, local) and `keys/<login>.pub` (public, safe to commit).
2. **Push the public key to your fork.** Put `keys/<login>.pub` on a branch named `<login>` in your GitHub fork — the server reads it from there.
3. **Sign up on the server.** `tools/signup.py` sends your login; the server downloads the public key from your branch, hands you a nonce, you sign it with the private key.

That's the whole trust model — no passwords, no tokens, no cookies. Full details and the manual flow: [`docs/AUTH_EN.md`](docs/AUTH_EN.md).

---

## Quick setup

Minimum path from zero to playing. Replace `<login>` with your GitHub login.

| # | Do this |
|---|---------|
| 1 | Fork & clone (see [§1](#1-fork--clone)) |
| 2 | `pip install -r requirements.txt` ([§2](#2-install-python-dependencies)) |
| 3 | `cp .env.example .env` and set `USERNAME=<login>` ([§3](#3-configure-env)) |
| 4 | `python3 tools/signup.py` — keys, `git push`, REST signup in one go ([§6.1](#61-with-the-script-recommended)) |
| 5 | `./play.sh` or `python3 bot.py` ([§7](#7-verify-and-play)) |

**Keys only** (no server signup yet): after step 3, run `python3 tools/keygen.py` ([§4](#4-generate-an-ed25519-keypair)). It reads `USERNAME` from `.env`, not the OS `$USERNAME` (on Windows those differ).

**Manual / verify yourself:** [`docs/AUTH_EN.md`](docs/AUTH_EN.md) §3 — generate keys without `tools/keygen.py` and run signup with `curl`. Same section covers error codes and security notes.

**Full walkthrough:** [Quickstart §1–7](#quickstart) below · [Русский — краткая установка](docs/README_RU.md#краткая-установка) · [Русский — полный Quickstart](docs/README_RU.md#quickstart)

---

## Quickstart

Replace `<login>` with your GitHub login everywhere. Prefer the [Quick setup](#quick-setup) table above; this section walks through the same steps with explanations. Manual / by-hand alternatives live in [`docs/AUTH_EN.md`](docs/AUTH_EN.md) §3.

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

### 4. Generate an Ed25519 keypair

You need two files in `keys/`: a private `.key` (32 raw bytes, mode `0600`, **never commit**) and a public `.pub` (hex, 64 chars, **safe to commit**).

```bash
python3 tools/keygen.py
# or explicitly: python3 tools/keygen.py <login>
```

Reads `USERNAME` from `.env` when called without an argument (ignores the OS `$USERNAME` on Windows). Creates `keys/<login>.key` and `keys/<login>.pub`. Idempotent — if the private key already exists, it's reused and the public key is regenerated from it. Refuses placeholder values such as `default`.

Want to do it without the script? See [`docs/AUTH_EN.md`](docs/AUTH_EN.md) §3.1 for the equivalent Python heredoc.

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

### 6. Sign up with the server

Two REST calls in total: the server hands you a 60-second nonce, you sign it, you send the signature back. After this the server has `(username, pubkey)` cached in SQLite and never needs to touch GitHub for you again.

#### 6.1. With the script (recommended)

```bash
python3 tools/signup.py
```

The script:

1. Confirms `USERNAME` from `.env`.
2. Generates the keypair if step 4 hasn't run yet (idempotent).
3. **Pauses** and reprints the four `git` commands from step 5 — press Enter once the public key is pushed.
4. Calls `/api/auth/signup`, signs the nonce, calls `/api/auth/signup/verify`.

Source is ~200 LOC at [`tools/signup.py`](tools/signup.py). No hidden logic.

#### 6.2. OR by hand

Two `curl` calls; sign the nonce with the private key on disk:

```bash
# Call 1 — request a challenge. Server fetches your key.pub from GitHub,
# stores (pubkey, nonce) in Redis (TTL 60 s), returns the nonce.
curl -s -X POST "http://${BOC_AUTH_HOST:-127.0.0.1}:${BOC_AUTH_PORT:-8000}/api/auth/signup" \
     -H 'Content-Type: application/json' \
     -d "{\"username\":\"$USERNAME\"}"
# -> {"status":"challenge","nonce":"<HEX>","ttl":60}

# Call 2 — sign the nonce (raw bytes, not the hex string) and verify.
NONCE=<paste from above>
SIG=$(python3 - <<PY
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
key = Ed25519PrivateKey.from_private_bytes(open(f"keys/$USERNAME.key","rb").read())
print(key.sign(bytes.fromhex("$NONCE")).hex())
PY
)
curl -s -X POST "http://${BOC_AUTH_HOST:-127.0.0.1}:${BOC_AUTH_PORT:-8000}/api/auth/signup/verify" \
     -H 'Content-Type: application/json' \
     -d "{\"username\":\"$USERNAME\",\"sig\":\"$SIG\"}"
# -> {"status":"ok","username":"<login>"}
```

Error codes, the full failure-mode table, and the security rationale: [`docs/AUTH_EN.md`](docs/AUTH_EN.md) · [русская версия](docs/AUTH_RU.md). Back to [Quick setup](#quick-setup).

### 7. Verify and play

Smoke-test the game WebSocket:

```bash
python3 tools/login.py
```

This opens `ws://<host>:5555/`, sends a signed `hello` frame, waits for `auth_ok` + `welcome`, sends one `ping`, prints `pong`, closes. Two lines of green output means you're in.

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
| `docs/AUTH_EN.md`      | auth deep dive (REST signup, signing rules, failure modes)                 |
| `docs/API_EN.md`       | wire protocol (WebSocket frames, state messages, events, `state` examples) |
| `docs/RULES_EN.md`     | game rules (zones, trails, capture, death, anti-patterns)                  |
| `keys/<u>.pub`         | your **public** key (committed on the `<u>` branch of your fork)           |
| `keys/<u>.key`         | your **private** key (git-ignored, mode 0600)                              |

---

## How registration works (summary)

1. You generate an Ed25519 keypair (step 4 above).
2. Private key stays in `keys/<your-login>.key` (git-ignored, mode `0600`).
3. Public key is committed as `keys/<your-login>.pub` on a branch named after your GitHub login.
4. `tools/signup.py` (or two `curl` calls) tells the server your username; the server downloads the public key from `keys/<login>.pub` on your `<login>` branch and issues a short-lived nonce.
5. The script signs the nonce with your private key; the server verifies and stores `(username, pubkey)` in its SQLite auth DB. After that there is no further GitHub round-trip.
6. Every WebSocket connect carries a fresh signed `hello` (`{username, ts, sig}`). The server verifies it against the stored public key. No tokens, no cookies, no sessions.

`main` stays clean: PRs upstream don't touch your `.pub`. Your branch is your registration.

Deep references (Russian mirrors linked):
- [`docs/AUTH_EN.md`](docs/AUTH_EN.md) ([RU](docs/AUTH_RU.md)) — auth flow, error codes, security; complements [§6](#6-sign-up-with-the-server) and [Quick setup](#quick-setup)
- [`docs/API_EN.md`](docs/API_EN.md) ([RU](docs/API_RU.md)) — wire format (REST + WebSocket) and `state` examples
- [`docs/RULES_EN.md`](docs/RULES_EN.md) ([RU](docs/RULES_RU.md)) — game mechanics and anti-patterns
- [`docs/README_RU.md`](docs/README_RU.md) — full Russian install guide ([back to English Quick setup](README.md#quick-setup))

---

## Improve your bot

Open `bot.py`. The entire bot is one file. The only function you need to touch is `decide(state)` at the top.

- Read [`docs/RULES_EN.md`](docs/RULES_EN.md) for what wins and which moves kill you.
- Read [`docs/API_EN.md`](docs/API_EN.md) for the shape of `state` (it's just a JSON dict) and short snippets showing how to consume it.

`bot.go` and `bot.js` are placeholders that print "not implemented yet" — if you want to play in Go or Node, port `bot.py` over. The protocol is ~80 lines of real logic; everything else is `decide()` and reconnect plumbing.

---

## Links

- Server & live leaderboard: <https://battleofcode.com>
- Issue tracker: file bugs against `battleofcode/bocbot` upstream

## Licence

MIT — see [LICENSE](LICENSE).
