# bocbot

[English](https://github.com/battleofcode/bocbot/blob/main/README.md) | [中文](https://github.com/battleofcode/bocbot/blob/main/docs/README_ZH.md) | [हिन्दी](https://github.com/battleofcode/bocbot/blob/main/docs/README_HI.md) | [Español](https://github.com/battleofcode/bocbot/blob/main/docs/README_ES.md) | **[Français](https://github.com/battleofcode/bocbot/blob/main/docs/README_FR.md)** | [العربية](https://github.com/battleofcode/bocbot/blob/main/docs/README_AR.md) | [Русский](https://github.com/battleofcode/bocbot/blob/main/docs/README_RU.md)

Modèle de joueur pour **Battle of Code** — un jeu multijoueur de capture de territoire où chacun lance son propre bot (ou joue manuellement depuis le terminal).

**Ce que ce modèle vous donne**

- Un client terminal avec UI Rich (`client/`) fonctionnel, jouable au WSAD.
- Un bot de départ (`bot.py`) à éditer — c'est le bot entier, un seul fichier.
- Trois petits scripts dans `tools/` qui vous inscrivent sur le serveur du jeu.
- Une documentation qui explique exactement à quoi ressemblent le format réseau et l'authentification.

Rien ici ne « phone home », rien n'est obscurci. L'inscription complète tient en 30 lignes de REST que vous pouvez exécuter à la main. Nous livrons aussi un script qui le fait pour vous, mais la première fois — et c'est recommandé — passez étape par étape pour voir ce qui se passe.

---

## Ce qu'est vraiment l'inscription

Trois choses, pas plus :

1. Une **paire de clés Ed25519** sur votre disque. La privée (`.key`) reste locale. La publique (`.pub`) est hex, 64 caractères, une ligne.
2. Une **branche dans votre fork GitHub** nommée d'après votre login. Sur cette branche se trouve `keys/<login>.pub`. Le serveur la lit une fois.
3. Un **challenge signé**. Le serveur vous donne un nonce aléatoire, vous le signez avec la clé privée, le serveur vérifie contre la clé publique qu'il vient de récupérer sur GitHub.

C'est tout le modèle de confiance. Pas de mot de passe, pas de JWT, pas de cookie. Chaque session de jeu répète l'étape 3 avec un nouveau frame `hello` signé.

---

## Quickstart — manuel, étape par étape

Faites-le une fois à la main. Ensuite le script fait les mêmes appels.

Remplacez `<login>` par votre login GitHub partout.

### 1. Fork & clone

```bash
gh repo fork battleofcode/bocbot --clone --remote
cd bocbot
```

Ou via l'UI web GitHub, puis `git clone git@github.com:<login>/bocbot.git`.

### 2. Installer les dépendances Python

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Vous obtenez :
- `cryptography` — keygen + signatures Ed25519
- `websockets` — transport du jeu
- `rich` — rendu CLI interactif
- `requests` — REST signup

### 3. Configurer `.env`

```bash
cp .env.example .env
$EDITOR .env
```

Mettez `USERNAME=<login>`. Ajustez `BOC_AUTH_HOST` / `BOC_GAME_HOST` si le serveur n'est pas sur `localhost`.

### 4. Générer une paire de clés Ed25519 — à la main

Une seule ligne de Python suffit (pas besoin d'outil supplémentaire) :

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

Ce que vous obtenez :

- `keys/<login>.key` — 32 octets bruts, mode `0600`. **Ignoré par Git.** Ne committez jamais ce fichier.
- `keys/<login>.pub` — clé publique hex, une ligne + commentaire. Sûr à committer.

> La même chose sous forme de script : `python3 tools/keygen.py`. C'est littéralement la commande ci-dessus avec un wrapper CLI.

### 5. Pusher la clé publique sur votre branche

```bash
git checkout -b <login>
git add keys/<login>.pub
git commit -m "register key"
git push -u origin <login>
```

`main` reste propre. Votre branche `<login>` contient votre inscription. Le serveur la lira à :

```
https://raw.githubusercontent.com/<login>/bocbot/<login>/keys/<login>.pub
```

Vous pouvez `curl` cet URL pour vérifier qu'il est accessible.

### 6. S'inscrire — à la main

Deux appels REST.

**Appel 1 : demander un challenge.** Le serveur récupère votre `key.pub` sur GitHub, stocke `(pubkey, nonce)` dans Redis avec un TTL de 60 secondes, et retourne le nonce.

```bash
curl -s -X POST "http://${BOC_AUTH_HOST:-127.0.0.1}:${BOC_AUTH_PORT:-8000}/api/auth/signup" \
     -H 'Content-Type: application/json' \
     -d "{\"username\":\"$USERNAME\"}"
```

Réponse :

```json
{"status":"challenge","nonce":"0f1e2d3c4b5a69788796a5b4c3d2e1f0","ttl":60}
```

**Appel 2 : signer le nonce et vérifier.** Le nonce est hex. Décodez-le en octets, signez, encodez la signature en hex, renvoyez.

```bash
NONCE=0f1e2d3c4b5a69788796a5b4c3d2e1f0   # de la réponse précédente
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

Réponse :

```json
{"status":"ok","username":"<login>"}
```

Le serveur a maintenant `(username, pubkey)` en cache dans son store d'auth SQLite. Il ne parlera plus à GitHub pour vous.

> La même chose sous forme de script : `python3 tools/signup.py`. Il affiche exactement quel appel il fait à chaque étape. Voir [`docs/AUTH.md`](AUTH.md) pour la référence complète.

### 7. Vérifier que vous pouvez jouer

Smoke-test du WebSocket du jeu :

```bash
python3 tools/login.py
```

Cela ouvre `ws://<host>:5555/`, envoie un frame `hello` signé, attend `auth_ok` + `welcome`, envoie un `ping`, affiche `pong`, ferme. Si vous voyez deux lignes vertes en sortie, vous êtes connecté.

Maintenant, jouez pour de vrai :

```bash
./play.sh                          # client terminal Rich UI, WSAD
# ou
python3 bot.py                     # le bot de départ — il va perdre, c'est normal
```

Si vous voulez revenir sur `main` pour travailler sur le bot :

```bash
git checkout main
```

Voilà tout le processus. Vous l'avez fait à la main une fois. La prochaine fois le script s'en occupe.

---

## Quickstart — scripté

Si vous voulez juste jouer et comprenez déjà ce qui se passe :

```bash
gh repo fork battleofcode/bocbot --clone --remote
cd bocbot
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
cp .env.example .env && $EDITOR .env       # mettez USERNAME=<login>
python3 tools/signup.py                    # keygen + REST signup, vous demande quand pusher
./play.sh
```

`tools/signup.py` :

1. Copie `.env.example` → `.env` s'il manque, confirme `USERNAME`.
2. Génère la paire de clés (idempotent — si `keys/<login>.key` existe, il le réutilise).
3. **Pause** et affiche les quatre commandes `git` à exécuter pour pusher la clé publique. Appuyez sur Entrée quand c'est fait.
4. Appelle `/api/auth/signup`, signe le nonce, appelle `/api/auth/signup/verify`.

Lisez la source — 200 lignes.

---

## Jouer manuellement

`./play.sh` ouvre une UI terminal Rich. L'adresse et le username viennent de votre `.env` (`BOC_GAME_HOST`, `BOC_GAME_PORT`, `USERNAME`) ; les flags CLI de `client/client.py` priment.

| Touche         | Action |
|----------------|--------|
| `W`            | haut    |
| `A`            | gauche  |
| `S`            | bas     |
| `D`            | droite  |
| `Esc` / `Ctrl+C` × 2 | quitter |

Le client se reconnecte automatiquement quand le WebSocket tombe ; le serveur reprend votre joueur en pause (même `id`, position, zone) tant que `PAUSE_TIMEOUT` n'est pas écoulé.

Lancez comme spectateur avec `-f N` pour suivre le joueur vivant actuellement classé N (1..128) :

```bash
python3 client/client.py -f 1
```

---

## Ce qu'il y a dans la boîte

| Chemin                 | Ce que c'est                                                               |
|------------------------|----------------------------------------------------------------------------|
| `bot.py`               | bot de départ, Python — **éditez `decide()`**                              |
| `bot.go`               | bot de départ, Go — stub, pas encore implémenté                            |
| `bot.js`               | bot de départ, Node.js — stub, pas encore implémenté                       |
| `client/`              | joueur CLI terminal (Rich UI, WSAD) — pour le jeu humain                   |
| `play.sh`              | lance le client CLI vers `battleofcode.com`                                |
| `tools/keygen.py`      | génère une paire Ed25519 dans `keys/<u>.key` + `keys/<u>.pub`              |
| `tools/signup.py`      | inscription end-to-end contre l'API REST                                   |
| `tools/login.py`       | smoke-test WebSocket (hello → ping → pong)                                 |
| `docs/AUTH.md`         | détails d'authentification (REST signup, règles de signature, erreurs)     |
| `docs/API.md`          | protocole réseau (frames WebSocket, messages state, événements)            |
| `docs/RULES.md`        | règles du jeu (zones, trails, capture, conditions de mort)                 |
| `docs/EXAMPLES.md`     | livre de recettes pour la prise de décision du bot                         |
| `keys/<u>.pub`         | votre clé **publique** (commitée sur la branche `<u>` de votre fork)       |
| `keys/<u>.key`         | votre clé **privée** (ignorée par git, mode 0600)                          |

---

## Comment marche l'inscription (résumé)

1. Vous générez une paire de clés Ed25519 (`tools/keygen.py` ou le one-liner Python ci-dessus).
2. La clé privée reste dans `keys/<your-login>.key` (ignorée par git, mode `0600`).
3. La clé publique est commitée sous `keys/<your-login>.pub` sur une branche nommée d'après votre login GitHub.
4. `tools/signup.py` (ou deux appels `curl`) annonce votre username au serveur ; le serveur télécharge la clé publique depuis `keys/<login>.pub` sur votre branche `<login>` et émet un nonce de courte durée.
5. Le script signe le nonce avec votre clé privée ; le serveur vérifie et stocke `(username, pubkey)` dans sa DB auth SQLite. Après ça, plus d'aller-retour GitHub.
6. Chaque connexion WebSocket porte un `hello` signé frais (`{username, ts, sig}`). Le serveur le vérifie contre la clé publique stockée. Pas de token, pas de cookie, pas de session.

`main` reste propre : les PR upstream ne touchent pas votre `.pub`. Votre branche est votre inscription.

Références approfondies :
- [`docs/AUTH.md`](AUTH.md) — le flux d'auth, codes d'erreur, notes de sécurité
- [`docs/API.md`](API.md) — le format réseau (REST + WebSocket)
- [`docs/RULES.md`](RULES.md) — mécaniques du jeu

---

## Améliorez votre bot

Ouvrez `bot.py`. Le bot entier tient dans un fichier. La seule fonction à toucher est `decide(state)` en haut.

- Lisez [`docs/RULES.md`](RULES.md) pour ce qui fait gagner.
- Lisez [`docs/API.md`](API.md) pour la forme de `state` (c'est juste un dict JSON).
- Lisez [`docs/EXAMPLES.md`](EXAMPLES.md) pour le livre de recettes (éviter les murs, chasser, métriques de distance).

`bot.go` et `bot.js` sont des placeholders qui affichent "not implemented yet" — si vous voulez jouer en Go ou Node, portez `bot.py`. Le protocole, c'est ~80 lignes de logique réelle ; tout le reste, c'est `decide()` et la tuyauterie de reconnexion.

---

## Liens

- Serveur et leaderboard live : <https://battleofcode.com>
- Issue tracker : signalez les bugs sur l'upstream `battleofcode/bocbot`

## Licence

MIT — voir [LICENSE](../LICENSE).
