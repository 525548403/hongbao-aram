# -*- coding: utf-8 -*-
"""
单场战绩 -> 弹窗视图模型(与 Web 端评分完全一致)
================================================================
从一场 SGP DETAILS 构造原生弹窗所需的数据:
  - 按"我"所在队伍, 用 aram_web.score_team 算分(同队相对贡献, 防刷KDA)
  - 敌我两队分别算, 标注 is_me / win
  - 若提供组队名单(party_names), 复用 aram_redpacket.apply_red_packet 标🧧

本模块不依赖任何 GUI 库, 可离线单测(给 build_match_view 喂一份 v5 形状
的 DETAILS 即可)。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from aram_web import score_team, champion_cn
from aram_redpacket import apply_red_packet
from aram_akari_framework import ARAM_QUEUE_IDS


def participants_from_details(details):
    """兼容 Riot match-v5(info.participants) 与腾讯 SGP(顶层 participants)。
    返回 (participants_list, game_id)。"""
    if isinstance(details, dict):
        info = details.get("info")
        if isinstance(info, dict) and info.get("participants"):
            gid = details.get("metadata", {}).get("gameId") or details.get("gameId")
            return info["participants"], str(gid) if gid else None
        if details.get("participants"):
            return details["participants"], (str(details["gameId"])
                                            if details.get("gameId") else None)
    return [], None


def build_match_view(details, puuid, party_names=None, unit=10.0, penta_unit=20.0,
                      include_enemy=False):
    """构造弹窗视图模型。返回 dict, 或 {"skip": True, ...} 表示跳过(非大乱斗)。

    include_enemy: 是否附带敌方 5 人(默认 **False** —— 弹窗只显示我方 5 人)。
        评分始终按"我方 5 人"内部横向比较, 敌方分数对开黑记账无意义。
    """
    parts, game_id = participants_from_details(details)
    if not parts:
        return None

    qid = parts[0].get("queueId")
    if qid not in ARAM_QUEUE_IDS:
        return {"skip": True, "reason": f"非大乱斗队列(queueId={qid})",
                "queue_id": qid}

    me = next((p for p in parts if p.get("puuid") == puuid), None)
    if me is None:
        return None

    team_id = me.get("teamId")
    own = [p for p in parts if p.get("teamId") == team_id]
    enemy = [p for p in parts if p.get("teamId") != team_id]

    # 评分只用我方 5 人(同队相对贡献才是开黑记账的依据)
    own_res = score_team(own, puuid)

    players = []
    for p in own_res["players"]:
        players.append({
            "name": p["name"],
            "champion_cn": p.get("champion_cn"),
            "kda": p.get("kda"),
            "new_score": p.get("new_score"),
            "grade": p.get("grade"),
            "win": bool(me.get("win")),
            "is_me": p["name"] == own_res["me_name"],
        })
    if include_enemy:
        enemy_res = score_team(enemy, None)
        for p in enemy_res["players"]:
            players.append({
                "name": p["name"],
                "champion_cn": p.get("champion_cn"),
                "kda": p.get("kda"),
                "new_score": p.get("new_score"),
                "grade": p.get("grade"),
                "win": not bool(me.get("win")),
                "is_me": False,
            })

    match = {
        "gameId": game_id,
        "queue_id": qid,
        "champion": me.get("championName"),
        "champion_cn": champion_cn(me.get("championName")),
        "win": bool(me.get("win")),
        "me_name": own_res["me_name"],
        "players": players,
    }

    # 红包标注(若提供了组队名单): 在 players 对象上就地标注 party_member/rank/red_packet
    if party_names:
        apply_red_packet(match, list(party_names))
        for p in players:
            p["red_packet"] = bool(p.get("red_packet"))
            p["party_member"] = bool(p.get("party_member"))
        match["party_payers"] = match.get("party_payers", [])
    else:
        match["party_payers"] = []

    players.sort(key=lambda x: -(x.get("new_score") or 0))
    match["me_row"] = next((i for i, p in enumerate(players) if p["is_me"]), None)
    return match


def sample_details():
    """造一份 Riot match-v5 形状的 10 人 ARAM 数据(供测试弹窗 / 离线自测)。"""
    return {
        "metadata": {"gameId": "TEST-123"},
        "info": {"participants": [
            {"puuid": "ME", "teamId": 100, "win": True, "championName": "Jinx",
             "riotIdGameName": "阿伟", "kills": 12, "assists": 8, "deaths": 3,
             "totalDamageDealtToChampions": 35000, "totalDamageTaken": 18000,
             "totalHeal": 2000, "totalDamageShieldedOnTeammates": 500,
             "timeCCingOthers": 15, "damageDealtToObjectives": 1200,
             "pentaKills": 1, "queueId": 450},
            {"puuid": "T2", "teamId": 100, "win": True, "championName": "Leona",
             "riotIdGameName": "老K", "kills": 1, "assists": 20, "deaths": 5,
             "totalDamageDealtToChampions": 4000, "totalDamageTaken": 30000,
             "totalHeal": 8000, "totalDamageShieldedOnTeammates": 6000,
             "timeCCingOthers": 40, "damageDealtToObjectives": 300, "pentaKills": 0,
             "queueId": 450},
            {"puuid": "T3", "teamId": 100, "win": True, "championName": "Soraka",
             "riotIdGameName": "软妹", "kills": 0, "assists": 22, "deaths": 4,
             "totalDamageDealtToChampions": 1500, "totalDamageTaken": 12000,
             "totalHeal": 12000, "totalDamageShieldedOnTeammates": 3000,
             "timeCCingOthers": 10, "damageDealtToObjectives": 100, "pentaKills": 0,
             "queueId": 450},
            {"puuid": "T4", "teamId": 100, "win": True, "championName": "Garen",
             "riotIdGameName": "大熊", "kills": 6, "assists": 5, "deaths": 6,
             "totalDamageDealtToChampions": 18000, "totalDamageTaken": 25000,
             "totalHeal": 1000, "totalDamageShieldedOnTeammates": 0,
             "timeCCingOthers": 8, "damageDealtToObjectives": 800, "pentaKills": 0,
             "queueId": 450},
            {"puuid": "T5", "teamId": 100, "win": True, "championName": "Veigar",
             "riotIdGameName": "小法", "kills": 9, "assists": 7, "deaths": 5,
             "totalDamageDealtToChampions": 28000, "totalDamageTaken": 9000,
             "totalHeal": 500, "totalDamageShieldedOnTeammates": 0,
             "timeCCingOthers": 5, "damageDealtToObjectives": 400, "pentaKills": 0,
             "queueId": 450},
            {"puuid": "E1", "teamId": 200, "win": False, "championName": "Teemo",
             "riotIdGameName": "蘑菇", "kills": 4, "assists": 6, "deaths": 7,
             "totalDamageDealtToChampions": 16000, "totalDamageTaken": 15000,
             "totalHeal": 800, "totalDamageShieldedOnTeammates": 200,
             "timeCCingOthers": 12, "damageDealtToObjectives": 600, "pentaKills": 0,
             "queueId": 450},
            {"puuid": "E2", "teamId": 200, "win": False, "championName": "Yasuo",
             "riotIdGameName": "亚索", "kills": 8, "assists": 4, "deaths": 8,
             "totalDamageDealtToChampions": 24000, "totalDamageTaken": 14000,
             "totalHeal": 300, "totalDamageShieldedOnTeammates": 0,
             "timeCCingOthers": 6, "damageDealtToObjectives": 500, "pentaKills": 0,
             "queueId": 450},
            {"puuid": "E3", "teamId": 200, "win": False, "championName": "Lux",
             "riotIdGameName": "拉克丝", "kills": 5, "assists": 9, "deaths": 6,
             "totalDamageDealtToChampions": 20000, "totalDamageTaken": 8000,
             "totalHeal": 600, "totalDamageShieldedOnTeammates": 400,
             "timeCCingOthers": 20, "damageDealtToObjectives": 300, "pentaKills": 0,
             "queueId": 450},
            {"puuid": "E4", "teamId": 200, "win": False, "championName": "Braum",
             "riotIdGameName": "布隆", "kills": 2, "assists": 14, "deaths": 7,
             "totalDamageDealtToChampions": 5000, "totalDamageTaken": 22000,
             "totalHeal": 5000, "totalDamageShieldedOnTeammates": 4000,
             "timeCCingOthers": 35, "damageDealtToObjectives": 200, "pentaKills": 0,
             "queueId": 450},
            {"puuid": "E5", "teamId": 200, "win": False, "championName": "Ahri",
             "riotIdGameName": "阿狸", "kills": 7, "assists": 8, "deaths": 6,
             "totalDamageDealtToChampions": 22000, "totalDamageTaken": 11000,
             "totalHeal": 700, "totalDamageShieldedOnTeammates": 0,
             "timeCCingOthers": 18, "damageDealtToObjectives": 450, "pentaKills": 0,
             "queueId": 450},
        ]},
    }


if __name__ == "__main__":
    # 离线自测: 造一份 Riot match-v5 形状的 10 人 ARAM 数据
    import json
    sample = sample_details()
    vm = build_match_view(sample, "ME", party_names=["阿伟", "老K", "软妹"])
    print(json.dumps(vm, ensure_ascii=False, indent=2))
