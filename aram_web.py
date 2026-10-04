# -*- coding: utf-8 -*-
"""
红包乱斗 —— 网页版(本地服务)
==========================================
后端复用:
    aram_score_system.compute       (评分内核)
    aram_akari_framework.*          (LeagueAkari 国服 LCU+SGP 抓取)

提供:
    GET  /                -> 前端页面(index.html)
    GET  /api/sample      -> 演示数据(无需客户端即可预览界面)
    GET  /api/fetch?count=20 -> 经 LCU+SGP 拉取真实国服战绩并算分
    POST /api/import      -> 接收手动填写的战绩 JSON 并算分

运行: python aram_web.py [端口, 默认 8777]
    —— 在已登录英雄联盟客户端、能联网(国服需加速器)的机器上运行, 打开
       http://127.0.0.1:8777 即可看到雷达图 + S~D 评级评分面板。
"""

import os
import sys
import json
import time
import urllib
import webbrowser
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from aram_score_system import Player, compute          # 评分内核
from aram_akari_framework import (                       # Akari 国服抓取
    lcu_auth, get_entitlements, SgpFetcher, QUEUE_ARAM,
    read_league_akari_config, fetch_aram_matches,
)
from aram_redpacket import (                                  # 红包局规则
    apply_red_packet, apply_penta_bounty, aggregate_stats, detect_party,
)
from aram_champions import champion_cn                        # 英文中文名

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8777
APP_VERSION = "1.3.0 (开发版 / dev)"  # 单一版本来源: 前端徽标由后端注入


def resource_path(rel: str) -> str:
    """打包后(onefile)资源位于 sys._MEIPASS; 开发态回退到脚本目录。"""
    base = getattr(sys, "_MEIPASS", None)
    return os.path.join(base, rel) if base else os.path.join(HERE, rel)


# ============================================================
# 数据转换与算分封装(返回前端友好的结构化数据)
# ============================================================
def raw_to_player(d: dict) -> Player:
    def num(*keys, default=0):
        for k in keys:
            if k in d and d[k] is not None:
                return d[k]
        return default
    return Player(
        name=d.get("name") or d.get("riotIdGameName") or d.get("summonerName") or "?",
        kills=int(num("kills", default=0)),
        assists=int(num("assists", default=0)),
        deaths=int(num("deaths", default=0)),
        dmg_to_champs=int(num("dmg_to_champs", "totalDamageDealtToChampions", default=0)),
        dmg_taken=int(num("dmg_taken", "totalDamageTaken", default=0)),
        healing=int(num("healing", "totalHeal", default=0)),
        shielding=int(num("shielding", "totalDamageShieldedOnTeammates", default=0)),
        cc_seconds=float(num("cc_seconds", "timeCCingOthers", default=0) or 0),
        tower_dmg=int(num("tower_dmg", "damageDealtToObjectives", default=0)),
        minion_dmg=int(num("minion_dmg", default=0)),
        champion=d.get("champion") or d.get("championName") or "",
    )


def _heal_val(raw: dict) -> float:
    """有效治疗(对队友的治疗量); SGP 缺该字段时回退总治疗 totalHeal。"""
    for k in ("totalHealsOnTeammates", "healsOnTeammates", "heals_on_teammates"):
        if k in raw and raw[k] is not None:
            return float(raw[k] or 0)
    return float(raw.get("healing") or raw.get("totalHeal") or 0)


def _shield_val(raw: dict) -> float:
    """给队友的护盾量。"""
    for k in ("totalDamageShieldedOnTeammates", "shielding"):
        if k in raw and raw[k] is not None:
            return float(raw[k] or 0)
    return 0.0


def score_team(team_raw: list, me_puuid: str = None) -> dict:
    """对一队(5人)原始数据算分, 返回 {players, radar, me_name}."""
    players = [raw_to_player(p) for p in team_raw]
    results = compute(players)

    # ---- 计算雷达维度(各维度占全队百分比, 0~100), 六维:
    #      伤害 / 承伤 / 辅助(有效治疗+给队友的盾) / 控制 / 参战 / 推进
    aux_vals = [_heal_val(r) + _shield_val(r) for r in team_raw]

    t_dmg = max(1, sum(p.dmg_to_champs for p in players))
    t_tank = max(1, sum(p.dmg_taken for p in players))
    t_aux = max(1, sum(aux_vals))
    t_cc = max(1, sum(p.cc_seconds for p in players))
    t_k = max(1, sum(p.kills + p.assists for p in players))
    t_obj = max(1, sum(p.tower_dmg + p.minion_dmg for p in players))

    radar = []
    for p, av in zip(players, aux_vals):
        radar.append({
            "dmg": round(p.dmg_to_champs / t_dmg * 100, 1),
            "tank": round(p.dmg_taken / t_tank * 100, 1),
            "aux": round(av / t_aux * 100, 1),
            "cc": round(float(p.cc_seconds or 0) / t_cc * 100, 1),
            "kp": round((p.kills + p.assists) / t_k * 100, 1),
            "obj": round((p.tower_dmg + p.minion_dmg) / t_obj * 100, 1),
        })

    # 标记"我"
    me_name = None
    if me_puuid:
        for r, raw in zip(results, team_raw):
            if raw.get("puuid") == me_puuid:
                me_name = r["name"]
    if not me_name and results:
        me_name = max(results, key=lambda r: r["new_score"])["name"]

    players_out = []
    for r, rdr, raw in zip(results, radar, team_raw):
        out = dict(r)
        out["radar"] = rdr
        # 五杀次数: 战绩 participants 自带 pentaKills 字段
        try:
            out["penta_kills"] = int(raw.get("pentaKills")
                                     or raw.get("penta_kills") or 0)
        except (TypeError, ValueError):
            out["penta_kills"] = 0
        out["champion_cn"] = champion_cn(out.get("champion"))
        players_out.append(out)

    return {"players": players_out, "me_name": me_name}


def build_match(parts: list, puuid: str, game_id=None, win=None, champion=None,
                game_creation=None):
    """从单场 10 人 participants 构造一场己方5人评分结果."""
    me = next((p for p in parts if p.get("puuid") == puuid), None)
    if me is None:
        return None
    team = [p for p in parts if p.get("teamId") == me.get("teamId")]
    if not team:
        return None
    scored = score_team(team, puuid)
    champ_cn = champion_cn(champion or me.get("championName"))
    return {
        "gameId": game_id,
        "champion": champion or me.get("championName"),
        "champion_cn": champ_cn,
        "win": win if win is not None else bool(me.get("win")),
        # 对局开始时间(毫秒): 红包局统计起点判定依据(与组队识别无关)
        "game_creation": int(game_creation) if game_creation else None,
        "players": scored["players"],
        "me_name": scored["me_name"],
    }


# ============================================================
# 红包局结算流水线(识别组队 -> 红包标注 -> 五杀赏金 -> 统计)
# ============================================================
def finalize(matches: list, me_names: list, unit: float = 10.0,
             penta_unit: float = 20.0, min_games: int = None,
             party_names: list = None) -> dict:
    """对已算分的 matches 做完整红包局结算, 返回带标注的数据。

    min_games: 组队识别门槛(共同游戏场数), None=默认 2 场。
    party_names: 直接指定组队名单(来自100场识别池/手动添加), 跳过自动识别。
    """
    if party_names is None:
        party_info = detect_party(matches, min_games)
        names = sorted(set(me_names)) + [x["name"] for x in party_info]
    else:
        names = [str(n).strip() for n in party_names if str(n).strip()]
        party_info = None
    for m in matches:
        apply_red_packet(m, names)
        apply_penta_bounty(m, penta_unit)
    stats = aggregate_stats(matches, unit, penta_unit)
    return {
        "unit": unit,
        "penta_unit": penta_unit,
        "me_names": sorted(set(me_names)),
        "party_names": names,
        "party_info": party_info,
        "matches": matches,
        "stats": stats,
    }


# ============================================================
# 参数持久化(下次打开保留金额/阈值/组队名单等设置)
# ============================================================
# exe(单文件)运行时设置文件与 exe 同目录; 脚本运行时与脚本同目录
SETTINGS_FILE = os.path.join(
    os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else HERE,
    "aram_settings.json")


def load_settings() -> dict:
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_settings(**kv):
    try:
        s = load_settings()
        s.update(kv)
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ============================================================
# 远程抓取(LeagueAkari 国服机制)
# ============================================================
DETECT_POOL_SIZE = 100  # 「仅本次拉取」模式: 拉最近 100 场作识别池并展示前 count 场
# 「累计增量」模式: 不限场数 —— 翻页拉取直到追上战绩库已有对局(即上次
# 已收录), 自动补齐期间新打的所有场次; 封顶 500 场防止首次拉取过多。
INCREMENTAL_SCAN_LIMIT = 500

def merge_party_names(me_names, party_info, manual_add, manual_removed) -> list:
    """组队名单三源合一: 自动识别 ∪ 手动添加(持久) − 手动移除黑名单(持久)。

    之前只持久化整体名单并在下次拉取时覆盖新识别结果, 导致识别结果
    "闪一下就没"。现在拆分: 识别每次新鲜计算, 手动增删单独持久化,
    移除的人即使再次被识别也不会回来。
    """
    manual_removed = {str(n).strip() for n in (manual_removed or [])}
    merged = (sorted(set(me_names or []))
              + [x["name"] for x in (party_info or [])]
              + [str(n).strip() for n in (manual_add or []) if str(n).strip()])
    seen = set()
    return [n for n in merged
            if n not in manual_removed and not (n in seen or seen.add(n))]


# 识别池缓存: 供「组队阈值」调整时重新识别, 无需重新拉取 100 场
_POOL = {"pool": [], "me_names": []}

# 「拉取全部战绩」(single)模式最近一次拉取的完整匹配池(未经 count 切片)。
# 供「往前/往后一场」按钮在已拉取范围内 ±1 重新切片, 无需再次联网拉取。
_LAST_SINGLE_POOL = []

# ============================================================
# 桌面常驻程序的对局结束广播(供已打开的 Web 面板自动刷新)
# ============================================================
# 桌面程序检测到对局结束并算分完成后调用 publish_live_match(); Web 面板轮询
# GET /api/live, 发现 seq 变化即自动按当前模式刷新一次, 无需用户手点。
_LIVE = {"seq": 0, "match": None, "at": 0}


def publish_live_match(vm: dict):
    """广播一场刚结束的对局(Web 面板据此自动刷新)。线程安全(整体替换)。"""
    if not vm:
        return
    _LIVE["seq"] = int(_LIVE.get("seq") or 0) + 1
    _LIVE["match"] = {
        "gameId": vm.get("gameId"),
        "champion": vm.get("champion"),
        "champion_cn": vm.get("champion_cn"),
        "win": vm.get("win"),
        "me_name": vm.get("me_name"),
        "party_payers": vm.get("party_payers") or [],
    }
    _LIVE["at"] = int(time.time())


def live_state() -> dict:
    """返回给 Web 面板的广播状态。"""
    return {"seq": int(_LIVE.get("seq") or 0),
            "match": _LIVE.get("match"),
            "at": _LIVE.get("at") or 0}

# ============================================================
# 战绩本地存储(增量累计模式): 拉取过的新对局存入 aram_matches.json。
# 两条线彻底分开:
#   - 组队识别: 每次拉取的识别池(最近100/500场)现场分析, 不落库;
#   - 红包局统计: 只汇总「统计起点 started_at」之后的对局 ——
#     即用户开始用本工具记账之后打的场次, 回填的历史对局不计入。
# 文件格式: {"_started_at": 毫秒时间戳|null, "_matches": {gameId: match}}
# ============================================================
MATCH_STORE_FILE = os.path.join(
    os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else HERE,
    "aram_matches.json")


def load_match_store():
    """返回 (started_at 毫秒|None, {gameId(str): match dict})。

    兼容旧格式(纯 {gameId: match}): 迁移时统计起点取战绩库文件的
    创建时间(= 用户开始使用本工具记账的时刻), 库里早于此的历史
    对局(回填等)不进入红包局统计。
    """
    try:
        with open(MATCH_STORE_FILE, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict) and isinstance(d.get("_matches"), dict):
            return d.get("_started_at"), d["_matches"]
        if isinstance(d, dict) and d:            # 旧格式迁移
            try:
                started = int(os.path.getctime(MATCH_STORE_FILE) * 1000)
            except Exception:
                started = None
            return started, d
    except Exception:
        pass
    return None, {}


def save_match_store(started_at, matches: dict):
    try:
        with open(MATCH_STORE_FILE, "w", encoding="utf-8") as f:
            json.dump({"_started_at": started_at, "_matches": matches},
                      f, ensure_ascii=False)
    except Exception:
        pass


def scope_matches(all_matches: list, started_at) -> list:
    """红包局统计范围: started_at 之后打的对局(新->旧)。

    started_at 为 None 时统计全部(等价于"统计全部"按钮)。
    没有时间戳的对局(极旧条目)仅在 started_at 为 None 时计入。
    """
    ms = sorted(all_matches,
                key=lambda m: int(m.get("gameId") or 0), reverse=True)
    if started_at is None:
        return ms
    return [m for m in ms
            if m.get("game_creation") and m["game_creation"] >= started_at]


def run_remote(count: int = 20, unit: float = 10.0,
               penta_unit: float = 20.0, min_games: int = None,
               count_mode: str = "single", stats_start: str = None) -> dict:
    try:
        lcu_base, lcu_s, cfg = lcu_auth()
        token, puuid = get_entitlements(lcu_base, lcu_s)
        rso = (cfg or {}).get("rsoPlatformId", "HN10")
        region = (cfg or {}).get("region", "TENCENT")
        fetcher = SgpFetcher(token, rso, region)
        # 0) 增量模式: 先读战绩库, 翻页拉取时"追到已有对局就停" -> 自动补齐
        #    上次拉取以来新打的所有场次, 无固定场数限制(封顶 500 场防失控)
        if count_mode == "incremental":
            started_at, store = load_match_store()
            scan_count = INCREMENTAL_SCAN_LIMIT
            stop_gids = set(store.keys())
            # 统计起点调整(仅影响红包局统计范围, 不影响组队识别):
            #   now  = 把起点锚定到「上一把」(战绩库当前最新一把的结束时间),
            #          之后新打的局(game_creation 更晚)以增量形式追加, 不重置已有数据;
            #          库为空时暂不设起点, 等下面拉取后再锚定。
            #   reset = 统计全部(不过滤)。
            if stats_start == "now":
                # 仅在尚未锚定时锚定起点(=上一把), 之后保持该起点不变,
                # 让后续增量拉取把新对局追加到起点之后。否则每点一次都重锚定到
                # 最新一把, 统计范围被压缩成只剩最新一把, 失去"增量累积"效果。
                if started_at is None:
                    gcs = [int(m["game_creation"]) for m in store.values()
                           if m.get("game_creation")]
                    if gcs:
                        started_at = max(gcs)   # 锚定到最新一把(上一把)的结束时间
            elif stats_start == "reset":
                started_at = None
        else:
            started_at, store = None, None
            # 「拉取全部战绩」: 按场次填入拉取最近 N 场并全部统计(N 场识别池足够)
            scan_count = max(1, int(count) if count else DETECT_POOL_SIZE)
            stop_gids = None
        # 1) 分页拉取战绩(同时作为组队识别池: 固定好友几乎场场同队)
        pool_parsed = fetch_aram_matches(fetcher, puuid, scan_count,
                                         stop_gids=stop_gids)
        pool_matches = []
        seen_gids = set()
        for m in pool_parsed:
            gid = m.get("game_id")
            # 按 gameId 去重: 同一场重复出现会导致红包/赏金全部翻倍
            if gid is not None and gid in seen_gids:
                continue
            seen_gids.add(gid)
            mres = build_match(m["participants"], puuid, game_id=gid,
                               win=m["win"], champion=m["champion"],
                               game_creation=m.get("game_creation"))
            if mres:
                pool_matches.append(mres)
        # 2) 组队识别: 只用识别池(与红包局统计范围无关, 两套计算)
        me_names_pool = [m["me_name"] for m in pool_matches]
        party_info = detect_party(pool_matches, min_games)
        # 名单三源合一: 自动识别 ∪ 手动添加(持久) − 手动移除黑名单(持久)
        _scfg = load_settings()
        party_names = merge_party_names(
            me_names_pool, party_info,
            _scfg.get("party_manual_add"), _scfg.get("party_removed"))
        _POOL["pool"] = pool_matches
        _POOL["me_names"] = me_names_pool
        # 3) 红包局统计范围(与识别分开):
        #    incremental=战绩库中「统计起点」之后的场次; single=仅本次拉取
        if count_mode == "incremental":
            added = 0
            for m in pool_matches:
                key = str(m.get("gameId"))
                if key not in store:
                    added += 1
                store[key] = m          # 覆盖写入(补齐时间戳等新字段)
            # 「从现在开始统计」且战绩库原本为空(首次锚定):
            # 拉取后把起点设为刚拉到的库最新一把 game_creation(=上一把),
            # 之后新打的局以增量形式追加, 已拉取的历史不计入红包局统计。
            if stats_start == "now" and started_at is None:
                gcs = [int(m["game_creation"]) for m in store.values()
                       if m.get("game_creation")]
                started_at = max(gcs) if gcs else int(time.time() * 1000)
            save_match_store(started_at, store)
            matches = scope_matches(list(store.values()), started_at)
            me_names = sorted({m["me_name"] for m in matches
                               if m.get("me_name")}) or sorted(set(me_names_pool))
            new_count = added
            store_total = len(store)
        else:
            matches = pool_matches[:max(1, count)]
            # 缓存完整拉取池, 供「往前/往后一场」±1 切片(不重新联网)
            global _LAST_SINGLE_POOL
            _LAST_SINGLE_POOL = pool_matches
            me_names = sorted({m["me_name"] for m in matches
                               if m.get("me_name")})
            new_count = len(matches)
            store_total = len(matches)
        # 4) 对统计范围内的场次做红包局结算
        out = finalize(matches, me_names, unit, penta_unit,
                       party_names=party_names)
        out["party_info"] = party_info          # 出现次数按识别池计
        out["pool_size"] = len(pool_matches)    # 组队识别场数(识别池)
        out["new_count"] = new_count
        out["count_mode"] = count_mode
        out["started_at"] = started_at          # 统计起点(红包局)
        out["store_total"] = store_total        # 战绩库总场数(含起点前)
        save_settings(count=count, unit=unit, penta_unit=penta_unit,
                      threshold=min_games or 2, party_names=out["party_names"],
                      count_mode=count_mode)
        return {
            "mode": "remote",
            "puuid": puuid,
            "server": f"TENCENT_{rso}",
            "count_requested": count,
            **out,
        }
    except BaseException as e:
        return {"mode": "error", "error": f"{type(e).__name__}: {str(e)[:300]}"}


# ============================================================
# 战绩自定义: 往前往后加一场(±1 场调整统计范围)
# ============================================================
def adjust_range(mode: str, delta: int, count: int, started_at,
                 unit: float = 10.0, penta_unit: float = 20.0,
                 party_names: list = None, me_names: list = None) -> dict:
    """战绩自定义 ±1 场:
      - single(拉取全部战绩): 在已拉取池内按 count±1 重新切片并结算(不重新联网拉取)。
      - incremental(从现在开始统计): 把红包局统计起点按 ±1 场平移并结算(不重新拉取)。

    delta>0 = 往前一场(多看一场更早的对局, 统计范围向历史更早处扩展一场);
    delta<0 = 往后一场(少看一场最早的对局, 统计范围从最早处收缩一场)。
    """
    delta = 1 if delta > 0 else -1
    if mode == "single":
        pool = _LAST_SINGLE_POOL
        if not pool:
            return {"mode": "error", "error": "尚未拉取战绩, 请先点「拉取全部战绩」"}
        new_count = max(1, min(len(pool), int(count) + delta))
        matches = pool[:new_count]
        names = sorted({m["me_name"] for m in matches
                        if m.get("me_name")}) or (me_names or [])
        out = finalize(matches, names, unit, penta_unit,
                       party_names=party_names or None)
        out["mode"] = "adjust"
        out["count_requested"] = new_count
        out["count_mode"] = "single"
        out["started_at"] = None
        out["store_total"] = len(pool)
        out["pool_size"] = len(pool)
        out["new_count"] = new_count
        out["me_names"] = names
        out["party_info"] = None
        out["note"] = f"已调整为最近 {new_count} 场(共拉取 {len(pool)} 场可选)"
        return out
    else:  # incremental: 平移统计起点
        prev_started, store = load_match_store()
        if not store:
            return {"mode": "error", "error": "战绩库为空, 请先点「从现在开始统计」"}
        # 所有对局按 game_creation 降序(新->旧)
        all_m = sorted(store.values(),
                       key=lambda m: int(m.get("game_creation") or 0), reverse=True)
        if started_at is None:
            # 当前=全部累计: 往前无意义; 往后=去掉最旧一场
            if delta > 0:
                return {"mode": "error", "error": "已是全部累计, 无法再往前加场"}
            if len(all_m) <= 1:
                return {"mode": "error", "error": "仅剩 1 场, 无法再减少"}
            new_started = int(all_m[-1].get("game_creation") or 0) + 1
        else:
            cur = int(started_at)
            if delta > 0:
                # 往前: 把起点降到"比当前起点更旧的一场里最新的那场"
                older = [m for m in all_m if int(m.get("game_creation") or 0) < cur]
                if not older:
                    return {"mode": "error", "error": "已是战绩库最早一场, 无法再往前"}
                new_started = max(int(m.get("game_creation") or 0) for m in older)
            else:
                # 往后: 当前包含 game_creation>=cur 的场; 去掉最旧(起点)那场
                included = [m for m in all_m
                            if int(m.get("game_creation") or 0) >= cur]
                if len(included) <= 1:
                    return {"mode": "error", "error": "统计范围内仅剩 1 场, 无法再减少"}
                oldest_inc = min(int(m.get("game_creation") or 0) for m in included)
                new_started = oldest_inc + 1
        save_match_store(new_started, store)
        matches = scope_matches(list(store.values()), new_started)
        names = sorted({m["me_name"] for m in matches
                        if m.get("me_name")}) or (me_names or [])
        out = finalize(matches, names, unit, penta_unit,
                       party_names=party_names or None)
        out["mode"] = "adjust"
        out["count_mode"] = "incremental"
        out["started_at"] = new_started
        out["store_total"] = len(store)
        out["pool_size"] = len(_POOL["pool"]) if _POOL["pool"] else len(matches)
        out["new_count"] = len(matches)
        out["me_names"] = names
        out["party_info"] = None
        out["note"] = f"统计起点已调整: 现含 {len(matches)} 场"
        return out


# ============================================================
# 演示数据(无需客户端即可看界面)
# ============================================================
def sample_data() -> dict:
    """演示数据: 固定 5 人车队打 3 场大乱斗。
    组队 3 人: 阿伟 / 摸鱼怪 / 老K (面板默认名单即此三人, 3人组队→组内最后1名发红包)
    摸鱼怪每场评分垫底 -> 组内最后1名 -> 每场都要发红包 🧧
    """
    def P(name, k, a, d, dmg, tank, heal, shield, cc, tow, minion, champ=""):
        return dict(name=name, kills=k, assists=a, deaths=d, champion=champ,
                    dmg_to_champs=dmg, dmg_taken=tank, healing=heal,
                    shielding=shield, cc_seconds=cc, tower_dmg=tow, minion_dmg=minion)

    matches = []
    # 第1场(胜): 摸鱼怪高助攻刷KDA, 被反刷规则压分
    matches.append({"gameId": "SAMPLE-1", "champion": "Jinx",
                    "champion_cn": "暴走萝莉", "win": True, **score_team([
        P("阿伟",   12, 8, 4,  48000, 18000, 0,     0,     6,  3000, 9000, "Jinx"),
        P("摸鱼怪",  5, 14, 2,   9000,  4000, 0,     0,     1,   500, 1500, "Lux"),
        P("老K",     3, 10, 9,  22000, 42000, 0,     0,    18,  2000, 5000, "Leona"),
        P("软妹",    1, 16, 5,   6000, 12000, 18000, 14000, 22,   800, 2000, "Soraka"),
        P("大熊",    6,  9, 6,  25000, 20000, 2000,  1000,  8,   1500, 4000, "Garen"),
    ])})
    # 第2场(负): 摸鱼怪更躺
    matches.append({"gameId": "SAMPLE-2", "champion": "Jinx", "win": False, **score_team([
        P("阿伟",    8, 5, 7,  32000, 21000, 0,    0,     5,  2000, 6000, "Jinx"),
        P("摸鱼怪",  2, 8, 6,   6000,  5000, 0,    0,     1,   300, 1000, "Lux"),
        P("老K",     2, 9, 12, 18000, 48000, 0,    0,    22,  2500, 4000, "Leona"),
        P("软妹",    0, 12, 8, 5000, 14000, 15000, 12000, 25,   600, 1500, "Soraka"),
        P("大熊",    4, 7, 8,  20000, 26000, 1000, 500,   9,   1200, 3500, "Garen"),
    ])})
    # 第3场(胜): 老K开团carry, 摸鱼怪依旧垫底
    matches.append({"gameId": "SAMPLE-3", "champion": "Jinx", "win": True, **score_team([
        P("阿伟",   11, 9, 5,  44000, 17000, 0,    0,     7,  2800, 8000, "Jinx"),
        P("摸鱼怪",  4, 12, 7,  11000,  6000, 0,    0,     3,   400, 1200, "Lux"),
        P("老K",     5, 11, 7,  24000, 40000, 0,    0,    16,  3000, 5000, "Leona"),
        P("软妹",    2, 15, 6,  7000, 13000, 16000, 13000, 20,   700, 1800, "Soraka"),
        P("大熊",    7, 8, 5,  27000, 22000, 1000, 800,  10,   1600, 4500, "Garen"),
    ])})
    return {"mode": "sample", "puuid": "demo", "server": "DEMO",
            "count_requested": len(matches), "matches": matches}


# ============================================================
# Web 服务
# ============================================================
class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body: bytes, ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        try:
            self._do_get()
        except BaseException as e:
            self._send(200, json.dumps(
                {"mode": "error", "error": f"{type(e).__name__}: {str(e)[:300]}"},
                ensure_ascii=False).encode("utf-8"))

    def _do_get(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            html = Path(resource_path("index.html")).read_text(encoding="utf-8")
            html = html.replace("<!--APP_VERSION-->", APP_VERSION)
            self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
            return
        if parsed.path.startswith("/vendor/"):
            rel = parsed.path[len("/vendor/"):]
            # 防目录穿越: 只允许 vendor 下一级文件
            if "/" in rel or "\\" in rel or not rel:
                self._send(404, b'{"error":"not found"}')
                return
            fp = resource_path(os.path.join("vendor", rel))
            if not os.path.exists(fp):
                self._send(404, b'{"error":"not found"}')
                return
            ctype = "application/javascript; charset=utf-8" if rel.endswith(".js") \
                else "application/octet-stream"
            self._send(200, Path(fp).read_bytes(), ctype)
            return
        if parsed.path == "/api/sample":
            self._send(200, json.dumps(sample_data(), ensure_ascii=False).encode("utf-8"))
            return
        if parsed.path == "/api/live":
            # 桌面常驻程序的对局结束广播(Web 面板据此自动刷新)
            self._send(200, json.dumps(live_state(),
                                       ensure_ascii=False).encode("utf-8"))
            return
        if parsed.path == "/api/settings":
            self._send(200, json.dumps(load_settings(),
                                       ensure_ascii=False).encode("utf-8"))
            return
        if parsed.path == "/api/fetch":
            qs = urllib.parse.parse_qs(parsed.query)
            count = int(qs.get("count", ["20"])[0])
            unit = float(qs.get("unit", ["10"])[0])
            penta_unit = float(qs.get("penta_unit", ["20"])[0])
            threshold = qs.get("threshold", [None])[0]
            min_games = int(float(threshold)) if threshold not in (None, "") else None
            count_mode = qs.get("count_mode", ["single"])[0]
            if count_mode not in ("incremental", "single"):
                count_mode = "single"
            stats_start = qs.get("stats_start", [None])[0]
            if stats_start not in ("now", "reset"):
                stats_start = None
            self._send(200, json.dumps(
                run_remote(count, unit, penta_unit, min_games, count_mode,
                           stats_start),
                ensure_ascii=False).encode("utf-8"))
            return
        self._send(404, b'{"error":"not found"}')

    def do_POST(self):
        try:
            self._do_post()
        except BaseException as e:
            self._send(200, json.dumps(
                {"mode": "error", "error": f"{type(e).__name__}: {str(e)[:300]}"},
                ensure_ascii=False).encode("utf-8"))

    def _do_post(self):
        if self.path == "/api/redpacket":
            # 红包局/五杀赏金重算。组队名单来源优先级:
            #   1) 带 threshold 且有 100 场识别池缓存 -> 按新阈值重新识别好友
            #   2) 带 party(手动添加/删除后的名单)      -> 直接使用该名单
            #   3) 带 me_names                          -> 在已拉取场次里识别(兜底)
            #   4) 都没有                               -> 保留标注仅重算五杀与金额
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8"))
                matches = payload.get("matches", []) or []
                me_names = payload.get("me_names", []) or []
                unit = float(payload.get("unit", 10) or 10)
                penta_unit = float(payload.get("penta_unit", 20) or 20)
                threshold = payload.get("threshold")
                party = payload.get("party") or []
                # 红包局统计起点调整: now=从现在开始记账 / reset=统计全部。
                # 只改统计范围(读战绩库重算), 不重新拉取, 不影响组队识别。
                stats_start = payload.get("stats_start")
                started_at = payload.get("started_at")
                store_total = None
                if stats_start in ("now", "reset"):
                    prev_started, store = load_match_store()
                    if stats_start == "reset":
                        started_at = None
                    else:  # now: 锚定到上一把(战绩库最新一把的 game_creation)
                        gcs = [int(m["game_creation"]) for m in store.values()
                               if m.get("game_creation")]
                        started_at = max(gcs) if gcs else int(time.time() * 1000)
                    save_match_store(started_at, store)
                    matches = scope_matches(list(store.values()), started_at)
                    me_names = sorted({m["me_name"] for m in matches
                                       if m.get("me_name")})
                    store_total = len(store)

                party_names, party_info = None, None
                # 手动增删名单(前端持久维护, 全量上报): 添加 ∪ 识别 − 移除黑名单
                manual_add = [str(n).strip() for n in (payload.get("manual_add") or [])
                              if str(n).strip()]
                manual_removed = {str(n).strip()
                                  for n in (payload.get("manual_removed") or [])}
                if threshold is not None and _POOL["pool"]:
                    info = detect_party(_POOL["pool"], int(float(threshold)))
                    party_names = merge_party_names(
                        _POOL["me_names"], info,
                        manual_add, manual_removed)
                    party_info = info
                elif party:
                    party_names = [str(n).strip() for n in party if str(n).strip()]

                if stats_start in ("now", "reset"):
                    # 起点调整: 用战绩库范围 + 现有组队名单整体重算
                    out = finalize(matches, me_names, unit, penta_unit,
                                   party_names=party_names or None)
                    out["started_at"] = started_at
                    out["store_total"] = store_total
                    out["new_count"] = 0
                    out["count_mode"] = "incremental"
                    out["pool_size"] = len(_POOL["pool"])
                elif party_names is not None:
                    for m in matches:
                        apply_red_packet(m, party_names)
                        apply_penta_bounty(m, penta_unit)
                    out = {
                        "unit": unit, "penta_unit": penta_unit,
                        "me_names": payload.get("me_names", []),
                        "party_names": party_names,
                        "party_info": party_info,
                        "matches": matches,
                        "stats": aggregate_stats(matches, unit, penta_unit),
                    }
                elif me_names:
                    out = finalize(matches, me_names, unit, penta_unit)
                else:
                    for m in matches:
                        apply_penta_bounty(m, penta_unit)
                    out = {
                        "unit": unit, "penta_unit": penta_unit,
                        "me_names": [], "party_names": [],
                        "party_info": [], "matches": matches,
                        "stats": aggregate_stats(matches, unit, penta_unit),
                    }
                self._send(200, json.dumps({
                    "mode": payload.get("mode", "ok"),
                    "server": payload.get("server"),
                    **out,
                }, ensure_ascii=False).encode("utf-8"))
                # 持久化本次参数; 手动增删名单仅在请求带上时才写入
                _kv = {"unit": unit, "penta_unit": penta_unit,
                       "party_names": out.get("party_names") or []}
                if threshold is not None:
                    _kv["threshold"] = int(float(threshold))
                if "manual_add" in payload:
                    _kv["party_manual_add"] = manual_add
                if "manual_removed" in payload:
                    _kv["party_removed"] = sorted(manual_removed)
                save_settings(**_kv)
            except Exception as e:
                self._send(200, json.dumps(
                    {"mode": "error", "error": "红包规则处理失败: " + str(e)[:300]},
                    ensure_ascii=False).encode("utf-8"))
            return
        if self.path == "/api/adjust":
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8"))
                mode = payload.get("mode") or "single"
                if mode not in ("incremental", "single"):
                    mode = "single"
                delta = int(payload.get("delta") or 0)
                if delta == 0:
                    self._send(200, json.dumps(
                        {"mode": "error", "error": "delta 必须为 +1 或 -1"},
                        ensure_ascii=False).encode("utf-8"))
                    return
                count = int(payload.get("count") or 50)
                unit = float(payload.get("unit", 10) or 10)
                penta_unit = float(payload.get("penta_unit", 20) or 20)
                party_names = [str(n).strip() for n in (payload.get("party_names") or [])
                               if str(n).strip()]
                me_names = [str(n).strip() for n in (payload.get("me_names") or [])]
                out = adjust_range(mode, delta, count, payload.get("started_at"),
                                   unit, penta_unit, party_names or None,
                                   me_names or None)
                self._send(200, json.dumps(
                    {**out, "server": payload.get("server")},
                    ensure_ascii=False).encode("utf-8"))
            except Exception as e:
                self._send(200, json.dumps(
                    {"mode": "error", "error": "调整范围失败: " + str(e)[:300]},
                    ensure_ascii=False).encode("utf-8"))
            return
        if self.path == "/api/import":
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"[]"
            try:
                payload = json.loads(raw.decode("utf-8"))
                matches = []
                for m in payload.get("matches", payload if isinstance(payload, list) else []):
                    team = m.get("players", [])
                    if not team:
                        continue
                    sc = score_team(team, m.get("puuid"))
                    matches.append({
                        "gameId": m.get("gameId", "IMPORT"),
                        "champion": m.get("champion"),
                        "win": m.get("win"),
                        "players": sc["players"],
                        "me_name": sc["me_name"],
                    })
                self._send(200, json.dumps({"mode": "import", "matches": matches},
                                           ensure_ascii=False).encode("utf-8"))
            except Exception as e:
                self._send(200, json.dumps({"mode": "error", "error": "导入JSON解析失败: " + str(e)[:300]},
                                           ensure_ascii=False).encode("utf-8"))
            return
        self._send(404, b'{"error":"not found"}')

    def log_message(self, *a):
        pass


def make_server(port=None):
    """创建并返回 (HTTPServer, port)。供桌面常驻程序在子线程内嵌战绩面板。"""
    p = int(port) if port else PORT
    return HTTPServer(("127.0.0.1", p), Handler), p


def serve_forever(port=None, open_browser=True):
    """启动战绩面板服务。open_browser=False 时只起服务不开浏览器
    (由调用方程序自行决定何时打开主界面)。"""
    srv, p = make_server(port)
    url = f"http://127.0.0.1:{p}"
    print("=" * 56)
    print("  红包乱斗  (已打包为独立程序)")
    print("=" * 56)
    print(f"  评分面板已尝试在浏览器打开: {url}")
    print("  若未自动打开, 请手动访问上面的地址。")
    print("  点页面上的「拉取战绩」需: 本机已登录英雄联盟客户端,")
    print("  国服建议开启加速器; 否则可直接看「示例数据」。")
    print("  关闭本窗口即可退出程序。")
    print("=" * 56)
    if open_browser:
        # 延迟 1.2s 等服务器起来再开浏览器
        threading.Timer(1.2, lambda: _safe_open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
        srv.shutdown()


def main():
    serve_forever()


def _safe_open(url: str):
    try:
        webbrowser.open(url)
    except Exception:
        pass


if __name__ == "__main__":
    main()
