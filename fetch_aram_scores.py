# -*- coding: utf-8 -*-
"""
大乱斗(ARAM)战绩抓取 + 本规则评分
====================================
数据源: Riot Games 官方 API (https://developer.riotgames.com)
依赖: aram_score_system.py 中的 Player / compute (本规则评分内核)

重要限制:
    Riot 官方 API 仅覆盖 Riot 直营服(美洲/欧洲/韩国/日本/大洋洲),
    **不覆盖中国服(QQ/微信区)**。国服账号请用其他数据源, 本脚本不适用。

使用前配置(三选一):
    1) 直接修改下方 CONFIG 常量
    2) 设置环境变量 RIOT_API_KEY / RIOT_GAME_NAME / RIOT_TAG_LINE / RIOT_REGION
    3) 命令行: python fetch_aram_scores.py KEY NAME TAG REGION [COUNT]

运行: python fetch_aram_scores.py
"""

import os
import sys
import time
import requests

# ---------------- CONFIG ----------------
API_KEY = "在此填入你的 Riot API Key"   # 从 https://developer.riotgames.com 申请
GAME_NAME = "玩家名"                     # Riot ID 前半, 例如 "Hide on bush"
TAG_LINE = "TAG"                         # Riot ID 后半, 例如 "KR1" / "1234" / "EUW"
REGION = "asia"                          # 路由区域: americas / asia / europe
ARAM_COUNT = 10                          # 抓取最近多少场 ARAM
# ----------------------------------------

# 命令行覆盖
if len(sys.argv) >= 5:
    API_KEY, GAME_NAME, TAG_LINE, REGION = sys.argv[1:5]
    if len(sys.argv) >= 6:
        ARAM_COUNT = int(sys.argv[6-1])

API_KEY = os.getenv("RIOT_API_KEY", API_KEY)
GAME_NAME = os.getenv("RIOT_GAME_NAME", GAME_NAME)
TAG_LINE = os.getenv("RIOT_TAG_LINE", TAG_LINE)
REGION = os.getenv("RIOT_REGION", REGION)
ARAM_COUNT = int(os.getenv("ARAM_COUNT", str(ARAM_COUNT)))

# 区域路由映射(平台 -> 路由)
ROUTING = {
    "na1": "americas", "br1": "americas", "lan1": "americas", "las1": "americas",
    "kr": "asia", "jp1": "asia", "oc1": "asia",
    "euw1": "europe", "eune1": "europe", "tr1": "europe", "ru": "europe", "me1": "europe",
}
if REGION in ROUTING:
    REGION = ROUTING[REGION]

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from aram_score_system import Player, compute  # 本规则评分内核

BASE = f"https://{REGION}.api.riotgames.com"
HEADERS = {"X-Riot-Token": API_KEY}
QUEUE_ARAM = 450  # 大乱斗


def _get(url: str) -> dict:
    r = requests.get(url, headers=HEADERS, timeout=15)
    if r.status_code == 403:
        raise SystemExit("❌ 403: API Key 无效或已过期 (开发者门户可重新生成)")
    if r.status_code == 404:
        raise SystemExit("❌ 404: 找不到该玩家, 检查 GAME_NAME / TAG_LINE / REGION 是否正确")
    if r.status_code == 429:
        wait = int(r.headers.get("Retry-After", "3"))
        print(f"  · 触发限流, 等待 {wait}s ...")
        time.sleep(wait)
        return _get(url)
    r.raise_for_status()
    return r.json()


def get_puuid() -> str:
    url = f"{BASE}/riot/account/v1/accounts/by-riot-id/{GAME_NAME}/{TAG_LINE}"
    data = _get(url)
    return data["puuid"]


def get_aram_match_ids(puuid: str) -> list:
    url = (f"{BASE}/lol/match/v5/matches/by-puuid/{puuid}/ids"
           f"?queue={QUEUE_ARAM}&count={ARAM_COUNT}")
    return _get(url)


def player_from_participant(p: dict) -> Player:
    return Player(
        name=f"{p.get('championName','?')}#{p.get('riotIdGameName') or p.get('summonerName') or '?'}",
        kills=p.get("kills", 0),
        assists=p.get("assists", 0),
        deaths=p.get("deaths", 0),
        dmg_to_champs=p.get("totalDamageDealtToChampions", 0),
        dmg_taken=p.get("totalDamageTaken", 0),
        healing=p.get("totalHeal", 0),
        shielding=p.get("totalDamageShielded", 0),
        cc_seconds=float(p.get("timeCCingOthers", 0)),
        tower_dmg=p.get("damageDealtToObjectives", 0),  # ARAM 推进≈塔伤
        minion_dmg=0,
    )


def score_match(match_id: str, puuid: str) -> dict:
    m = _get(f"{BASE}/lol/match/v5/matches/{match_id}")
    info = m["info"]
    parts = info["participants"]
    # 找到目标玩家, 取其所在队伍
    target = next(p for p in parts if p.get("puuid") == puuid)
    team_id = target["teamId"]
    team = [p for p in parts if p["teamId"] == team_id]
    players = [player_from_participant(p) for p in team]
    results = compute(players)
    # 取目标玩家的结果(按 champion#name 近似匹配)
    tname = next((r["name"] for r in results if r["name"].split("#")[-1] in
                  (target.get("riotIdGameName"), target.get("summonerName"))), None)
    trow = next((r for r in results if r["name"] == tname), results[0])
    return {
        "match_id": match_id,
        "champion": target.get("championName"),
        "win": target.get("win"),
        "score": trow["new_score"],
        "grade": trow["grade"],
        "kda": trow["kda"],
        "kp": trow["kp"],
        "eci": trow["eci"],
        "reasons": trow["reasons"],
        "board": sorted(results, key=lambda x: -x["new_score"]),  # 本队全部分数
    }


def main():
    if API_KEY.startswith("在此填入") or not API_KEY:
        raise SystemExit("❌ 请先配置 API_KEY (脚本顶部 CONFIG / 环境变量 / 命令行)")
    print(f"抓取 {GAME_NAME}#{TAG_LINE} 最近 {ARAM_COUNT} 场 ARAM (路由: {REGION}) ...")
    puuid = get_puuid()
    ids = get_aram_match_ids(puuid)
    if not ids:
        raise SystemExit("⚠ 该玩家最近没有 ARAM 战绩 (queue=450)")
    print(f"找到 {len(ids)} 场, 逐场计算评分...\n")

    rows = []
    for i, mid in enumerate(ids, 1):
        try:
            r = score_match(mid, puuid)
        except Exception as e:
            print(f"  [{i}] {mid} 解析失败: {e}")
            continue
        rows.append(r)
        res = "胜" if r["win"] else "负"
        flag = ("  ⚠ " + ",".join(r["reasons"])) if r["reasons"] else ""
        print(f"[{i}] {r['champion']:<12} {res}  KDA {r['kda']:>5}  "
              f"评分 {r['score']:>5}  评级 {r['grade']}{flag}")

    if rows:
        avg = sum(r["score"] for r in rows) / len(rows)
        wins = sum(1 for r in rows if r["win"])
        print("-" * 60)
        print(f"共 {len(rows)} 场 | 胜率 {wins}/{len(rows)} | 平均评分 {avg:.1f}")
        # 保存本队完整比分板到文件
        with open("aram_scores_output.txt", "w", encoding="utf-8") as f:
            for r in rows:
                f.write(f"{r['champion']} {'胜' if r['win'] else '负'} "
                        f"评分{r['score']} 评级{r['grade']} "
                        f"KDA{r['kda']} KP{r['kp']} ECI{r['eci']}\n")
                for b in r["board"]:
                    f.write(f"    {b['name']:<22} {b['new_score']:>5} {b['grade']}\n")
        print("完整比分板已写入 aram_scores_output.txt")


if __name__ == "__main__":
    main()
