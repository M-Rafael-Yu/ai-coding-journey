# multi_turn_chat.py 说明文档（小白友好版）

> 这份文档面向「会一点 Python、但还不熟悉面向对象和 API 调用」的同学。
> 目标：让你看完后能 **跑起来**、**看懂结构**、**讲清逻辑**。

---

## 一、这个文件是干什么的？

一句话：**它做了一个可以“连续聊天”的机器人，而且能像人一样“记住”之前说过的话。**

举几个它解决的问题，你就懂它的价值了：

| 你想要的                      | 普通一次调用          | 本模块            |
| ------------------------- | --------------- | -------------- |
| 问完第一个问题，再追问“举個例子”         | 模型不记得上一个问题，答非所问 | ✅ 自动带上上文，能追问   |
| 想看到字一个一个蹦出来（像 ChatGPT 那样） | 要等全部生成完才一次性返回   | ✅ 流式输出，逐字显示    |
| 关掉程序明天还想接着昨天的聊            | 昨天说的全没了         | ✅ 存成文件，下次自动恢复  |
| 网断了 / Key 错了              | 程序直接崩，报一堆英文     | ✅ 中文报错，且不会弄脏历史 |

它底层调用的是**通义千问（Qwen）**，用的是 OpenAI 官方库的兼容接口。

---

## 二、跑起来之前的准备

1. **装依赖**（在项目终端里）：
   ```bash
   pip install openai python-dotenv
   ```

2. **配置密钥**：在项目根目录的 `.env` 文件里写一行：
   ```
   QWEN_API_KEY=你的通义千问密钥
   ```
   （密钥去阿里云 dashscope 控制台申请。`.env` 里的内容会被 `load_dotenv()` 自动读进环境变量。）

3. **运行**：
   ```bash
   python multi_turn_chat.py
   ```
   然后在 `🧑 你：` 后面打字、回车，就能聊了。输入 `exit` 退出，退出时自动存档。

---

## 三、常用启动参数

在终端里 `python multi_turn_chat.py` 后面可以加这些参数（`python multi_turn_chat.py -h` 可查看全部）：

| 参数 | 作用 | 例子 |
|---|---|---|
| `--system "..."` | 设定机器人的“人设” | `--system "你是翻译官"` |
| `--model 名字` | 换模型 | `--model qwen-turbo` |
| `--temperature 数字` | 回答的随机程度（0~2，越大越放飞）；填负数=用模型默认 | `--temperature 0.7` |
| `--save 文件名` | 退出时存到这个文件；**该文件存在时，启动会自动续聊** | `--save my.json` |
| `--load 文件名` | 启动时读取指定文件来续聊 | `--load my.json` |
| `--fresh` | 强制从头开始，不自动读存档 | `--fresh` |
| `--no-save` | 退出时不存档 | `--no-save` |

> 💡 **最容易踩的坑**：直接运行（不加 `--load`）时，如果存档文件已存在，程序会**自动续聊**，不用你手动加参数。想彻底重来用 `--fresh`。

---

## 四、在代码里怎么用（不只是当脚本跑）

```python
from multi_turn_chat import MultiTurnChat

# 1. 创建一个机器人，设定人设和温度
bot = MultiTurnChat(system_prompt="你是一位严谨的老师", temperature=0)

# 2. 流式聊天：一段一段拿到回复
for piece in bot.chat("什么是质数？"):
    print(piece, end="", flush=True)

# 3. 非流式：直接拿到完整字符串
reply = bot.chat_once("再举个例子")

# 4. 存档 / 恢复
bot.save("chat.json")
bot.load_history("chat.json")   # 恢复后继续 chat() 就是续聊

# 5. 清空历史重来
bot.reset()

# 6. 查看完整历史
print(bot.messages)
```

---

## 五、代码结构总览

整个文件由四部分组成，从上到下：

```
multi_turn_chat.py
│
├─ 1. 文件开头的“简介”注释（docstring）        ← 文档与用法
├─ 2. import 区 + 全局常量 + _build_client()    ← 准备工作
├─ 3. class MultiTurnChat                        ← 核心！全部功能在这
│      ├─ __init__            初始化（建历史、建客户端）
│      ├─ _validate_temperature  温度校验（内部小工具）
│      ├─ chat                流式对话（最核心）
│      ├─ chat_once           非流式对话（套了层 chat）
│      ├─ save                存档到 JSON
│      ├─ load_history        从 JSON 恢复
│      ├─ reset               清空历史
│      └─ messages            只读查看历史
└─ 4. _parse_args() + if __name__ == "__main__"  ← 命令行入口/交互循环
```

**一句话记忆**：第 3 部分是“能干什么”，第 4 部分是“当脚本跑时怎么和人交互”。

---

## 六、先搞懂 4 个核心概念（看懂这节，代码就懂一半）

### 1. 消息列表 = 对话历史

大模型聊天，本质是给它一串“消息”让它接着说。每条消息长这样：
```python
{"role": "user",      "content": "什么是质数？"}
{"role": "assistant", "content": "质数是只能被1和自身整除的数…"}
```
`role` 有三种：
- `system`：**人设**，告诉模型“你是谁”，放在最开头，只出现一次。
- `user`：**你说的话**。
- `assistant`：**模型回的话**。

把这一串消息整个发给模型，它就能“记得”上文。**多轮对话的秘密就是：把所有历史消息每次都一起发过去。** 本模块用一个列表 `self.history` 存住它们。

### 2. 流式输出（stream）

普通调用：模型把整段话说完，一次性返回，你得干等。
流式调用：模型一边想一边吐，每次吐一小片（叫 `delta`），程序拿到一小片就显示一小片，于是你看到字一个个蹦出来。

代码里 `stream=True` 就是开流式；`for chunk in stream` 就是逐片接收。

### 3. 生成器（`yield`）

`chat()` 方法里有 `yield delta.content`。带 `yield` 的函数叫**生成器**：它不会一次跑完返回结果，而是“暂停”在 `yield` 处交出一个值，等你下次要时再继续。

好处：模型吐一片，`yield` 一片，调用方 `for piece in bot.chat(...)` 就能实时拿到，不用等整段生成完。这就是流式能“边收边显示”的原理。

### 4. 持久化（存档/恢复）

`self.history` 是个列表，**程序一关就没了**。要跨天续聊，就得把它写到文件里。
- 存：`json.dump(self.history, 文件)` → 把列表变成 JSON 文本写盘。
- 读：`json.load(文件)` → 把 JSON 文本变回列表。
JSON 就是一种“把 Python 数据变成纯文本”的通用格式，人也能看懂。

---

## 七、逐块代码讲解

### ① 准备工作（第 52~78 行）

```python
load_dotenv()                     # 读取 .env，把 QWEN_API_KEY 放进环境变量
TEMPERATURE_MIN, TEMPERATURE_MAX = 0.0, 1.99   # 温度合法范围

def _build_client():
    return OpenAI(
        api_key=os.getenv("QWEN_API_KEY"),
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
```
- `OpenAI(...)` 是建一个“客户端”，相当于“和通义千问服务器连线的电话”。
- `base_url` 指向阿里云的兼容地址——**用 OpenAI 的库，打阿里的电话**，这就是“兼容模式”。
- 前面加下划线 `_build_client`：约定俗成表示“内部用的，别在外部直接调”。

### ② `__init__` 初始化（第 89~117 行）

```python
def __init__(self, system_prompt=..., model="qwen-plus", temperature=None, client=None):
    ...
    self.model = model
    self.temperature = self._validate_temperature(temperature)
    self.client = client if client is not None else _build_client()
    self.history = [{"role": "system", "content": system_prompt}]
```
做了三件事：
1. 存下模型名、温度、客户端。
2. **温度先校验**（见 ③）。
3. **历史列表的第一条固定放 system 人设**——之后 user/assistant 消息会往后面追加。

`client` 参数允许你传一个“假的客户端”进来，方便测试时**不真打网络**。

### ③ `_validate_temperature` 温度校验（第 119~131 行）

```python
if temperature < 0.0 or temperature >= 1.99:
    clamped = max(0.0, min(temperature, 1.99))   # 夹紧到合法范围
    warnings.warn(...)                            # 告警但不报错
    return clamped
```
逻辑：温度超范围时不让程序崩，而是**自动夹回合法区间并提醒你**。`max/min` 组合是常见的“把值限制在 [a,b]”写法。

### ④ `chat` 流式对话 —— 最核心（第 133~219 行）

整个流程分三步，对照行号看：

**第 1 步：把用户的话存进历史（第 153 行）**
```python
self.history.append({"role": "user", "content": prompt})
```
先存进去，这样发给模型时它就带着这句。

**第 2 步：发请求（第 163~191 行）**
```python
params = {"model": self.model, "messages": self.history, "stream": True}
stream = self.client.chat.completions.create(**params)
```
`**params` 是把字典“展开”成参数。注意 `messages=self.history`——**把全部历史一起发**，这就是多轮上下文。

这一步套了 6 个 `except`，把各种网络/API 错误**统一翻译成中文 RuntimeError**。关键细节：每个 except 里都有 `self.history.pop()`——**如果请求失败，把刚才加进去的那句 user 消息撤掉**，保证历史里不留“问出去了但没答”的脏数据。这叫**回滚**。

**第 3 步：边收边吐，最后存进历史（第 194~219 行）**
```python
full_reply = []
for chunk in stream:
    delta = chunk.choices[0].delta
    if delta and delta.content:
        full_reply.append(delta.content)   # 攒起来
        yield delta.content                # 同时吐给调用方
self.history.append({"role": "assistant", "content": "".join(full_reply)})
```
- 每收到一小片，**既 `yield` 出去（让你能实时显示），又攒进 `full_reply`**。
- 全部收完后，把拼好的完整回复作为 `assistant` 消息存进历史。这样下一轮就带着这轮的答。
- 如果流式**中途断开**（第 203~215 行）：已收到的部分仍然存进历史，方便下次续接，而不是丢掉。

### ⑤ `chat_once` 非流式（第 221~237 行）

```python
def chat_once(self, prompt):
    return "".join(self.chat(prompt))
```
就一行！它**复用 `chat`**，把流式吐出的小片用 `"".join(...)` 拼成完整字符串返回。好处：历史维护、错误处理等逻辑不用重写一遍，和流式版完全一致。这是“代码复用”的好例子。

### ⑥ `save` / `load_history` 存档与恢复（第 239~284 行）

`save`：
```python
os.makedirs(directory, exist_ok=True)   # 父目录不存在就建
with open(file_path, "w", encoding="utf-8") as f:
    json.dump(self.history, f, ensure_ascii=False, indent=2)
```
- `ensure_ascii=False`：让中文直接存中文，不转成 `\uXXXX`。
- `indent=2`：存成带缩进的好看格式，人也能读。

`load_history`：读回来后**做了格式校验**——必须是列表、第一条必须是 system、每条要有 role 和 content。防止读到坏文件把程序搞崩。校验通过才 `self.history = [dict(m) for m in data]` 覆盖历史。

### ⑦ `reset` 和 `messages`（第 286~307 行）

- `reset(system_prompt=None)`：把历史清空，只留一条 system。不传参数就用原来的 system 文本。
- `messages`：是 `@property`，访问像属性（`bot.messages` 而不是 `bot.messages()`）。返回历史的**副本**（`dict(m)`），这样外部改了也不会影响内部真实历史——保护数据。

### ⑧ 命令行入口 + 交互循环（第 310~429 行）

`_parse_args()`：用 `argparse` 库把命令行参数（`--system` 等）解析成 Python 对象。

`if __name__ == "__main__":` 这段的意思是：**“只有直接运行本文件时才执行下面这段；被 import 时不执行。”** 这是 Python 的标准写法，保证这个文件既能当脚本跑，又能当模块被别人引用。

交互循环的核心：
```python
load_source = None
if args.load:                       # ① 显式指定文件 → 读它
    load_source = args.load
elif not args.fresh and os.path.exists(args.save):  # ② 没指定但存档在 → 自动续聊
    load_source = args.save

# ... 聊天循环 ...
while True:
    user_input = input("\n🧑 你：")
    if user_input 退出命令: break
    for piece in bot.chat(user_input):
        print(piece, end="", flush=True)
```
- 自动续聊逻辑（第 376~389 行）就是那个“忘了加 `--load` 也不会丢历史”的保护。
- `try / except / finally`（第 396~429 行）：无论正常退出、`Ctrl+C` 中断、还是出错，`finally` 都会执行存档，**保证聊过的内容不丢**。

---

## 八、程序运行全流程图

```
启动
 │
 ├─ 解析命令行参数 (--system/--load/--fresh ...)
 ├─ 创建 bot，初始化历史[system]
 ├─ 决定历史来源：
 │    有 --load  → 读指定文件
 │    有 --fresh → 全新
 │    否则存档存在 → 自动续聊
 │
 ├─ 进入聊天循环 ─────────────────────────┐
 │    🧑 你：输入                          │
 │      ├─ 空行 → 跳过                     │
 │      ├─ exit/quit/退出 → 跳出循环        │
 │      └─ 正常问题:                        │
 │           bot.chat(输入)                │
 │            ├─ user 消息进历史            │
 │            ├─ 带【全部历史】发请求(stream)│
 │            ├─ 逐片 yield → 实时打印      │
 │            └─ 完整回复进历史             │
 └──────────────────────────────────────┘
 │
 └─ finally: 保存历史到文件 → 退出
```

---

## 九、几个值得学习的设计点（算法/逻辑层面）

1. **多轮上下文 = 每次重发全部历史**。不是靠模型“记得”，而是程序每次把历史整包发过去。简单可靠。

2. **失败回滚**。请求失败就 `pop` 掉刚加的 user 消息，保证历史永远是“成对的问答”，不会出现“有问无答”导致下一轮上下文错乱。

3. **流中断兜底**。流式中途断了，已收到的部分也存进历史，下次能从断点续，而不是整轮作废。

4. **非流式复用流式**。`chat_once` 不另写一套，直接拼 `chat` 的输出，避免重复代码导致两套行为不一致。

5. **自动续聊**。检测到存档就自动读，化解“忘加 `--load` → 退出覆盖 → 历史丢失”这个最常见的坑。

6. **防御性校验**。温度超范围自动夹紧、加载历史时校验格式、`messages` 返回副本——处处防止“坏输入/外部修改”破坏内部状态。

7. **统一错误封装**。把 6 种英文异常翻译成中文 `RuntimeError`，调用方只需 `except RuntimeError`，不用懂 OpenAI 的异常体系。

---

## 十、常见问题（FAQ）

**Q1：运行报错“API Key 无效”？**
A：检查 `.env` 里 `QWEN_API_KEY` 是否正确，且 `.env` 在项目根目录。

**Q2：我改了机器人的名字，重启后它不记得了？**
A：要么用 `--load` 续聊，要么直接运行（存档存在会自动续聊）。直接运行还“不记得”，多半是你上一次没正常 `exit`、或上次用了 `--no-save`、或被一次全新会话覆盖了。

**Q3：终端里中文/emoji 变成乱码？**
A：是终端编码问题，不影响逻辑。设环境变量 `PYTHONIOENCODING=utf-8`；PyCharm 里在运行配置勾选 “Emulate terminal in output console”。

**Q4：想从头重新开始怎么办？**
A：加 `--fresh`，或删掉 `multi_turn_chat.json` 文件。

**Q5：`chat` 和 `chat_once` 该用哪个？**
A：要“打字机效果”用 `chat`（配合 `for` 循环打印）；只要最终结果用 `chat_once`。

---

## 十一、动手改造练习（从易到难）

> 看懂≠会写。下面 5 个练习带你在原代码上动手，每个都给「目标 / 提示 / 参考答案」。
> 建议自己先试，卡住了再看答案。所有改动都只动 `multi_turn_chat.py`。

### 练习 1（⭐ 入门）：加一个“本轮字数统计”

**目标**：每轮回复结束后，打印模型这轮回了多少个字。

**提示**：`chat()` 里已经有 `full_reply` 这个列表在攒回复，流结束后能拿到完整文本。

**参考答案**（在 `chat()` 末尾、写入历史之后加）：
```python
self.history.append({"role": "assistant", "content": "".join(full_reply)})
print(f"\n   （本轮回复 {len(''.join(full_reply))} 字）")  # 新增
```
*学到的*：`len(字符串)` 数字符数；列表拼接用 `"".join(...)`。

---

### 练习 2（⭐⭐ 基础）：加一个“清空历史”的聊天指令

**目标**：聊天过程中输入 `clear` 就清空历史重新开始（不用退出程序）。

**提示**：在交互循环里，和 `exit` 的判断并列，加一个 `clear` 分支，调用现成的方法。

**参考答案**（在 `__main__` 循环里，`EXIT_COMMANDS` 判断旁加）：
```python
RESET_COMMANDS = {"clear", "重置"}

# while 循环内：
if user_input.strip().lower() in RESET_COMMANDS:
    bot.reset()
    print("🧹 历史已清空，重新开始。")
    continue
```
*学到的*：`continue` 跳过本轮循环剩余部分；复用已有方法比新写逻辑好。

---

### 练习 3（⭐⭐⭐ 实用）：统计每轮 Token 用量

**目标**：每轮结束后显示本次消耗的 token 数（输入+输出）。

**提示**：
- 流式响应里，**最后一个 chunk** 通常带 `usage` 字段（需在请求时加 `stream_options={"include_usage": True}`）。
- 不是所有兼容接口都返回 usage，所以要判空。

**参考答案**：
```python
# chat() 第 155 行 params 里加：
params = {
    "model": self.model,
    "messages": self.history,
    "stream": True,
    "stream_options": {"include_usage": True},   # 新增
}

# 流式循环里记录 usage：
usage = None
for chunk in stream:
    if chunk.usage:                  # 带 usage 的通常是最后一个 chunk
        usage = chunk.usage
    if not chunk.choices:
        continue
    ...

# 流结束后打印：
if usage:
    print(f"\n   （tokens: 输入 {usage.prompt_tokens} + 输出 {usage.completion_tokens} = {usage.total_tokens}）")
```
*学到的*：流式拿 usage 的姿势；`if 对象:` 判空；兼容不同接口要防御性判断。

---

### 练习 4（⭐⭐⭐ 进阶）：多角色人设一键切换

**目标**：支持多个预设人设，启动时用 `--role teacher` / `--role translator` 选择，不用手敲长 system。

**提示**：
- 在文件里定义一个字典 `ROLES = {"teacher": "...", "translator": "..."}`。
- `_parse_args()` 里把 `--system` 换成 `--role`，默认 `teacher`。
- `__main__` 里用 `ROLES[args.role]` 传给 `MultiTurnChat`。

**参考答案**：
```python
ROLES = {
    "teacher": "你是一位严谨的数学辅导老师，回答简练。",
    "translator": "你是专业中英翻译官，用户给中文译英文，给英文译中文。",
    "coder": "你是一位资深 Python 工程师，回答附带可运行代码。",
}

# _parse_args() 里：
parser.add_argument("--role", choices=list(ROLES), default="teacher",
                    help="预设人设角色。")
# 删掉原来的 --system（或保留作覆盖用）

# __main__ 里：
bot = MultiTurnChat(system_prompt=ROLES[args.role], ...)
```
*学到的*：用字典管理配置；`argparse` 的 `choices` 限定可选值；参数默认值联动。

---

### 练习 5（⭐⭐⭐⭐ 综合）：历史超长自动裁剪

**目标**：对话轮数多了之后，历史会越来越长、token 越花越多。加一个上限：超过 N 轮就**保留 system + 最近 N 轮问答**，把更早的丢掉。

**提示**：
- “1 轮”= 1 条 user + 1 条 assistant = 2 条消息；system 单独算。
- 在 `chat()` 里，发请求前检查长度，超了就从前面（system 之后）裁掉。
- ⚠️ 裁剪是“有损”的，模型会忘记很早的内容——这是性能和记忆的权衡。

**参考答案**（在 `__init__` 加参数，在 `chat()` 发请求前裁剪）：
```python
def __init__(self, ..., max_rounds: int | None = None):
    ...
    self.max_rounds = max_rounds   # None 表示不限制

# chat() 里，self.history.append(user) 之后、create 之前：
if self.max_rounds is not None:
    system_msg = self.history[0]                       # system 永远保留
    rest = self.history[1:]                            # 其余是问答对
    keep_pairs = self.max_rounds                       # 保留最近 N 轮
    rest = rest[-keep_pairs * 2:]                      # 每轮 2 条
    self.history = [system_msg] + rest
```
运行：`MultiTurnChat(system_prompt="...", max_rounds=5)` 就只记最近 5 轮。

*学到的*：列表切片 `[-n:]` 取末尾 n 个；用 `None` 表示“无限制”是常见设计；权衡（trade-off）思维——记忆 vs 成本。

---

### 🎯 练习通关检验

做完后，你的模块应该能：
- [ ] 每轮显示回复字数（练习1）
- [ ] 聊天中 `clear` 重置（练习2）
- [ ] 每轮显示 token 消耗（练习3）
- [ ] `--role` 一键换人设（练习4）
- [ ] 历史超长自动裁剪不报错（练习5）

每做完一个，**用第 七、八 节的知识回读自己改的代码**，确认你讲得清“为什么这么写”——这才是真懂了。

---

## 附：关键行号速查

| 想看什么 | 行号 |
|---|---|
| 模块简介/用法 | 1~50 |
| 构造客户端 | 73~78 |
| 类初始化 | 89~117 |
| 温度校验 | 119~131 |
| **流式对话核心** | 133~219 |
| 非流式便捷方法 | 221~237 |
| 存档 / 恢复 | 239~284 |
| 重置 / 查看历史 | 286~307 |
| 命令行参数 | 310~353 |
| 交互主循环 | 356~429 |
