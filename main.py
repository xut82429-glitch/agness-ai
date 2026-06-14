#!/usr/bin/env python3
"""Agnes AI 创作工具 - 图片/视频生成，支持多 API Key 切换"""

import json
import mimetypes
import os
import sys
import time
from pathlib import Path
from urllib import error, parse, request

API_BASE = "https://apihub.agnes-ai.com"
IMAGE_MODEL = "agnes-image-2.1-flash"
VIDEO_MODEL = "agnes-video-v2.0"
OUTPUT_DIR = Path.home() / "Desktop" / "agness" / "output"


# ==================== API Key 管理 ====================

def load_api_keys() -> list[str]:
    keys = []
    for var in ("AGNES_API_KEY", "AGNES_TOKEN", "AGNES_API_KEY_2", "AGNES_API_KEY_3"):
        val = os.environ.get(var, "").strip()
        if val:
            keys.append(val)
    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                _, v = line.split("=", 1)
                v = v.strip().strip("'\"")
                if v and v not in keys:
                    keys.append(v)
    return keys


def choose_api_key(keys: list[str]) -> str:
    if not keys:
        print("没有找到 API Key。")
        print("方式1: export AGNES_API_KEY='your_key'")
        print(f"方式2: 在 {Path(__file__).parent / '.env'} 中写入 AGNES_API_KEY=your_key")
        print(f"\n获取地址: https://platform.agnes-ai.com/settings/apiKeys")
        sys.exit(1)
    if len(keys) == 1:
        print(f"使用 API Key: {keys[0][:8]}...{keys[0][-4:]}")
        return keys[0]
    print("\n可用 API Key:")
    for i, k in enumerate(keys, 1):
        print(f"  [{i}] {k[:8]}...{k[-4:]}")
    while True:
        choice = input(f"\n选择 (1-{len(keys)}): ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(keys):
            selected = keys[int(choice) - 1]
            print(f"已选择: {selected[:8]}...{selected[-4:]}")
            return selected
        print("无效选择，请重试")


# ==================== HTTP 工具 ====================

def api_request(method: str, path: str, api_key: str, payload: dict | None = None) -> dict:
    url = f"{API_BASE}{path}"
    headers = {"Authorization": f"Bearer {api_key}"}
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = request.Request(url, data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=180) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            err = json.loads(body)
            msg = err.get("error", {}).get("message", body) if isinstance(err.get("error"), dict) else body
        except json.JSONDecodeError:
            msg = body
        raise RuntimeError(f"API错误 ({e.code}): {msg}") from e


def download_file(url: str, output_dir: Path, default_name: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    parsed = parse.urlparse(url)
    name = Path(parsed.path).name
    if not name or "." not in name:
        name = default_name
    path = output_dir / name
    with request.urlopen(url, timeout=600) as resp:
        path.write_bytes(resp.read())
    return path


# ==================== 图片生成 ====================

def generate_image(api_key: str):
    print("\n--- 图片生成 ---")
    prompt = input("图片描述: ").strip()
    if not prompt:
        print("描述不能为空")
        return

    size = input("尺寸 (默认 1024x768): ").strip() or "1024x768"
    image_url = input("参考图片URL (留空=文生图): ").strip()

    payload = {"model": IMAGE_MODEL, "prompt": prompt, "size": size}
    if image_url:
        payload["extra_body"] = {"image": [image_url], "response_format": "url"}
    else:
        payload["extra_body"] = {"response_format": "url"}

    print(f"\n生成中...")
    t0 = time.time()
    try:
        resp = api_request("POST", "/v1/images/generations", api_key, payload)
    except RuntimeError as e:
        print(f"失败: {e}")
        return
    elapsed = time.time() - t0
    print(f"完成 ({elapsed:.1f}s)")

    urls = extract_urls(resp)
    if urls:
        for i, url in enumerate(urls, 1):
            print(f"  图片{i}: {url}")
        if input("\n下载图片? (Y/n): ").strip().lower() != "n":
            for i, url in enumerate(urls, 1):
                path = download_file(url, OUTPUT_DIR / "images", f"image_{i}.png")
                print(f"  已保存: {path}")
    else:
        print("响应:")
        print(json.dumps(resp, ensure_ascii=False, indent=2))


def extract_urls(data: Any) -> list[str]:
    urls = []
    if isinstance(data, dict):
        for k, v in data.items():
            if k in ("url", "image_url") and isinstance(v, str) and v.startswith("http"):
                urls.append(v)
            else:
                urls.extend(extract_urls(v))
    elif isinstance(data, list):
        for item in data:
            urls.extend(extract_urls(item))
    return urls


# ==================== 视频生成 ====================

def generate_video(api_key: str):
    print("\n--- 视频生成 ---")
    prompt = input("视频描述: ").strip()
    if not prompt:
        print("描述不能为空")
        return

    image_url = input("输入图片URL (留空=文生视频): ").strip()
    width = int(input("宽度 (默认 1152): ").strip() or "1152")
    height = int(input("高度 (默认 768): ").strip() or "768")
    num_frames = int(input("帧数 81/121/161/241/441 (默认 121): ").strip() or "121")
    frame_rate = float(input("帧率 (默认 24): ").strip() or "24")

    payload = {
        "model": VIDEO_MODEL,
        "prompt": prompt,
        "width": width,
        "height": height,
        "num_frames": num_frames,
        "frame_rate": frame_rate,
    }
    if image_url:
        payload["image"] = image_url

    print(f"\n提交任务...")
    t0 = time.time()
    try:
        resp = api_request("POST", "/v1/videos", api_key, payload)
    except RuntimeError as e:
        print(f"失败: {e}")
        return

    task_id = resp.get("id") or resp.get("task_id") or resp.get("data", {}).get("id")
    if not task_id:
        print("无法获取任务ID:")
        print(json.dumps(resp, ensure_ascii=False, indent=2))
        return

    print(f"任务ID: {task_id}")
    print("等待生成中", end="", flush=True)

    while True:
        time.sleep(3)
        try:
            status_resp = api_request("GET", f"/v1/videos/{parse.quote(task_id)}", api_key)
        except RuntimeError as e:
            print(f"\n查询失败: {e}")
            return

        status = (status_resp.get("status") or status_resp.get("data", {}).get("status", "")).lower()
        progress = status_resp.get("progress") or status_resp.get("data", {}).get("progress", "")
        elapsed = time.time() - t0

        if status in ("completed", "succeeded", "success"):
            print(f"\n完成 ({elapsed:.1f}s)")
            video_url = None
            for key in ("video_url", "url"):
                val = status_resp.get(key) or status_resp.get("data", {}).get(key)
                if isinstance(val, str) and val.startswith("http"):
                    video_url = val
                    break
            if video_url:
                print(f"  视频: {video_url}")
                if input("\n下载视频? (Y/n): ").strip().lower() != "n":
                    path = download_file(video_url, OUTPUT_DIR / "videos", "video.mp4")
                    print(f"  已保存: {path}")
            else:
                print("响应:")
                print(json.dumps(status_resp, ensure_ascii=False, indent=2))
            return

        if status in ("failed", "cancelled", "error"):
            err = status_resp.get("error", {})
            msg = err.get("message", "未知错误") if isinstance(err, dict) else str(err)
            print(f"\n失败 ({elapsed:.1f}s): {msg}")
            return

        print(".", end="", flush=True)


# ==================== 聊天 ====================

def chat(api_key: str):
    print("\n--- AI 对话 (输入 'back' 返回主菜单) ---\n")
    messages = [{"role": "system", "content": "你是一个友好的AI助手，用简洁清晰的中文回答。"}]

    while True:
        user_input = input("你: ").strip()
        if not user_input:
            continue
        if user_input.lower() == "back":
            return

        messages.append({"role": "user", "content": user_input})
        payload = {"model": "agnes-2.0-flash", "messages": messages, "stream": True, "temperature": 0.7}
        url = f"{API_BASE}/v1/chat/completions"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(url, data=data, headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }, method="POST")

        print("AI: ", end="", flush=True)
        full = []
        try:
            with request.urlopen(req, timeout=120) as resp:
                for raw_line in resp:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data: "):
                        continue
                    ds = line[6:]
                    if ds == "[DONE]":
                        break
                    try:
                        chunk = json.loads(ds)
                        c = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
                        if c:
                            print(c, end="", flush=True)
                            full.append(c)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            print(f"\n请求失败: {e}")
            continue

        print()
        messages.append({"role": "assistant", "content": "".join(full)})


# ==================== 主菜单 ====================

def main():
    print("=" * 40)
    print("  Agnes AI 创作工具")
    print("=" * 40)

    keys = load_api_keys()
    api_key = choose_api_key(keys)

    while True:
        print("\n--- 主菜单 ---")
        print("  [1] 生成图片")
        print("  [2] 生成视频")
        print("  [3] AI 对话")
        print("  [4] 切换 API Key")
        print("  [0] 退出")

        choice = input("\n选择功能: ").strip()

        if choice == "1":
            generate_image(api_key)
        elif choice == "2":
            generate_video(api_key)
        elif choice == "3":
            chat(api_key)
        elif choice == "4":
            api_key = choose_api_key(keys)
        elif choice == "0":
            print("再见!")
            break
        else:
            print("无效选择")


if __name__ == "__main__":
    main()
