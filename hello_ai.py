import os
import warnings

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

client = OpenAI(
    api_key=os.getenv("QWEN_API_KEY"),
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
)


def ask_llm(
    prompt: str,
    system_prompt: str = "You are a helpful assistant.",
    temperature: float | None = None,
    model: str = "qwen-plus",
) -> str:
    """调用大语言模型并返回回复文本。

    Args:
        prompt: 用户输入的提示词。
        system_prompt: 系统角色设定。
        temperature: 采样温度（0-2），越高越随机；传 None 使用模型默认值。
        model: 模型名称。

    Returns:
        模型返回的文本内容。

    Raises:
        ValueError: prompt 或 system_prompt 为空时抛出。
        RuntimeError: 封装后的 API 调用错误。
    """
    if not prompt or not prompt.strip():
        raise ValueError("prompt 不能为空，请输入有效的提示词。")
    if not system_prompt or not system_prompt.strip():
        raise ValueError("system_prompt 不能为空。")

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]

    # temperature 合法范围 (0, 2)，闭区间下界 0，开区间上界 2
    if temperature is not None:
        TEMPERATURE_MIN, TEMPERATURE_MAX = 0.0, 1.99
        if temperature < TEMPERATURE_MIN or temperature >= TEMPERATURE_MAX:
            clamped = max(TEMPERATURE_MIN, min(temperature, TEMPERATURE_MAX))
            warnings.warn(
                f"temperature={temperature} 超出有效范围 [{TEMPERATURE_MIN}, {TEMPERATURE_MAX})，"
                f"已自动调整为 {clamped}"
            )
            temperature = clamped

    params = {
        "model": model,
        "messages": messages,
        "stream": False,
    }
    if temperature is not None:
        params["temperature"] = temperature

    try:
        response = client.chat.completions.create(**params)
        return response.choices[0].message.content

    except AuthenticationError:
        raise RuntimeError(
            "API Key 无效或已过期，请检查环境变量 QWEN_API_KEY 是否正确。"
        )
    except APIConnectionError:
        raise RuntimeError(
            "网络连接失败，请检查网络是否畅通或 API 地址是否正确。"
        )
    except RateLimitError:
        raise RuntimeError(
            "API 调用频率过高，请稍后重试。"
        )
    except APITimeoutError:
        raise RuntimeError(
            "API 请求超时，请检查网络状况后重试。"
        )
    except APIError as e:
        raise RuntimeError(
            f"API 返回错误（状态码 {e.status_code}）：{e.message}"
        )
    except OSError as e:
        raise RuntimeError(
            f"网络错误，请检查网络连接：{e}"
        )
    except Exception as e:
        raise RuntimeError(
            f"调用 LLM 时发生未知错误：{e}"
        )


if __name__ == "__main__":
    try:
        reply = ask_llm(
            prompt="你认识陈赫鸣吗?",
            system_prompt="你是一位悲观主义的诗人。",
            temperature=0,
        )
        print(reply)
    except (ValueError, RuntimeError) as e:
        print(f"❌ 错误：{e}")
