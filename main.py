import os
import textwrap
import requests
from dotenv import load_dotenv
import google.generativeai as genai

# =========================
# 設定読み込み
# =========================

load_dotenv()

GITHUB_TOKEN = os.getenv("GH_API_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

if not GITHUB_TOKEN:
    raise RuntimeError("GH_API_TOKEN が .env から読み込めていません")

if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY が .env から読み込めていません")

if not DISCORD_WEBHOOK_URL:
    raise RuntimeError("DISCORD_WEBHOOK_URL が .env から読み込めていません")

# Gemini 設定
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.0-flash")  # 必要ならモデル名はここで変更

GITHUB_API_BASE = "https://api.github.com"

# 上位何件を要約するか
TOP_N = 2


# =========================
# GitHub API 用ユーティリティ
# =========================

def github_request(path: str, params: dict | None = None, accept_raw: bool = False):
    """GitHub API を叩く共通関数"""
    url = GITHUB_API_BASE + path
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3.raw" if accept_raw else "application/vnd.github.v3+json",
    }
    resp = requests.get(url, headers=headers, params=params)
    print(f"[GitHub] {resp.status_code} {url}")
    if resp.status_code != 200:
        print(resp.text)
        resp.raise_for_status()
    return resp.text if accept_raw else resp.json()


def search_repos(query: str, per_page: int = 5):
    """GitHub リポジトリ検索"""
    params = {
        "q": query,
        "sort": "stars",
        "order": "desc",
        "per_page": per_page,
    }
    data = github_request("/search/repositories", params=params)
    return data["items"]


def fetch_readme(owner: str, repo: str) -> str | None:
    """README をプレーンテキストで取得（なければ None）"""
    path = f"/repos/{owner}/{repo}/readme"
    try:
        readme_text = github_request(path, accept_raw=True)
        return readme_text
    except requests.HTTPError as e:
        print(f"[WARN] README取得失敗: {owner}/{repo} - {e}")
        return None


# =========================
# README 要約（Gemini）
# =========================

def summarize_with_gemini(full_name: str, readme_text: str) -> str:
    """Gemini で README を日本語要約"""

    # 長すぎるREADMEは先頭だけ使ってトークン節約
    max_chars = 5000
    if len(readme_text) > max_chars:
        readme_text = readme_text[:max_chars] + "\n...\n(※長いので一部のみ要約)"

    prompt = f"""
あなたは GitHub リポジトリの README を簡潔に要約するアシスタントです。

以下の README を読み、
- 何をするプロジェクトか
- 主な機能
- 技術的なポイント
- Rikochi AI（自律AIの設計や実装）の参考になりそうな点
を **やさしい日本語で5〜8行程度** にまとめてください。

リポジトリ名: {full_name}

README:
----------------------
{readme_text}
----------------------
"""

    response = model.generate_content(prompt)
    return (response.text or "").strip()


# =========================
# Discord 送信
# =========================

def send_to_discord(content: str):
    """Discord Webhook にテキスト送信"""
    if len(content) > 1900:
        content = content[:1900] + "\n...(文字数制限でカット)"

    payload = {
        "content": content,
        "username": "rikochi_repo",  # 表示名。エージェントごとに変えてもOK
    }
    r = requests.post(DISCORD_WEBHOOK_URL, json=payload)
    print(f"[Discord] {r.status_code}")
    if r.status_code >= 300:
        print(r.text)


# =========================
# メイン処理
# =========================

def main():
    # 🔎 検索クエリ（自由に変えてOK）
    query = "autonomous agent language:Python stars:>200"
    print(f"GitHub 検索クエリ: {query}\n")

    # 取得件数は多めでもOK（ただし要約するのは TOP_N 件だけ）
    repos = search_repos(query, per_page=5)

    # 上位 TOP_N 件だけ要約
    for rank, repo in enumerate(repos[:TOP_N], start=1):
        full_name = repo["full_name"]          # owner/repo
        stars = repo["stargazers_count"]
        desc = repo["description"] or ""
        url = repo["html_url"]

        print(f"\n=== {rank}. {full_name} ===")

        readme = fetch_readme(*full_name.split("/"))
        if not readme:
            print("README が見つからないためスキップ")
            continue

        summary = summarize_with_gemini(full_name, readme)
        print("要約:\n", summary)

        message = textwrap.dedent(f"""
        🏅 ランク {rank}

        📘 **{full_name}**
        ⭐ Stars: {stars}
        🔗 {url}

        📝 説明:
        {desc}

        🧠 README 要約 (Gemini):
        {summary}
        """).strip()

        send_to_discord(message)


if __name__ == "__main__":
    main()
