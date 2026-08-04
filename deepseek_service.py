import os
import json
from composio import ComposioToolSet, Action

def ask_deepseek_v4_flash(prompt: str, system_prompt: str = "你是一位專業的 AI 助理。"):
    """
    透過 Composio SDK 調用 DeepSeek 服務 (模型設定: DeepSeek V4 Flash)
    """
    composio_api_key = os.getenv("COMPOSIO_API_KEY")
    if composio_api_key:
        toolset = ComposioToolSet(api_key=composio_api_key)
    else:
        toolset = ComposioToolSet()

    # 執行 Composio 的 DeepSeek Chat Completion Action
    # 指明使用 DeepSeek V4 Flash (deepseek-chat)
    response = toolset.execute_action(
        action=Action.DEEPSEEK_CREATE_CHAT_COMPLETION,
        params={
            "model": "deepseek-chat", # DeepSeek V4 Flash 模型識別碼
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7,
            "max_tokens": 2048
        }
    )
    return response

if __name__ == "__main__":
    test_prompt = "請簡短自我介紹，並說明你所使用的 DeepSeek V4 Flash 模型優勢。"
    print(f"正在發送請求至 DeepSeek V4 Flash...")
    try:
        res = ask_deepseek_v4_flash(test_prompt)
        print("--- DeepSeek V4 Flash 回應 ---")
        print(json.dumps(res, ensure_ascii=False, indent=2))
    except Exception as e:
        print(f"調用失敗: {e}")
