# bocbot

Player template for **Battle of Code** — a multiplayer territory-capture game where everyone runs their own bot (or plays manually from the terminal).

Fork this repo. Run two scripts. You're in.

## Quickstart — Linux, step by step

Registration is just three things: an Ed25519 keypair on disk, the **public** half committed on a branch named after your GitHub login, the **private** half kept locally. Steps 4-7 below are also automated by `python3 tools/signup.py` if you'd rather not run each call by hand.

Replace `<login>` with your GitHub login everywhere below.

### 1. Fork & clone

```bash
gh repo fork battleofcode/bocbot --clone --remote
cd bocbot
```

(or fork via the GitHub UI, then `git clone git@github.com:<login>/bocbot.git`)

### 2. Install Python dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

This pulls in `cryptography` (keygen + signatures), `websockets` (game transport), `rich` (interactive CLI) and `requests` (signup REST).

### 3. Configure `.env`

```bash
cp .env.example .env
$EDITOR .env       # set USERNAME=<login>; tweak BOC_AUTH_* / BOC_GAME_* if your server is not on localhost
```

### 4. Generate an Ed25519 keypair

```bash
python3 tools/keygen.py            # picks <login> up from .env
```

What this produces:
- `keys/<login>.key` — 32 raw bytes, mode `0600`. Git-ignored.
- `keys/<login>.pub` — hex-encoded 32-byte public key, one line + comment. Commit-able.

### 5. Push the public key on your branch

```bash
git checkout -b <login>
git add keys/<login>.pub
git commit -m "register key"
git push -u origin <login>
```

`main` stays clean; your branch holds your registration. The server fetches the key from `https://raw.githubusercontent.com/<login>/bocbot/<login>/keys/<login>.pub`.

### 6. Sign up against the REST API

```bash
python3 tools/signup.py
```

The script calls `POST /api/auth/signup` (server fetches the GitHub key, returns a nonce), signs the nonce with the private key, and submits `POST /api/auth/signup/verify`. From here on the server-side SQLite holds `(username, pubkey)`.

You can also do it manually — see [`docs/PROTO.md`](docs/PROTO.md) for the curl recipe.

### 7. Verify & play

```bash
python3 tools/login.py             # WebSocket smoke-test: hello -> ping -> pong
./play.sh                          # join a game in the terminal (Rich UI, WSAD)
# or
python3 bot.py                     # run the starter bot (it will lose — that's the point)
```

If you want to return to `main` to work on the bot itself without polluting your registration branch:

```bash
git checkout main
```

That's it.

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
| `docs/`                | `RULES.md`, `PROTO.md`, `EXAMPLES.md`                                      |
| `keys/<u>.pub`         | your **public** key (committed on the `<u>` branch of your fork)           |
| `keys/<u>.key`         | your **private** key (git-ignored, mode 0600)                              |

## How registration works

1. You generate an Ed25519 keypair (`tools/keygen.py`).
2. Private key stays in `keys/<your-login>.key` (git-ignored, mode `0600`).
3. Public key is committed as `keys/<your-login>.pub` on a branch named after your GitHub login.
4. `tools/signup.py` (or two curl calls) tells the server your username; the server downloads the public key from `keys/<login>.pub` on your `<login>` branch and issues a short-lived nonce.
5. The script signs the nonce with your private key; the server verifies and stores `(username, pubkey)` in its SQLite auth DB. After that there is no further GitHub round-trip.
6. Every WebSocket connect carries a fresh signed `hello` (`{username, ts, sig}`). The server verifies it against the stored public key. No tokens, no cookies, no sessions.

`main` stays clean: PRs upstream don't touch your `.pub`. Your branch is your registration.

See [`docs/PROTO.md`](docs/PROTO.md) for the wire-level details (REST + WebSocket) and [`docs/RULES.md`](docs/RULES.md) for the game rules.

## Improve your bot

Open `bot.py`. The entire bot is in one file, and the only function you need to touch is `decide(state)` at the top. Read `docs/RULES.md` for what wins, `docs/PROTO.md` for the wire format, and `docs/EXAMPLES.md` for a cookbook of patterns (avoid walls, hunt enemies, distance metrics).

`bot.go` and `bot.js` are placeholders that just print "not implemented yet" — if you want to play in Go or Node, port `bot.py` over (the protocol is ~80 lines of real logic; everything else is `decide()` and reconnect plumbing).

## Screenshot

```
TODO: drop a terminal recording / GIF of the Rich UI here.
```

## Links

- Server & live leaderboard: <https://battleofcode.com>
- Issue tracker: file bugs against `battleofcode/bocbot` upstream

## Licence

MIT — see [LICENSE](LICENSE).
