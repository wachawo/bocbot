# AUTH.md — Battle of Code authentication

**[English](https://github.com/battleofcode/bocbot/blob/main/docs/AUTH_EN.md)** | [Русский](https://github.com/battleofcode/bocbot/blob/main/docs/AUTH_RU.md)

> See also: [API.md](API_EN.md) for the realtime game protocol, [RULES.md](RULES_EN.md) for game rules.

Battle of Code uses Ed25519 signed-hello authentication: no passwords, no JWTs, no cookies, no shared secrets. The trust anchor is a public key the player publishes on their own GitHub fork — the server fetches it once at signup, stores it, and verifies every subsequent connection against it.

This document covers the **REST signup flow**. The **WebSocket hello** that every gameplay session sends is in [API.md](API_EN.md).

---

## 1. Identity model

A player is identified by their **GitHub login**. The trust anchor is an Ed25519 keypair:

| Half        | Where it lives                                                                                          | Who sees it |
|-------------|---------------------------------------------------------------------------------------------------------|-------------|
| Private key | `keys/<username>.key` — 32 raw bytes, mode `0600`                                                       | local only  |
| Public key  | `keys/<username>.pub` — hex-encoded 32 bytes, committed on the branch `<username>` of your `bocbot` fork | the world   |

The server fetches the public key once during signup from:

```
https://raw.githubusercontent.com/<username>/bocbot/<username>/keys/<username>.pub
```

After signup the server caches `(username, pubkey)` in its SQLite auth store and never talks to GitHub for that user again. No bearer token, no password, no certificate, no rotating session.

### Why GitHub?

- Anyone playing already has a GitHub account.
- The branch name = GitHub login = display name. One source of identity.
- Key rotation is `git push` on the same branch — no admin interaction required.
- The public key is auditable: anyone can `curl` it.

### Why Ed25519?

- 32-byte keys, 64-byte signatures, ~70 µs to sign on commodity hardware.
- Standard library support in Python (`cryptography`), Go, Node.
- Deterministic — no need for an RNG at signing time.

---

## 2. Signup flow — two REST calls

Both POST endpoints are rate-limited per source IP: **10 / hour**, **50 / day**.

The flow is two-step because the server must prove the caller actually controls the private key matching the GitHub-published public key. The nonce is the proof.

```
┌────────┐                            ┌────────┐                  ┌──────────┐
│ client │                            │ server │                  │  GitHub  │
└───┬────┘                            └────┬───┘                  └─────┬────┘
    │ POST /api/auth/signup               │                            │
    │ {"username":"alice"}                │                            │
    │ ─────────────────────────────────►  │                            │
    │                                     │ GET raw.../alice.pub       │
    │                                     │ ─────────────────────────► │
    │                                     │ ◄───── pubkey hex ──────── │
    │                                     │ store (pubkey, nonce) in Redis (TTL 60s)
    │ ◄────── {nonce, ttl} ──────────────│                            │
    │                                     │                            │
    │ sign(nonce_bytes, priv_key)         │                            │
    │                                     │                            │
    │ POST /api/auth/signup/verify        │                            │
    │ {"username":"alice","sig":"..."}    │                            │
    │ ─────────────────────────────────►  │                            │
    │                                     │ Ed25519_verify(pubkey, nonce_bytes, sig)
    │                                     │ INSERT INTO auth(username, pubkey)
    │ ◄──────── {status:"ok"} ────────────│                            │
```

### Step 1 — `POST /api/auth/signup`

Request:

```json
{"username": "alice"}
```

Response **200**:

```json
{"status": "challenge", "nonce": "0f1e2d3c4b5a69788796a5b4c3d2e1f0", "ttl": 60}
```

The `nonce` is hex-encoded 16 bytes. You must sign the **raw bytes** (`bytes.fromhex(nonce)`), not the hex string.

Errors:

| Status | `error`               | When                                                                  |
|-------:|-----------------------|-----------------------------------------------------------------------|
| 400    | `bad_username`        | empty, reserved (`default`, `admin`, `root`, …), or fails GitHub regex |
| 404    | `pubkey_fetch_failed` | branch or file not found at the expected URL                          |
| 400    | `pubkey_fetch_failed` | `key.pub` body has no 64-char hex token                                |
| 429    | `rate_limited`        | per-IP cap exceeded                                                   |
| 502    | `pubkey_fetch_failed` | GitHub unreachable                                                    |

### Step 2 — `POST /api/auth/signup/verify`

Sign the **raw bytes** of the nonce with the Ed25519 private key. Submit the hex-encoded signature.

Request:

```json
{"username": "alice", "sig": "abcd1234..."}
```

Response **200**:

```json
{"status": "ok", "username": "alice"}
```

Errors:

| Status | `error`         | When                                                       |
|-------:|-----------------|------------------------------------------------------------|
| 400    | `nonce_missing` | no active signup nonce (expired after 60 s, or never issued) |
| 401    | `bad_signature` | signature does not verify against the stored public key    |
| 500    | `db_error`      | server-side persistence failure                            |

---

## 3. Try it by hand

The Python one-liner below is the minimum to sign a nonce against the private key on disk. The full sequence is also in the top-level [`README.md`](../README.md#6-sign-up--by-hand).

```bash
# Step 1: request the challenge
curl -s -X POST "http://127.0.0.1:8000/api/auth/signup" \
     -H 'Content-Type: application/json' \
     -d '{"username":"alice"}'
# -> {"status":"challenge","nonce":"<HEX>","ttl":60}

# Step 2: sign the nonce
NONCE=<paste from above>
SIG=$(python3 - <<PY
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
key = Ed25519PrivateKey.from_private_bytes(open("keys/alice.key","rb").read())
print(key.sign(bytes.fromhex("$NONCE")).hex())
PY
)

# Step 3: verify
curl -s -X POST "http://127.0.0.1:8000/api/auth/signup/verify" \
     -H 'Content-Type: application/json' \
     -d "{\"username\":\"alice\",\"sig\":\"$SIG\"}"
# -> {"status":"ok","username":"alice"}
```

The bundled `tools/signup.py` does exactly the same three calls plus key generation and a guard-rail around `USERNAME=default`. Read its source (~200 LOC) end to end — there is no hidden logic.

---

## 4. Lost your private key

There is no recovery path. The private key is the credential. If it's gone:

1. Generate a new keypair (`python3 tools/keygen.py`).
2. Force-push the new `keys/<login>.pub` to the `<login>` branch of your fork.
3. Re-run `python3 tools/signup.py`. The server will fetch the new public key from GitHub and overwrite the stored row.

Step 2 force-pushes because the server **doesn't trust git history** — it re-reads `keys/<login>.pub` from whatever HEAD of the `<login>` branch currently points to. So just `git push --force-with-lease origin <login>` is enough.

---

## 5. Security notes

- **The private key is the credential.** Anything that can read `keys/<login>.key` can play as you. Mode `0600` is enforced by `tools/keygen.py`; the `.gitignore` excludes `keys/*.key`.
- **Nonce TTL is 60 seconds.** If signup takes longer (slow GitHub fetch, manual signing) you'll get `nonce_missing` and need to restart from Step 1.
- **Timestamp skew on the hello frame is ±30 s.** Your machine clock must be roughly correct. NTP usually handles this.
- **There is no logout.** Every WebSocket connect signs a fresh `hello`. To "log out" of a stolen key, generate a new keypair (Section 4) — the old public key on GitHub gets overwritten and the new one replaces it in the server's auth DB on next signup.
- **No password reset, no email recovery.** The system has no email and no password. If you control the GitHub branch `<login>` of your `bocbot` fork, you control the identity `<login>`.

---

## 6. Why this design

| Constraint                           | Why it falls out of this design                                              |
|--------------------------------------|------------------------------------------------------------------------------|
| Anyone can sign up without contacting us | The server pulls the public key from public infrastructure (GitHub).      |
| Identity is verifiable from outside  | `curl https://raw.githubusercontent.com/<u>/bocbot/<u>/keys/<u>.pub` is enough. |
| No password reset, no email          | The trust anchor is on GitHub. Whoever controls that branch is the player.   |
| Cheap to verify                      | Ed25519 verify is ~30 µs. No DB lookup per packet beyond the cached pubkey. |
| No session state                     | Every connect signs a fresh nonce-equivalent (`username:ts`). Stateless server. |

---

## 7. References

- [`tools/keygen.py`](../tools/keygen.py) — keypair generator (idempotent).
- [`tools/signup.py`](../tools/signup.py) — end-to-end signup with prompts.
- [`tools/login.py`](../tools/login.py) — WebSocket smoke-test.
- [`API.md`](API_EN.md) — gameplay wire format (uses the same private key to sign each hello).
- RFC 8032 — Ed25519 spec.
