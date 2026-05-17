# bocbot

[English](https://github.com/battleofcode/bocbot/blob/main/README.md) | **[中文](https://github.com/battleofcode/bocbot/blob/main/docs/README_ZH.md)** | [हिन्दी](https://github.com/battleofcode/bocbot/blob/main/docs/README_HI.md) | [Español](https://github.com/battleofcode/bocbot/blob/main/docs/README_ES.md) | [Français](https://github.com/battleofcode/bocbot/blob/main/docs/README_FR.md) | [العربية](https://github.com/battleofcode/bocbot/blob/main/docs/README_AR.md) | [Русский](https://github.com/battleofcode/bocbot/blob/main/docs/README_RU.md)

**Battle of Code** 的玩家模板 —— 一款多人领地争夺游戏，每个人都可以运行自己的机器人(或在终端中手动游玩)。

**这个模板提供什么**

- 一个可用的 Rich UI 终端客户端 (`client/`)，可以用 WSAD 操控。
- 一个起步机器人 (`bot.py`)，你可以直接修改——整个机器人就这一个文件。
- 三个 `tools/` 小脚本，用于把你注册到游戏服务器。
- 文档明确说明 wire 协议和认证流程的真实样子。

这里没有任何东西会"回家通话"，也没有任何东西被混淆。完整的注册流程就是 30 行 REST 调用，你可以手动执行。我们也提供了一个脚本帮你完成这些，但第一次时——并且应该——一步一步走完整个流程，看清每一步发生了什么。

---

## 注册到底是什么

只有三件事：

1. 在你硬盘上的一对 **Ed25519 密钥**。私钥 (`.key`) 留在本地。公钥 (`.pub`) 是 hex 字符串，64 个字符，一行。
2. 你 GitHub fork 中以你 GitHub 用户名命名的一个**分支**。该分支上有 `keys/<login>.pub`。服务器读取一次。
3. 一个**签名挑战 (challenge)**。服务器给你一个随机 nonce，你用私钥签名，服务器用刚从 GitHub 拉取的公钥验证。

这就是全部的信任模型。没有密码、没有 JWT、没有 cookie。每个游戏会话都会用新签名的 `hello` 帧重复第 3 步。

---

## Quickstart —— 手动逐步

先手动操作一次。之后脚本会做同样的调用。

把下面所有的 `<login>` 替换成你的 GitHub 用户名。

### 1. Fork & clone

```bash
gh repo fork battleofcode/bocbot --clone --remote
cd bocbot
```

或通过 GitHub 网页 UI fork，然后 `git clone git@github.com:<login>/bocbot.git`。

### 2. 安装 Python 依赖

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

这会安装：
- `cryptography` —— Ed25519 密钥生成 + 签名
- `websockets` —— 游戏传输层
- `rich` —— 交互式 CLI 渲染
- `requests` —— REST 注册

### 3. 配置 `.env`

```bash
cp .env.example .env
$EDITOR .env
```

设置 `USERNAME=<login>`。如果服务器不在 `localhost`，调整 `BOC_AUTH_HOST` / `BOC_GAME_HOST`。

### 4. 生成 Ed25519 密钥对 —— 手动

可以用一行 Python 命令完成（无需额外工具）：

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

得到的文件：

- `keys/<login>.key` —— 32 个原始字节，权限 `0600`。**被 git 忽略。** 永远不要提交这个文件。
- `keys/<login>.pub` —— hex 公钥，一行 + 注释。可以安全提交。

> 脚本形式的同一操作：`python3 tools/keygen.py`。它就是上面那条一行命令的 CLI 包装。

### 5. 把公钥推送到你的分支

```bash
git checkout -b <login>
git add keys/<login>.pub
git commit -m "register key"
git push -u origin <login>
```

`main` 保持干净。你的 `<login>` 分支保存你的注册信息。服务器将从下面这个地址读取：

```
https://raw.githubusercontent.com/<login>/bocbot/<login>/keys/<login>.pub
```

可以自己 `curl` 这个 URL 来确认可访问。

### 6. 注册 —— 手动

两个 REST 调用。

**调用 1：请求挑战 (challenge)。** 服务器从 GitHub 拉取你的 `key.pub`，把 `(pubkey, nonce)` 存到 Redis (TTL 60 秒)，返回 nonce。

```bash
curl -s -X POST "http://${BOC_AUTH_HOST:-127.0.0.1}:${BOC_AUTH_PORT:-8000}/api/auth/signup" \
     -H 'Content-Type: application/json' \
     -d "{\"username\":\"$USERNAME\"}"
```

响应：

```json
{"status":"challenge","nonce":"0f1e2d3c4b5a69788796a5b4c3d2e1f0","ttl":60}
```

**调用 2：签名 nonce 并验证。** nonce 是 hex 字符串。把它解码成字节，签名，hex 编码签名，发回去。

```bash
NONCE=0f1e2d3c4b5a69788796a5b4c3d2e1f0   # 来自上一个响应
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

响应：

```json
{"status":"ok","username":"<login>"}
```

现在服务器已经在 SQLite 认证库里缓存了 `(username, pubkey)`。它不会再为你访问 GitHub。

> 脚本形式的同一操作：`python3 tools/signup.py`。它会打印每一步在做哪个调用。完整参考见 [`docs/AUTH.md`](AUTH.md)。

### 7. 验证你能玩

对游戏 WebSocket 做冒烟测试：

```bash
python3 tools/login.py
```

这会打开 `ws://<host>:5555/`，发送一个签名的 `hello` 帧，等待 `auth_ok` + `welcome`，发一个 `ping`，打印 `pong`，关闭连接。看到两行绿色输出就成了。

现在真正开始玩：

```bash
./play.sh                          # Rich UI 终端客户端，WSAD
# 或
python3 bot.py                     # 起步机器人 —— 它会输，这很正常
```

如果你想回到 `main` 去开发机器人：

```bash
git checkout main
```

整个流程就这些。你手动做了一次。下次脚本帮你做。

---

## Quickstart —— 脚本

如果你只是想玩，并且已经理解了正在发生的事：

```bash
gh repo fork battleofcode/bocbot --clone --remote
cd bocbot
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
cp .env.example .env && $EDITOR .env       # 设置 USERNAME=<login>
python3 tools/signup.py                    # keygen + REST 注册，准备 push 时会提示
./play.sh
```

`tools/signup.py`：

1. 如果 `.env` 缺失则从 `.env.example` 复制，确认 `USERNAME`。
2. 生成密钥对（幂等 —— 如果 `keys/<login>.key` 存在则复用）。
3. **暂停**并打印你需要执行的四条 `git` 命令以推送公钥。推送完按 Enter。
4. 调用 `/api/auth/signup`，签名 nonce，调用 `/api/auth/signup/verify`。

读源码 —— 200 行而已。

---

## 手动游玩

`./play.sh` 打开 Rich 终端 UI。地址和用户名来自你的 `.env` (`BOC_GAME_HOST`、`BOC_GAME_PORT`、`USERNAME`)；`client/client.py` 的 CLI 参数会覆盖它们。

| 按键           | 动作 |
|----------------|------|
| `W`            | 上    |
| `A`            | 左    |
| `S`            | 下    |
| `D`            | 右    |
| `Esc` / `Ctrl+C` × 2 | 退出 |

客户端在 WebSocket 断开时会自动重连；只要还没超过 `PAUSE_TIMEOUT`，服务器会恢复你处于 paused 状态的玩家（同样的 `id`、位置、领地）。

用 `-f N` 作为观战者运行，跟随当前排名第 N (1..128) 的活跃玩家：

```bash
python3 client/client.py -f 1
```

---

## 盒子里有什么

| 路径                   | 是什么                                                                     |
|------------------------|----------------------------------------------------------------------------|
| `bot.py`               | 起步机器人，Python —— **编辑 `decide()`**                                  |
| `bot.go`               | 起步机器人，Go —— 占位符，尚未实现                                          |
| `bot.js`               | 起步机器人，Node.js —— 占位符，尚未实现                                     |
| `client/`              | 终端 CLI 玩家 (Rich UI, WSAD) —— 用于人工游玩                              |
| `play.sh`              | 启动 CLI 客户端连接 `battleofcode.com`                                     |
| `tools/keygen.py`      | 生成 Ed25519 密钥对到 `keys/<u>.key` + `keys/<u>.pub`                      |
| `tools/signup.py`      | 通过 REST API 完成端到端注册                                                |
| `tools/login.py`       | WebSocket 冒烟测试 (hello → ping → pong)                                   |
| `docs/AUTH.md`         | 认证深入说明 (REST 注册、签名规则、错误码)                                 |
| `docs/API.md`          | wire 协议 (WebSocket 帧、state 消息、事件)                                 |
| `docs/RULES.md`        | 游戏规则 (领地、轨迹、占领、死亡条件)                                       |
| `docs/EXAMPLES.md`     | 机器人决策菜谱                                                              |
| `keys/<u>.pub`         | 你的**公钥** (提交在你 fork 的 `<u>` 分支上)                                |
| `keys/<u>.key`         | 你的**私钥** (被 git 忽略，权限 0600)                                       |

---

## 注册是怎么工作的（总结）

1. 你生成 Ed25519 密钥对 (`tools/keygen.py` 或上面的 Python 一行命令)。
2. 私钥留在 `keys/<your-login>.key` (被 git 忽略，权限 `0600`)。
3. 公钥作为 `keys/<your-login>.pub` 提交到以你 GitHub 用户名命名的分支。
4. `tools/signup.py` (或两个 `curl` 调用) 告诉服务器你的 username；服务器从你 `<login>` 分支的 `keys/<login>.pub` 下载公钥，发回一个短期 nonce。
5. 脚本用你的私钥签名 nonce；服务器验证并把 `(username, pubkey)` 存到 SQLite 认证库。之后不再与 GitHub 交互。
6. 每次 WebSocket 连接都携带新签名的 `hello` (`{username, ts, sig}`)。服务器用存储的公钥验证。没有 token、cookie、会话。

`main` 保持干净：上游 PR 不会触碰你的 `.pub`。你的分支就是你的注册。

深入参考：
- [`docs/AUTH.md`](AUTH.md) —— 认证流程、错误码、安全说明
- [`docs/API.md`](API.md) —— wire 格式 (REST + WebSocket)
- [`docs/RULES.md`](RULES.md) —— 游戏机制

---

## 改进你的机器人

打开 `bot.py`。整个机器人就是一个文件。你只需要碰顶部的 `decide(state)` 这一个函数。

- 读 [`docs/RULES.md`](RULES.md) 看什么算赢。
- 读 [`docs/API.md`](API.md) 看 `state` 的形状 (就是个 JSON 字典)。
- 读 [`docs/EXAMPLES.md`](EXAMPLES.md) 看食谱 (避墙、捕猎、距离度量)。

`bot.go` 和 `bot.js` 是打印 "not implemented yet" 的占位符 —— 如果想用 Go 或 Node 玩，把 `bot.py` 移植过去。协议大约 80 行实际逻辑；其余都是 `decide()` 和重连管道。

---

## 链接

- 服务器和实时排行榜：<https://battleofcode.com>
- Issue tracker：在上游 `battleofcode/bocbot` 提交 bug

## 许可证

MIT —— 见 [LICENSE](../LICENSE)。
