#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DeepSeek 接口测速——判断机器人回复慢的瓶颈在哪。
用法：把本文件放到和 config.json 同一目录，然后：python speedtest.py
会做 4 次计时调用：
  测1 极小回复 -> 基本等于"网络往返 + API排队"
  测2 约50字   -> 短回复生成时间
  测3 约200字  -> 长回复生成时间
  测4 带20轮历史 -> 历史越长请求越大，也会更慢
"""
import json
import os
import sys
import time
import urllib.request


def load_config():
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    base = "https://api.deepseek.com"
    model = "deepseek-chat"
    try:
        with open("config.json", encoding="utf-8") as f:
            cfg = json.load(f)
        key = key or cfg.get("deepseek_api_key", "")
        base = (cfg.get("deepseek_base_url") or base).rstrip("/")
        model = cfg.get("deepseek_model") or model
    except FileNotFoundError:
        pass
    return key, base, model


def call(base, key, model, messages, max_tokens, timeout=60):
    body = json.dumps({
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": False,
    }).encode("utf-8")
    req = urllib.request.Request(base + "/chat/completions", data=body, headers={
        "Authorization": "Bearer " + key,
        "Content-Type": "application/json",
    })
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.load(r)
    return time.time() - t0, data


def main():
    key, base, model = load_config()
    if not key or "在这里填" in key:
        print("错误：没有找到有效的 API Key（config.json 或环境变量 DEEPSEEK_API_KEY）")
        return 1

    print("=" * 50)
    print(f"模型: {model}")
    print(f"接口: {base}")
    print("=" * 50)

    tests = [
        ("测1 极小回复（网络往返，不含生成）",
         [{"role": "user", "content": "请只回复两个字：好的"}], 4),
        ("测2 短回复（约50字）",
         [{"role": "user", "content": "用一句话介绍你自己，50字以内"}], 100),
        ("测3 长回复（约200字）",
         [{"role": "user", "content": "请写一段200字左右的自我介绍"}], 400),
        ("测4 带20轮历史（模拟长对话）",
         [{"role": "user", "content": f"第{i}句：随便说点什么"} for i in range(20)], 100),
    ]
    for name, messages, max_tokens in tests:
        try:
            dt, data = call(base, key, model, messages, max_tokens)
            n = data.get("usage", {}).get("completion_tokens", 0)
            print(f"{name}: {dt:.2f} 秒（生成 {n} tokens）")
        except Exception as e:
            print(f"{name}: 失败! {e}")

    print()
    print("怎么读结果：")
    print("  测1 超过 3 秒  -> 网络/API 排队慢，跟机器人配置无关（查 DNS、代理、WiFi）")
    print("  测2/测3 随字数明显变长 -> 回复越长越慢，去 config.json 让人设把回复改短、max_tokens 调小")
    print("  测4 明显比测2慢  -> 历史记忆太长，调小 history_limit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
