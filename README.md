# bocbot

Player template for **Battle of Code** — a multiplayer territory-capture game where everyone runs their own bot (or plays manually from the terminal).

Fork this repo. Run two scripts. You're in.

## Quickstart

```bash
gh repo fork battleofcode/bocbot --clone --remote
cd bocbot
./scripts/setup.sh        # generate Ed25519 key, register on your branch
./scripts/play.sh         # play manually in the terminal
# or
cd bot/mybot && python3 bot.py    # run the starter bot (it will lose)
```

That's it. You're now registered and connected to `battleofcode.com`.

## What's in the box

| Path                   | What it is                                                  |
|------------------------|-------------------------------------------------------------|
| `client/`              | terminal CLI player (Rich UI, WSAD)                         |
| `bot/example/`         | working reference bot — copy this to start                  |
| `bot/mybot/`           | empty stub where **your** bot lives                         |
| `bot/sdk/python/`      | official Python SDK (`from bocbot import Bot`)             |
| `bot/sdk/{nodejs,go}/` | placeholders — coming in Phase D                            |
| `scripts/`             | `setup.sh`, `validate.sh`, `play.sh` (+ Windows `.ps1`)     |
| `docs/`                | `GAME-RULES.md`, `PROTOCOL.md`, `EXAMPLES.md`               |
| `.bocbot/key.pub`     | your **public** key (committed on your branch)              |
| `keys/`                | private keys (git-ignored)                                  |

## How registration works

1. `setup.sh` generates an Ed25519 keypair.
2. Private key stays in `keys/<your-login>.key` (git-ignored, mode 0600).
3. Public key is committed as `.bocbot/key.pub` on a branch named after your GitHub login.
4. The server reads your branch over the public GitHub API and trusts that public key.
5. When you connect, the server challenges you to sign a nonce — the client signs it with the private key.

`main` stays clean: PRs upstream don't touch `.bocbot/`. Your branch is your registration.

## Improve your bot

Open `bot/mybot/bot.py`. Replace the trivial `decide()` with something smarter. Read `bot/example/ai.py` for inspiration. Read `docs/GAME-RULES.md` for what wins. Read `docs/PROTOCOL.md` for what the server tells you.

## Screenshot

```
TODO: drop a terminal recording / GIF of the Rich UI here.
```

## Links

- Server & live leaderboard: <https://battleofcode.com>
- Issue tracker: file bugs against `battleofcode/bocbot` upstream

## Licence

MIT — see [LICENSE](LICENSE).
