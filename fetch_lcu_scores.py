# -*- coding: utf-8 -*-
"""
大乱斗(ARAM)战绩抓取 + 本规则评分 —— 基于 LCU API (本地客户端)
==============================================================
原理(同 LeagueAkari): 读取英雄联盟客户端运行时的 lockfile,
      用其中的端口+密码连接 127.0.0.1 本地 API, 无需任何开发者 Key。

适用: 客户端处于"登录且运行"状态时。Riot 直营服通常可用;
      国服(腾讯)官方未提供支持, 但客户端若暴露 LCU 接口则可尝试。

用法:
    1) 启动并登录英雄联盟客户端(保持运行)
    2) python fetch_lcu_scores.py [最近N场, 默认20]
"""

import os
import sys
import base64
import json
import urllib3
import requests
from pathlib import Path

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from aram_score_system import Player, compute  # 本规则评分内核

QUEUE_ARAM = 450


# ---------------- lockfile 定位 ----------------
def find_lockfile() -> str:
    candidates = [
        os.path.expandvars(r"%LOCALAPPDATA%\Riot Games\Riot Client\Config\lockfile"),
        os.path.expandvars(r"%APPDATA%\Riot Games\Riot Client\Config\lockfile"),
        r"C:\ProgramData\Riot Games\Riot Client\Config\lockfile",
    ]
    # 国服/WeGame 安装路径(实测: 客户端装在 Z:\网络游戏\英雄联盟\ 下)
    for drive in ("C", "D", "E", "F", "Z"):
        candidates.append(rf"{drive}:\网络游戏\英雄联盟\Riot Client Data\User Data\Config\lockfile")
        candidates.append(rf"{drive}:\网络游戏\英雄联盟\Riot Client\Config\lockfile")
        candidates.append(rf"{drive}:\Riot Games\Riot Client\Config\lockfile")
        candidates.append(rf"{drive}:\League of Legends\lockfile")
        candidates.append(rf"{drive}:\英雄联盟\Riot Client Data\User Data\Config\lockfile")
    # 环境变量指定(最高优先)
    if os.getenv("LOCKFILE_PATH"):
        candidates.insert(0, os.getenv("LOCKFILE_PATH"))
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return None


def parse_lockfile(path: str):
    text = Path(path).read_text(encoding="utf-8", errors="ignore").strip()
    # 格式: name:pid:port:password:protocol
    _, _, port, password, _ = text.split(":")
    return int(port), password


# ---------------- LCU 会话 ----------------
class LCU:
    def __init__(self, port: int, password: str):
        self.base = f"https://127.0.0.1:{port}"
        token = base64.b64encode(f"riot:{password}".encode()).decode()
        self.s = requests.Session()
        self.s.headers.update({"Authorization": f"Basic {token}"})
        self.s.verify = False

    def get(self, path: str):
        r = self.s.get(self.base + path, timeout=12)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()


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
        tower_dmg=p.get("damageDealtToObjectives", 0),
        minion_dmg=0,
    )


def get_match_detail(lcu: LCU, puuid: str, game_id: int):
    # 先试标准端点, 国服可能用 product 路径
    m = lcu.get(f"/lol-match/v1/matches/{game_id}")
    if m is None:
        m = lcu.get(f"/lol-match-history/v1/products/lol/{puuid}/matches/{game_id}")
    return m


def main():
    lf = find_lockfile()
    if not lf:
        raise SystemExit("❌ 没找到 lockfile。请确认: 1) 英雄联盟客户端已启动并登录; "
                         "2) 若在非常规路径, 设置环境变量 LOCKFILE_PATH 指向 lockfile 后重试。")
    port, pw = parse_lockfile(lf)
    lcu = LCU(port, pw)

    # 国服检测: 读区域, 若为 TENCENT 则 LCU 战绩接口被封锁
    region = (lcu.get("/riotclient/region-locale") or {}).get("region", "")
    if region.upper() == "TENCENT":
        raise SystemExit(
            "⚠️ 检测到当前为【国服/TENCENT】客户端。\n"
            "腾讯已封锁 LCU 的战绩/召唤师接口(/lol-match-history… 返回 404),\n"
            "因此本脚本无法在国服自动抓取战绩(LeagueAkari 同样受此限制)。\n\n"
            "✅ 改用「导入算分」方案:\n"
            "   1) 从「掌上英雄联盟」或 WeGame 把每场比分板截图发我, 我看图帮你填;\n"
            "   2) 或手动填写 matches_input.json(模板已提供), 然后运行:\n"
            "        python score_aram_import.py\n"
            "   仍按本系统的【防刷KDA规则】逐场计算评分与 S~D 评级。"
        )

    me = lcu.get("/lol-summoner/v1/current-summoner")
    if not me or "puuid" not in me:
        raise SystemExit("❌ 无法获取当前账号(客户端可能未登录或接口被国服屏蔽)")
    puuid = me["puuid"]
    print(f"当前账号: {me.get('displayName')}#{me.get('tagLine')}  puuid={puuid[:8]}...")

    count = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    hist = lcu.get(f"/lol-match-history/v1/products/lol/{puuid}/matches?begIndex=0&endIndex={count}")
    if not hist:
        raise SystemExit("❌ 战绩接口返回空。若你是国服账号, 该接口可能不被支持, 请改用 matches_input.json 导入方式。")
    games = hist.get("games", {}).get("games", [])
    aram = [g for g in games if g.get("queueId") == QUEUE_ARAM]
    print(f"最近 {len(games)} 场中, ARAM {len(aram)} 场, 逐场按本规则算分...\n")

    rows = []
    for g in aram:
        gid = g["gameId"]
        m = get_match_detail(lcu, puuid, gid)
        if not m:
            print(f"  · 对局 {gid} 详情获取失败, 跳过")
            continue
        parts = m.get("info", {}).get("participants", [])
        if not parts:
            continue
        target = next((p for p in parts if p.get("puuid") == puuid), None)
        if not target:
            continue
        team = [p for p in parts if p.get("teamId") == target.get("teamId")]
        res = compute([player_from_participant(p) for p in team])
        tname = next((r["name"] for r in res if r["name"].split("#")[-1] in
                      (target.get("riotIdGameName"), target.get("summonerName"))), res[0]["name"])
        trow = next((r for r in res if r["name"] == tname), res[0])
        rows.append((target.get("championName"), target.get("win"), trow))
        res_txt = "  ⚠ " + ",".join(trow["reasons"]) if trow["reasons"] else ""
        print(f"  {target.get('championName'):<12} {'胜' if target.get('win') else '负'}  "
              f"KDA {trow['kda']:>5}  评分 {trow['new_score']:>5}  评级 {trow['grade']}{res_txt}")

    if rows:
        avg = sum(r[2]["new_score"] for r in rows) / len(rows)
        wins = sum(1 for r in rows if r[1])
        print("-" * 60)
        print(f"共 {len(rows)} 场 ARAM | 胜率 {wins}/{len(rows)} | 平均评分 {avg:.1f}")


if __name__ == "__main__":
    main()
