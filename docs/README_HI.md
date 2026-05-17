# bocbot

[English](https://github.com/battleofcode/bocbot/blob/main/README.md) | [中文](https://github.com/battleofcode/bocbot/blob/main/docs/README_ZH.md) | **[हिन्दी](https://github.com/battleofcode/bocbot/blob/main/docs/README_HI.md)** | [Español](https://github.com/battleofcode/bocbot/blob/main/docs/README_ES.md) | [Français](https://github.com/battleofcode/bocbot/blob/main/docs/README_FR.md) | [العربية](https://github.com/battleofcode/bocbot/blob/main/docs/README_AR.md) | [Русский](https://github.com/battleofcode/bocbot/blob/main/docs/README_RU.md)

**Battle of Code** के लिए प्लेयर टेम्पलेट — एक मल्टीप्लेयर टेरिटरी-कैप्चर गेम जहाँ हर कोई अपना खुद का बॉट चलाता है (या टर्मिनल से हाथ से खेलता है)।

**यह टेम्पलेट आपको क्या देता है**

- एक काम करने वाला Rich-UI टर्मिनल क्लाइंट (`client/`) जिसे आप WSAD से खेल सकते हैं।
- एक स्टार्टर बॉट (`bot.py`) जिसे आप एडिट कर सकते हैं — पूरा बॉट यही है, एक फ़ाइल।
- तीन छोटे `tools/` स्क्रिप्ट जो आपको गेम सर्वर पर रजिस्टर करते हैं।
- डॉक्स जो ठीक-ठीक बताते हैं कि वायर-फॉर्मेट और auth कैसे दिखते हैं।

यहाँ कुछ भी "होम कॉल" नहीं करता, कुछ भी obfuscated नहीं है। पूरा रजिस्ट्रेशन 30 लाइनों का REST है जो आप हाथ से चला सकते हैं। हम एक स्क्रिप्ट भी देते हैं जो यह आपके लिए कर देती है, लेकिन पहली बार — और चाहिए — कदम-दर-कदम जाएँ ताकि आप देख सकें कि क्या हो रहा है।

---

## रजिस्ट्रेशन असल में क्या है

बस तीन चीज़ें, इससे ज़्यादा नहीं:

1. आपकी डिस्क पर एक **Ed25519 keypair**। प्राइवेट (`.key`) लोकल रहता है। पब्लिक (`.pub`) hex है, 64 कैरेक्टर, एक लाइन।
2. आपके GitHub fork में एक **ब्रांच** जिसका नाम आपके login के नाम पर है। उस ब्रांच पर `keys/<login>.pub` है। सर्वर इसे एक बार पढ़ता है।
3. एक **साइन किया हुआ challenge**। सर्वर आपको एक रैंडम nonce देता है, आप उसे प्राइवेट key से साइन करते हैं, सर्वर GitHub से अभी फ़ेच की गई पब्लिक key के विरुद्ध वेरिफाई करता है।

यही पूरा ट्रस्ट मॉडल है। कोई पासवर्ड नहीं, कोई JWT नहीं, कोई cookie नहीं। हर गेम सेशन step 3 को एक नए साइन किए गए `hello` फ़्रेम के साथ दोहराता है।

---

## Quickstart — हाथ से, कदम दर कदम

एक बार हाथ से करें। उसके बाद स्क्रिप्ट वही calls करती है।

नीचे हर जगह `<login>` को अपने GitHub login से replace करें।

### 1. Fork & clone

```bash
gh repo fork battleofcode/bocbot --clone --remote
cd bocbot
```

या GitHub web UI से fork करें, फिर `git clone git@github.com:<login>/bocbot.git`।

### 2. Python निर्भरताएँ इंस्टॉल करें

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

आपको मिलेगा:
- `cryptography` — Ed25519 keygen + signatures
- `websockets` — गेम ट्रांसपोर्ट
- `rich` — इंटरैक्टिव CLI रेंडरिंग
- `requests` — REST signup

### 3. `.env` कॉन्फ़िगर करें

```bash
cp .env.example .env
$EDITOR .env
```

`USERNAME=<login>` सेट करें। अगर सर्वर `localhost` पर नहीं है तो `BOC_AUTH_HOST` / `BOC_GAME_HOST` adjust करें।

### 4. Ed25519 keypair बनाएँ — हाथ से

आप एक Python one-liner से कर सकते हैं (कोई extra tool नहीं चाहिए):

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

आपको जो मिला:

- `keys/<login>.key` — 32 raw bytes, mode `0600`। **Git-ignored।** इसे कभी commit मत करें।
- `keys/<login>.pub` — hex पब्लिक key, एक लाइन + comment। Commit करना safe।

> स्क्रिप्ट रूप में वही: `python3 tools/keygen.py`। यह ठीक ऊपर वाला one-liner है CLI wrapper के साथ।

### 5. पब्लिक key को अपनी ब्रांच पर push करें

```bash
git checkout -b <login>
git add keys/<login>.pub
git commit -m "register key"
git push -u origin <login>
```

`main` साफ़ रहती है। आपकी `<login>` ब्रांच आपका रजिस्ट्रेशन रखती है। सर्वर इसे यहाँ से पढ़ेगा:

```
https://raw.githubusercontent.com/<login>/bocbot/<login>/keys/<login>.pub
```

आप खुद उस URL को `curl` कर सकते हैं ताकि देखें वो reachable है।

### 6. साइनअप करें — हाथ से

दो REST calls।

**Call 1: एक challenge request करें।** सर्वर GitHub से आपकी `key.pub` फ़ेच करता है, `(pubkey, nonce)` को Redis में 60-second TTL के साथ store करता है, और nonce वापस करता है।

```bash
curl -s -X POST "http://${BOC_AUTH_HOST:-127.0.0.1}:${BOC_AUTH_PORT:-8000}/api/auth/signup" \
     -H 'Content-Type: application/json' \
     -d "{\"username\":\"$USERNAME\"}"
```

Response:

```json
{"status":"challenge","nonce":"0f1e2d3c4b5a69788796a5b4c3d2e1f0","ttl":60}
```

**Call 2: nonce sign करें और verify करें।** nonce hex है। उसे bytes में decode करें, sign करें, signature को hex-encode करें, वापस भेजें।

```bash
NONCE=0f1e2d3c4b5a69788796a5b4c3d2e1f0   # पिछले response से
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

अब सर्वर के पास SQLite auth store में `(username, pubkey)` cached है। वह आपके लिए फिर GitHub से बात नहीं करेगा।

> स्क्रिप्ट रूप में वही: `python3 tools/signup.py`। यह हर step पर बताता है कि कौन सा call कर रहा है। पूरे reference के लिए [`docs/AUTH.md`](AUTH.md) देखें।

### 7. वेरिफाई करें कि आप खेल सकते हैं

गेम WebSocket का smoke-test:

```bash
python3 tools/login.py
```

यह `ws://<host>:5555/` खोलता है, एक साइन किया हुआ `hello` फ़्रेम भेजता है, `auth_ok` + `welcome` का इंतज़ार करता है, एक `ping` भेजता है, `pong` print करता है, बंद करता है। अगर दो हरी लाइनें दिखें तो आप अंदर हैं।

अब वास्तव में खेलें:

```bash
./play.sh                          # Rich UI टर्मिनल क्लाइंट, WSAD
# या
python3 bot.py                     # स्टार्टर बॉट — यह हारेगा, कोई बात नहीं
```

अगर आप बॉट पर काम करने के लिए `main` पर वापस आना चाहते हैं:

```bash
git checkout main
```

यही पूरा flow है। आपने एक बार हाथ से किया। अगली बार स्क्रिप्ट करेगी।

---

## Quickstart — स्क्रिप्ट से

अगर आप बस खेलना चाहते हैं और पहले से समझते हैं कि क्या हो रहा है:

```bash
gh repo fork battleofcode/bocbot --clone --remote
cd bocbot
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
cp .env.example .env && $EDITOR .env       # USERNAME=<login> सेट करें
python3 tools/signup.py                    # keygen + REST signup, push के लिए तैयार होने पर पूछेगी
./play.sh
```

`tools/signup.py`:

1. `.env` न हो तो `.env.example` → `.env` कॉपी करता है, `USERNAME` कन्फर्म करता है।
2. keypair बनाता है (idempotent — अगर `keys/<login>.key` है तो उसे reuse करता है)।
3. **रुकता है** और पब्लिक key push करने के लिए चार `git` commands print करता है। Push के बाद Enter दबाएँ।
4. `/api/auth/signup` call करता है, nonce sign करता है, `/api/auth/signup/verify` call करता है।

Source पढ़ें — 200 lines है।

---

## हाथ से खेलना

`./play.sh` एक Rich टर्मिनल UI खोलता है। Address और username `.env` से आते हैं (`BOC_GAME_HOST`, `BOC_GAME_PORT`, `USERNAME`); `client/client.py` के CLI flags उन्हें override करते हैं।

| Key            | क्रिया |
|----------------|--------|
| `W`            | ऊपर    |
| `A`            | बाएँ   |
| `S`            | नीचे   |
| `D`            | दाएँ   |
| `Esc` / `Ctrl+C` × 2 | बाहर |

WebSocket गिरने पर क्लाइंट auto-reconnect करता है; जब तक `PAUSE_TIMEOUT` खत्म नहीं हुआ, सर्वर आपके paused प्लेयर को resume करता है (वही `id`, position, zone)।

`-f N` से spectator के रूप में चलाएँ ताकि वर्तमान में N (1..128) रैंक के live प्लेयर को follow करें:

```bash
python3 client/client.py -f 1
```

---

## बॉक्स में क्या है

| Path                   | यह क्या है                                                                 |
|------------------------|----------------------------------------------------------------------------|
| `bot.py`               | स्टार्टर बॉट, Python — **`decide()` एडिट करें**                            |
| `bot.go`               | स्टार्टर बॉट, Go — stub, अभी implement नहीं                                |
| `bot.js`               | स्टार्टर बॉट, Node.js — stub, अभी implement नहीं                            |
| `client/`              | टर्मिनल CLI प्लेयर (Rich UI, WSAD) — मानव खेलने के लिए                     |
| `play.sh`              | `battleofcode.com` के विरुद्ध CLI क्लाइंट लॉन्च                            |
| `tools/keygen.py`      | `keys/<u>.key` + `keys/<u>.pub` में Ed25519 keypair generate               |
| `tools/signup.py`      | REST API के विरुद्ध end-to-end signup                                       |
| `tools/login.py`       | WebSocket smoke-test (hello → ping → pong)                                 |
| `docs/AUTH.md`         | auth विस्तार से (REST signup, signing नियम, error codes)                   |
| `docs/API.md`          | wire protocol (WebSocket frames, state messages, events)                   |
| `docs/RULES.md`        | गेम नियम (zones, trails, capture, मृत्यु conditions)                       |
| `docs/EXAMPLES.md`     | बॉट decision-making cookbook                                                |
| `keys/<u>.pub`         | आपकी **पब्लिक** key (आपके fork की `<u>` ब्रांच पर committed)               |
| `keys/<u>.key`         | आपकी **प्राइवेट** key (git-ignored, mode 0600)                              |

---

## रजिस्ट्रेशन कैसे काम करता है (सारांश)

1. आप एक Ed25519 keypair generate करते हैं (`tools/keygen.py` या ऊपर का Python one-liner)।
2. प्राइवेट key `keys/<your-login>.key` में रहती है (git-ignored, mode `0600`)।
3. पब्लिक key `keys/<your-login>.pub` के रूप में आपके GitHub login के नाम वाली ब्रांच पर commit होती है।
4. `tools/signup.py` (या दो `curl` calls) सर्वर को आपका username बताते हैं; सर्वर आपकी `<login>` ब्रांच पर `keys/<login>.pub` से पब्लिक key download करता है और एक short-lived nonce जारी करता है।
5. स्क्रिप्ट आपकी प्राइवेट key से nonce को sign करती है; सर्वर verify करता है और `(username, pubkey)` को अपनी SQLite auth DB में store करता है। उसके बाद कोई GitHub round-trip नहीं।
6. हर WebSocket connect एक fresh साइन किया हुआ `hello` (`{username, ts, sig}`) carry करता है। सर्वर इसे stored पब्लिक key के विरुद्ध verify करता है। कोई token नहीं, cookie नहीं, session नहीं।

`main` साफ़ रहता है: upstream PRs आपकी `.pub` को नहीं छूते। आपकी ब्रांच आपका रजिस्ट्रेशन है।

विस्तृत references:
- [`docs/AUTH.md`](AUTH.md) — auth flow, error codes, security notes
- [`docs/API.md`](API.md) — wire format (REST + WebSocket)
- [`docs/RULES.md`](RULES.md) — गेम mechanics

---

## अपना बॉट सुधारें

`bot.py` खोलें। पूरा बॉट एक file है। आपको ऊपर की `decide(state)` ही एक function छूनी है।

- [`docs/RULES.md`](RULES.md) पढ़ें कि जीतता क्या है।
- [`docs/API.md`](API.md) पढ़ें `state` का shape (यह सिर्फ JSON dict है)।
- [`docs/EXAMPLES.md`](EXAMPLES.md) पढ़ें recipe book के लिए (दीवारों से बचना, hunting, distance metrics)।

`bot.go` और `bot.js` placeholders हैं जो "not implemented yet" print करते हैं — अगर आप Go या Node में खेलना चाहते हैं तो `bot.py` को port करें। Protocol ~80 lines की वास्तविक logic है; बाकी सब `decide()` और reconnect plumbing है।

---

## Links

- सर्वर और live leaderboard: <https://battleofcode.com>
- Issue tracker: bugs को upstream `battleofcode/bocbot` के विरुद्ध file करें

## लाइसेंस

MIT — [LICENSE](../LICENSE) देखें।
