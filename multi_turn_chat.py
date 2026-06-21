"""多轮对话工具：支持流式输出、保留完整对话历史、可持久化。

软件功能
========
1. 多轮对话：每次提问都会自动携带此前全部上下文，实现连续追问。
2. 流式输出：``chat()`` 以生成器逐块产出增量文本，可实时打印。
3. 非流式便捷调用：``chat_once()`` 直接返回完整回复字符串。
4. 完整历史保留：用户与助手的每轮消息都保存在 ``history`` 中。
5. 历史持久化：``save()`` / ``load_history()`` 以 JSON 存档与恢复对话，
   便于跨会话续聊。
6. 健壮的错误处理：请求失败时回滚本轮消息、流中断时保留已生成内容，
   并将各类 API 异常统一封装为 ``RuntimeError``。

操作方法
========
- 直接运行本文件即可进入交互式聊天：

    python multi_turn_chat.py

  在提示符后输入问题回车发送，连续输入即为多轮追问；输入 ``exit``、
  ``quit`` 或 ``退出`` 结束对话，结束时自动把历史保存到
  ``multi_turn_chat.json``。

- 常用启动参数（``python multi_turn_chat.py -h`` 查看全部）：

    --system "你是翻译官"        自定义系统角色
    --model qwen-turbo           指定模型
    --temperature 0.7            采样温度（设为负数则用模型默认值）
    --load chat.json             启动时加载历史，续聊上次对话
    --save my.json               退出时保存到指定文件（该文件存在时启动会自动续聊）
    --fresh                      强制全新对话，不自动读取存档
    --no-save                    退出时不保存历史

- 代码内使用：

    from multi_turn_chat import MultiTurnChat

    bot = MultiTurnChat(system_prompt="你是一位严谨的老师", temperature=0)
    for piece in bot.chat("什么是质数？"):        # 流式
        print(piece, end="", flush=True)
    print(bot.chat_once("再举个例子"))            # 非流式
    bot.save("chat.json")                         # 存档
    bot.load_history("chat.json")                 # 恢复后继续追问
    bot.reset()                                   # 清空历史重新开始

环境依赖
========
- 在项目根目录 ``.env`` 中配置 ``QWEN_API_KEY``（通义千问 dashscope 兼容模式）。
- 依赖 ``openai`` 与 ``python-dotenv``。
"""

import json
import os
import warnings
from collections.abc import Iterator

from dotenv import load_dotenv
from openai import (
    OpenAI,
    APIError,
    APIConnectionError,
    AuthenticationError,
    RateLimitError,
    APITimeoutError,
)

load_dotenv()

# temperature 合法范围 (0, 2)，闭区间下界 0，开区间上界 2
TEMPERATURE_MIN, TEMPERATURE_MAX = 0.0, 1.99


def _build_client() -> OpenAI:
    """根据环境变量构造一个通义千问（dashscope 兼容模式）OpenAI 客户端。"""
    return OpenAI(
        api_key=os.getenv("QWEN_API_KEY"),
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )


class MultiTurnChat:
    """支持流式输出并保留完整对话历史的多轮对话类。

    每次调用 :meth:`chat` 时，用户输入会先追加到内部历史，再连同历史一起
    发送给模型；流式返回的完整回复也会被拼好并追加到历史，保证下一轮
    对话能携带完整上下文。
    """

    def __init__(
        self,
        system_prompt: str = "You are a helpful assistant.",
        model: str = "qwen-plus",
        temperature: float | None = None,
        client: OpenAI | None = None,
    ) -> None:
        """初始化多轮对话。

        Args:
            system_prompt: 系统角色设定，作为历史首条消息。
            model: 模型名称。
            temperature: 采样温度（0-2），越高越随机；传 None 使用模型默认值。
            client: 可选的已构造 OpenAI 客户端，便于复用或注入测试替身；
                为 None 时自动用环境变量构造。

        Raises:
            ValueError: system_prompt 为空时抛出。
        """
        if not system_prompt or not system_prompt.strip():
            raise ValueError("system_prompt 不能为空。")

        self.model = model
        self.temperature = self._validate_temperature(temperature)
        self.client = client if client is not None else _build_client()
        # 历史首条固定为 system 消息，后续交替追加 user / assistant 消息
        self.history: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt}
        ]

    @staticmethod
    def _validate_temperature(temperature: float | None) -> float | None:
        """校验并归一化 temperature，超出范围时自动夹紧并告警。"""
        if temperature is None:
            return None
        if temperature < TEMPERATURE_MIN or temperature >= TEMPERATURE_MAX:
            clamped = max(TEMPERATURE_MIN, min(temperature, TEMPERATURE_MAX))
            warnings.warn(
                f"temperature={temperature} 超出有效范围 [{TEMPERATURE_MIN}, {TEMPERATURE_MAX})，"
                f"已自动调整为 {clamped}"
            )
            return clamped
        return temperature

    def chat(self, prompt: str) -> Iterator[str]:
        """流式多轮对话，逐块（delta）产出回复文本。

        内部会先把用户输入追加到历史，再发起流式请求；流结束后把拼好的
        完整回复追加到历史。本方法是生成器，调用方可用 ``for chunk in
        chat.chat(prompt)`` 实时拿到增量文本。

        Args:
            prompt: 本轮用户输入。

        Yields:
            模型流式返回的增量文本片段。

        Raises:
            ValueError: prompt 为空时抛出。
            RuntimeError: 封装后的 API 调用错误。
        """
        if not prompt or not prompt.strip():
            raise ValueError("prompt 不能为空，请输入有效的提示词。")

        self.history.append({"role": "user", "content": prompt})

        params = {
            "model": self.model,
            "messages": self.history,
            "stream": True,
        }
        if self.temperature is not None:
            params["temperature"] = self.temperature

        try:
            stream = self.client.chat.completions.create(**params)
        except AuthenticationError:
            self.history.pop()  # 回滚本轮未成功的 user 消息
            raise RuntimeError(
                "API Key 无效或已过期，请检查环境变量 QWEN_API_KEY 是否正确。"
            )
        except APIConnectionError:
            self.history.pop()
            raise RuntimeError(
                "网络连接失败，请检查网络是否畅通或 API 地址是否正确。"
            )
        except RateLimitError:
            self.history.pop()
            raise RuntimeError("API 调用频率过高，请稍后重试。")
        except APITimeoutError:
            self.history.pop()
            raise RuntimeError("API 请求超时，请检查网络状况后重试。")
        except APIError as e:
            self.history.pop()
            raise RuntimeError(
                f"API 返回错误（状态码 {e.status_code}）：{e.message}"
            )
        except OSError as e:
            self.history.pop()
            raise RuntimeError(f"网络错误，请检查网络连接：{e}")
        except Exception as e:
            self.history.pop()
            raise RuntimeError(f"调用 LLM 时发生未知错误：{e}")

        # 流式过程中逐块产出，同时累积完整回复；流结束后写入历史
        full_reply = []
        try:
            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    full_reply.append(delta.content)
                    yield delta.content
        except APIError as e:
            # 流式途中断开：保留已生成的部分作为 assistant 消息，便于续接
            self.history.append(
                {"role": "assistant", "content": "".join(full_reply)}
            )
            raise RuntimeError(
                f"流式响应中途出错（状态码 {e.status_code}）：{e.message}"
            )
        except Exception as e:
            self.history.append(
                {"role": "assistant", "content": "".join(full_reply)}
            )
            raise RuntimeError(f"流式响应中途发生未知错误：{e}")

        self.history.append(
            {"role": "assistant", "content": "".join(full_reply)}
        )

    def chat_once(self, prompt: str) -> str:
        """非流式多轮对话，返回完整的回复文本。

        内部复用 :meth:`chat` 的流式逻辑并把增量拼成完整字符串，因此历史
        维护、错误回滚等行为与流式版本完全一致，仅是不再逐块 yield。

        Args:
            prompt: 本轮用户输入。

        Returns:
            模型的完整回复文本。

        Raises:
            ValueError: prompt 为空时抛出。
            RuntimeError: 封装后的 API 调用错误。
        """
        return "".join(self.chat(prompt))

    def save(self, path: str | os.PathLike[str]) -> None:
        """将当前完整对话历史以 JSON 形式持久化到文件。

        Args:
            path: 目标文件路径；父目录不存在时会自动创建。

        Raises:
            OSError: 文件写入失败时抛出。
        """
        file_path = os.fspath(path)
        directory = os.path.dirname(os.path.abspath(file_path))
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(self.history, f, ensure_ascii=False, indent=2)

    def load_history(self, path: str | os.PathLike[str]) -> None:
        """从 JSON 文件加载对话历史，覆盖当前历史。

        文件应为 :meth:`save` 写出的格式（一个消息字典列表），且首条必须是
        role 为 ``system`` 的消息；加载后 ``system_prompt`` 也会随之更新。

        Args:
            path: 历史文件路径。

        Raises:
            FileNotFoundError: 文件不存在时抛出。
            ValueError: 文件内容格式不合法时抛出。
            OSError: 文件读取失败时抛出。
        """
        file_path = os.fspath(path)
        with open(file_path, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError as e:
                raise ValueError(f"历史文件不是合法的 JSON：{e}") from e

        if not isinstance(data, list) or not data:
            raise ValueError("历史文件内容必须是非空的消息列表。")
        if not isinstance(data[0], dict) or data[0].get("role") != "system":
            raise ValueError("历史首条消息必须是 role 为 'system' 的消息。")
        for msg in data:
            if not isinstance(msg, dict) or "role" not in msg or "content" not in msg:
                raise ValueError("历史中存在格式不合法的消息项。")

        self.history = [dict(m) for m in data]

    def reset(self, system_prompt: str | None = None) -> None:
        """清空对话历史并重置。

        Args:
            system_prompt: 可选的新系统角色设定；为 None 时沿用原有 system 消息。

        Raises:
            ValueError: 传入的 system_prompt 为空时抛出。
        """
        if system_prompt is not None and (
            not system_prompt or not system_prompt.strip()
        ):
            raise ValueError("system_prompt 不能为空。")

        if system_prompt is None:
            system_prompt = self.history[0]["content"]
        self.history = [{"role": "system", "content": system_prompt}]

    @property
    def messages(self) -> list[dict[str, str]]:
        """返回当前完整对话历史的只读副本。"""
        return [dict(m) for m in self.history]


def _parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        description="多轮对话工具：流式输出 · 完整历史 · 可持久化。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--system",
        default="你是一位严谨的数学辅导老师，回答简练。",
        help="系统角色设定（system prompt）。",
    )
    parser.add_argument(
        "--model",
        default="qwen-plus",
        help="模型名称。",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.0,
        help="采样温度 (0-2)；设为负数则使用模型默认值。",
    )
    parser.add_argument(
        "--load",
        metavar="FILE",
        help="启动时从 JSON 文件加载历史，用于续聊（会覆盖 --system）。",
    )
    parser.add_argument(
        "--save",
        metavar="FILE",
        default="multi_turn_chat.json",
        help="退出时保存历史的文件路径；启动时若该文件存在也会自动续聊。",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="强制全新对话：不自动读取存档（仍可用 --load 手动指定）。",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="退出时不保存历史（忽略 --save）。",
    )
    return parser.parse_args()


if __name__ == "__main__":
    import argparse

    args = _parse_args()
    EXIT_COMMANDS = {"exit", "quit", "退出"}

    print("=" * 60)
    print("  多轮对话工具（流式输出 · 完整历史 · 可持久化）")
    print("=" * 60)

    bot = MultiTurnChat(
        system_prompt=args.system,
        model=args.model,
        temperature=None if args.temperature < 0 else args.temperature,
    )

    # 决定启动历史来源：
    #   --load FILE      → 读取指定文件（续聊）
    #   --fresh          → 全新对话，不读任何存档
    #   否则若存档存在   → 自动续聊（避免忘加 --load 导致覆盖丢失历史）
    load_source: str | None = None
    if args.load:
        load_source = args.load
    elif not args.fresh and os.path.exists(args.save):
        load_source = args.save
        print(f"🔁 检测到存档，自动续聊：{args.save}")

    if load_source:
        try:
            bot.load_history(load_source)
            print(f"📥 已加载历史：{load_source}（{len(bot.messages)} 条消息）")
        except (FileNotFoundError, ValueError, OSError) as e:
            print(f"⚠️  加载历史失败：{e}")
            print("   将以全新对话开始。")

    print("  直接输入问题回车发送，连续输入即为多轮追问。")
    print(f"  输入 {'/'.join(EXIT_COMMANDS)} 结束对话"
          + ("" if args.no_save else f"并保存历史到 {args.save}") + "。")
    print("=" * 60)

    try:
        while True:
            try:
                user_input = input("\n🧑 你：")
            except EOFError:
                # 非交互环境（如管道输入）收到 EOF，等同退出
                print()
                break

            if not user_input.strip():
                continue
            if user_input.strip().lower() in EXIT_COMMANDS:
                break

            print("🤖 ：", end="", flush=True)
            try:
                for piece in bot.chat(user_input):
                    print(piece, end="", flush=True)
                print()
            except RuntimeError as e:
                print(f"\n❌ 本轮出错：{e}")
                print("（历史已回滚，可继续提问或输入 exit 退出）")
    except KeyboardInterrupt:
        print("\n\n收到中断信号，正在退出……")
    finally:
        if args.no_save:
            print("\n👋 已退出（按 --no-save 未保存历史）。")
        else:
            try:
                bot.save(args.save)
                print(f"\n💾 对话历史已保存到：{args.save}")
                print(f"   共 {len(bot.messages)} 条消息。")
            except OSError as e:
                print(f"\n⚠️  保存历史失败：{e}")
