# bocbot

[English](https://github.com/battleofcode/bocbot/blob/main/README.md) | [中文](https://github.com/battleofcode/bocbot/blob/main/docs/README_ZH.md) | [हिन्दी](https://github.com/battleofcode/bocbot/blob/main/docs/README_HI.md) | [Español](https://github.com/battleofcode/bocbot/blob/main/docs/README_ES.md) | [Français](https://github.com/battleofcode/bocbot/blob/main/docs/README_FR.md) | **[العربية](https://github.com/battleofcode/bocbot/blob/main/docs/README_AR.md)** | [Русский](https://github.com/battleofcode/bocbot/blob/main/docs/README_RU.md)

<div dir="rtl" lang="ar" markdown="1">

قالب لاعب لـ **Battle of Code** — لعبة متعددة اللاعبين للاستيلاء على الأراضي حيث يقوم كل لاعب بتشغيل البوت الخاص به (أو اللعب يدوياً من الطرفية).

**ما يقدمه لك هذا القالب**

- عميل طرفية يعمل بواجهة Rich (`client/`) يمكنك اللعب به باستخدام WSAD.
- بوت بداية (`bot.py`) يمكنك تعديله — هذا هو البوت كاملاً، ملف واحد.
- ثلاثة سكربتات صغيرة في `tools/` تُسجلك على خادم اللعبة.
- توثيق يشرح بوضوح كيف يبدو بروتوكول الشبكة والمصادقة.

لا شيء هنا يتصل بالخارج، ولا شيء مشوّش. التسجيل الكامل عبارة عن 30 سطراً من استدعاءات REST يمكنك تنفيذها يدوياً. نقدم أيضاً سكربتاً يقوم بذلك نيابة عنك، لكن في المرة الأولى — وكما يجب — قم بالخطوات واحدة تلو الأخرى لترى ما يحدث.

---

## ما هو التسجيل فعلياً

ثلاثة أشياء فقط، لا أكثر:

1. **زوج مفاتيح Ed25519** على القرص الخاص بك. المفتاح الخاص (`.key`) يبقى محلياً. المفتاح العام (`.pub`) بصيغة hex، 64 محرفاً، سطر واحد.
2. **فرع في fork الخاص بك على GitHub** باسم تسجيل الدخول الخاص بك. في هذا الفرع يوجد `keys/<login>.pub`. يقرأه الخادم مرة واحدة.
3. **تحدٍّ موقّع**. يعطيك الخادم nonce عشوائياً، فتوقعه بالمفتاح الخاص، فيتحقق الخادم منه باستخدام المفتاح العام الذي جلبه للتو من GitHub.

هذا هو نموذج الثقة بأكمله. لا كلمة مرور، لا JWT، لا cookie. كل جلسة لعب تكرر الخطوة 3 بإطار `hello` موقّع جديد.

---

## بداية سريعة — يدوياً، خطوة بخطوة

افعلها مرة واحدة يدوياً. بعد ذلك السكربت يقوم بنفس الاستدعاءات.

استبدل `<login>` باسم تسجيل GitHub الخاص بك في كل مكان أدناه.

### 1. Fork & clone

```bash
gh repo fork battleofcode/bocbot --clone --remote
cd bocbot
```

أو عبر واجهة الويب لـ GitHub، ثم `git clone git@github.com:<login>/bocbot.git`.

### 2. تثبيت اعتمادات Python

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

هذا يعطيك:
- `cryptography` — توليد مفاتيح Ed25519 + التوقيعات
- `websockets` — نقل اللعبة
- `rich` — عرض CLI تفاعلي
- `requests` — REST signup

### 3. إعداد `.env`

```bash
cp .env.example .env
$EDITOR .env
```

عيّن `USERNAME=<login>`. عدّل `BOC_AUTH_HOST` / `BOC_GAME_HOST` إذا لم يكن الخادم على `localhost`.

### 4. توليد زوج مفاتيح Ed25519 — يدوياً

يمكنك ذلك بسطر واحد من Python (بدون أداة إضافية):

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

ما حصلت عليه:

- `keys/<login>.key` — 32 بايتاً خام، وضع `0600`. **مُتجاهَل من Git.** لا ترفعه أبداً.
- `keys/<login>.pub` — مفتاح عام hex، سطر واحد + تعليق. آمن للرفع.

> نفس الشيء بصيغة سكربت: `python3 tools/keygen.py`. هذا حرفياً نفس السطر أعلاه مع غلاف CLI.

### 5. ادفع المفتاح العام إلى فرعك

```bash
git checkout -b <login>
git add keys/<login>.pub
git commit -m "register key"
git push -u origin <login>
```

`main` يبقى نظيفاً. فرعك `<login>` يحتفظ بتسجيلك. سيقرأه الخادم من:

```
https://raw.githubusercontent.com/<login>/bocbot/<login>/keys/<login>.pub
```

يمكنك تنفيذ `curl` لهذا الرابط بنفسك للتأكد من إمكانية الوصول.

### 6. التسجيل — يدوياً

اثنان من استدعاءات REST.

**الاستدعاء 1: طلب challenge.** الخادم يجلب `key.pub` من GitHub، ويخزن `(pubkey, nonce)` في Redis بـ TTL مدته 60 ثانية، ويُرجع الـ nonce.

```bash
curl -s -X POST "http://${BOC_AUTH_HOST:-127.0.0.1}:${BOC_AUTH_PORT:-8000}/api/auth/signup" \
     -H 'Content-Type: application/json' \
     -d "{\"username\":\"$USERNAME\"}"
```

الاستجابة:

```json
{"status":"challenge","nonce":"0f1e2d3c4b5a69788796a5b4c3d2e1f0","ttl":60}
```

**الاستدعاء 2: وقّع الـ nonce وتحقق.** الـ nonce بصيغة hex. فك ترميزه إلى بايتات، وقّعه، رمّز التوقيع بصيغة hex، أرسله عائداً.

```bash
NONCE=0f1e2d3c4b5a69788796a5b4c3d2e1f0   # من الاستجابة السابقة
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

الاستجابة:

```json
{"status":"ok","username":"<login>"}
```

الآن الخادم لديه `(username, pubkey)` مخزن في مخزن SQLite. لن يتصل بـ GitHub من أجلك مرة أخرى.

> نفس الشيء بصيغة سكربت: `python3 tools/signup.py`. يطبع بدقة أي استدعاء يقوم به في كل خطوة. انظر [`docs/AUTH.md`](AUTH.md) للمرجع الكامل.

### 7. تحقق من أنك تستطيع اللعب

اختبار دخان لـ WebSocket اللعبة:

```bash
python3 tools/login.py
```

هذا يفتح `ws://<host>:5555/`، يرسل إطار `hello` موقّع، ينتظر `auth_ok` + `welcome`، يرسل `ping` واحداً، يطبع `pong`، يغلق. إذا رأيت سطرين خضراوين من المخرجات فأنت داخل.

الآن العب بالفعل:

```bash
./play.sh                          # عميل طرفية Rich UI, WSAD
# أو
python3 bot.py                     # بوت البداية — سيخسر، هذا طبيعي
```

إذا أردت العودة إلى `main` للعمل على البوت:

```bash
git checkout main
```

هذا هو التدفق الكامل. لقد فعلتها يدوياً مرة واحدة. في المرة القادمة السكربت يفعلها.

---

## بداية سريعة — بالسكربت

إذا كنت تريد فقط اللعب وتفهم بالفعل ما يحدث:

```bash
gh repo fork battleofcode/bocbot --clone --remote
cd bocbot
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
cp .env.example .env && $EDITOR .env       # عيّن USERNAME=<login>
python3 tools/signup.py                    # keygen + REST signup، يطلب التأكيد قبل الـ push
./play.sh
```

`tools/signup.py`:

1. ينسخ `.env.example` → `.env` إن لم يكن موجوداً، يؤكد `USERNAME`.
2. يولّد زوج المفاتيح (idempotent — إذا كان `keys/<login>.key` موجوداً، يعيد استخدامه).
3. **يتوقف** ويطبع أوامر `git` الأربعة التي تحتاجها لدفع المفتاح العام. اضغط Enter بعد الدفع.
4. يستدعي `/api/auth/signup`، يوقّع الـ nonce، يستدعي `/api/auth/signup/verify`.

اقرأ الكود المصدري — 200 سطر.

---

## اللعب يدوياً

`./play.sh` يفتح واجهة طرفية Rich. العنوان واسم المستخدم يأتيان من `.env` الخاص بك (`BOC_GAME_HOST`، `BOC_GAME_PORT`، `USERNAME`)؛ أعلام CLI الخاصة بـ `client/client.py` تتجاوزها.

| المفتاح        | الإجراء |
|----------------|---------|
| `W`            | أعلى    |
| `A`            | يسار    |
| `S`            | أسفل    |
| `D`            | يمين    |
| `Esc` / `Ctrl+C` × 2 | خروج |

العميل يعيد الاتصال تلقائياً عند انقطاع WebSocket؛ يستأنف الخادم لاعبك المُعلَّق (نفس `id` والموقع والمنطقة) ما دام `PAUSE_TIMEOUT` لم ينقضِ.

شغّل كمشاهد بـ `-f N` لمتابعة اللاعب الحي المصنّف حالياً N (1..128):

```bash
python3 client/client.py -f 1
```

---

## ما يوجد في الصندوق

| المسار                 | ما هو                                                                      |
|------------------------|----------------------------------------------------------------------------|
| `bot.py`               | بوت البداية، Python — **عدّل `decide()`**                                  |
| `bot.go`               | بوت البداية، Go — stub، غير مُنفَّذ بعد                                    |
| `bot.js`               | بوت البداية، Node.js — stub، غير مُنفَّذ بعد                                |
| `client/`              | لاعب طرفية CLI (Rich UI, WSAD) — للعب البشر                                |
| `play.sh`              | إطلاق عميل CLI ضد `battleofcode.com`                                       |
| `tools/keygen.py`      | توليد زوج مفاتيح Ed25519 في `keys/<u>.key` + `keys/<u>.pub`                |
| `tools/signup.py`      | تسجيل end-to-end ضد REST API                                                |
| `tools/login.py`       | اختبار دخان WebSocket (hello → ping → pong)                                |
| `docs/AUTH.md`         | تفاصيل المصادقة (REST signup، قواعد التوقيع، رموز الأخطاء)                 |
| `docs/API.md`          | بروتوكول الشبكة (إطارات WebSocket، رسائل state، الأحداث)                   |
| `docs/RULES.md`        | قواعد اللعبة (المناطق، الـ trails، الاستيلاء، شروط الموت)                  |
| `docs/EXAMPLES.md`     | كتاب وصفات اتخاذ قرارات البوت                                              |
| `keys/<u>.pub`         | مفتاحك **العام** (مرفوع على فرع `<u>` لـ fork الخاص بك)                    |
| `keys/<u>.key`         | مفتاحك **الخاص** (مُتجاهَل من git، الوضع 0600)                              |

---

## كيف يعمل التسجيل (ملخص)

1. تُولّد زوج مفاتيح Ed25519 (`tools/keygen.py` أو سطر Python أعلاه).
2. يبقى المفتاح الخاص في `keys/<your-login>.key` (مُتجاهَل من git، الوضع `0600`).
3. يُرفع المفتاح العام كـ `keys/<your-login>.pub` على فرع باسم تسجيل دخولك في GitHub.
4. `tools/signup.py` (أو استدعائي `curl`) يخبر الخادم باسم المستخدم؛ يحمّل الخادم المفتاح العام من `keys/<login>.pub` في فرعك `<login>` ويُصدر nonce قصير العمر.
5. يوقّع السكربت الـ nonce بمفتاحك الخاص؛ يتحقق الخادم ويخزن `(username, pubkey)` في قاعدة بيانات SQLite الخاصة بالمصادقة. بعد ذلك لا يوجد أي تواصل مع GitHub.
6. كل اتصال WebSocket يحمل `hello` موقّعاً جديداً (`{username, ts, sig}`). يتحقق الخادم منه باستخدام المفتاح العام المخزن. لا tokens ولا cookies ولا sessions.

`main` يبقى نظيفاً: PRs لـ upstream لا تلمس `.pub` الخاص بك. فرعك هو تسجيلك.

مراجع عميقة:
- [`docs/AUTH.md`](AUTH.md) — تدفق المصادقة، رموز الأخطاء، ملاحظات الأمان
- [`docs/API.md`](API.md) — تنسيق الشبكة (REST + WebSocket)
- [`docs/RULES.md`](RULES.md) — ميكانيكا اللعبة

---

## حسّن بوتك

افتح `bot.py`. البوت بأكمله ملف واحد. الدالة الوحيدة التي تحتاج لمسها هي `decide(state)` في الأعلى.

- اقرأ [`docs/RULES.md`](RULES.md) لمعرفة ما يفوز.
- اقرأ [`docs/API.md`](API.md) لشكل `state` (إنه مجرد JSON dict).
- اقرأ [`docs/EXAMPLES.md`](EXAMPLES.md) لكتاب الوصفات (تجنب الجدران، الصيد، مقاييس المسافة).

`bot.go` و `bot.js` placeholders تطبع "not implemented yet" — إذا أردت اللعب بـ Go أو Node، انقل `bot.py`. البروتوكول ~80 سطراً من المنطق الفعلي؛ كل ما تبقى هو `decide()` ومرافيق إعادة الاتصال.

---

## روابط

- الخادم والـ leaderboard المباشر: <https://battleofcode.com>
- متعقب المشكلات: قدّم البلاغات ضد `battleofcode/bocbot` upstream

## الترخيص

MIT — انظر [LICENSE](../LICENSE).

</div>
