# -*- coding: utf-8 -*-
"""
ARAM 反刷KDA 评分框架 —— 基于 LeagueAkari 的国服战绩读取机制
=================================================================

LeagueAkari 在国服读取战绩的真实链路(已从 v1.5.1 源码逆向确认):
  1. 本地 LCU 客户端(/entitlements/v1/token) 拿到 Riot 签发的 entitlements JWT
  2. 解码 JWT 的 sub 声明 = 当前账号 puuid
  3. 从 LeagueAkari 配置(lastConnectedClient.rsoPlatformId) 得到区服,
     拼出 SGP 服务器子标识 TENCENT_<rsoPlatformId>(如黑色玫瑰=HN10 -> TENCENT_HN10)
  4. 用 Bearer entitlements 令牌, 请求远程 Riot SGP:
        GET https://<platform>.api.riotgames.com
            /match-history-query/v1/products/lol/player/<puuid>/SUMMARY
        -> 得到对局 gameId 列表
        GET https://<platform>.api.riotgames.com
            /match-history-query/v1/products/lol/<TENCENT_HN10>_<gameId>/DETAILS
        -> 得到单场 10 人完整 stats
  5. 把 stats 喂入本评分系统(aram_score_system.compute), 输出防刷KDA评分 + S~D 评级

注意: 第4步是跨网请求(注释里 LeagueAkari 也提示"跨国需加速器")。
       若本机网络到 Riot SGP 不通, 框架会自动回退到读取
       LeagueAkari 本地缓存库 LeagueAkari.db(当你在 Akari 里打开过战绩后即被填充)。

用法:
    python aran_akari_framework.py [最近N场, 默认20]
依赖: requests  (已装在隔离 venv)
"""

import os
import sys
import json
import base64
import sqlite3
import urllib3
import requests
from pathlib import Path

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from aram_score_system import Player, compute  # 本规则评分内核

QUEUE_ARAM = 450
# 大乱斗队列 ID: 标准服=450; 国服(腾讯)大乱斗=2400
ARAM_QUEUE_IDS = {450, 2400}

# 国服(腾讯) 各区的真实 SGP host —— 逆向自 LeagueAkari v1.5.1 的 servers 映射表
# (main.js: TENCENT_HN10:{matchHistory:`https://hn10-k8s-sgp.lol.qq.com:21019`,...})
TENCENT_SGP_HOSTS = {
    "TENCENT_HN1":   "https://hn1-k8s-sgp.lol.qq.com:21019",
    "TENCENT_HN10":  "https://hn10-k8s-sgp.lol.qq.com:21019",
    "TENCENT_TJ100": "https://tj100-sgp.lol.qq.com:21019",
    "TENCENT_TJ101": "https://tj101-sgp.lol.qq.com:21019",
    "TENCENT_NJ100": "https://nj100-sgp.lol.qq.com:21019",
    "TENCENT_GZ100": "https://gz100-sgp.lol.qq.com:21019",
    "TENCENT_CQ100": "https://cq100-sgp.lol.qq.com:21019",
    "TENCENT_BGP2":  "https://bgp2-k8s-sgp.lol.qq.com:21019",
    "TENCENT_PBE":   "https://pbe-sgp.lol.qq.com:21019",
    "TENCENT_PREPBE": "https://prepbe-sgp.lol.qq.com:21019",
}


# ============================================================
# 1) LCU / Akari 本地鉴权
# ============================================================
def find_lockfile() -> str:
    """定位国服/直营服客户端 lockfile(含 Z 盘国服路径)."""
    candidates = [
        os.path.expandvars(r"%LOCALAPPDATA%\Riot Games\Riot Client\Config\lockfile"),
        os.path.expandvars(r"%APPDATA%\Riot Games\Riot Client\Config\lockfile"),
        r"C:\ProgramData\Riot Games\Riot Client\Config\lockfile",
    ]
    for drive in ("C", "D", "E", "F", "Z"):
        candidates += [
            rf"{drive}:\网络游戏\英雄联盟\Riot Client Data\User Data\Config\lockfile",
            rf"{drive}:\网络游戏\英雄联盟\Riot Client\Config\lockfile",
            rf"{drive}:\Riot Games\Riot Client\Config\lockfile",
            rf"{drive}:\英雄联盟\Riot Client Data\User Data\Config\lockfile",
        ]
    if os.getenv("LOCKFILE_PATH"):
        candidates.insert(0, os.getenv("LOCKFILE_PATH"))
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return None


def read_league_akari_config():
    """读取 LeagueAkari 本地库, 取出 rsoPlatformId / region / 端口 / 令牌.
    返回 dict 或 None."""
    db = os.path.expandvars(
        r"%APPDATA%\league-akari\LeagueAkari.db")
    if not os.path.exists(db):
        return None
    try:
        con = sqlite3.connect(db)
        row = con.execute(
            "SELECT value FROM Settings WHERE key='league-client-main/lastConnectedClient'"
        ).fetchone()
        con.close()
        if not row:
            return None
        return json.loads(row[0])
    except Exception:
        return None


def lcu_auth():
    """返回 (base_url, session) 用于访问本地 LCU; 并尽量从 Akari 配置回退."""
    lf = find_lockfile()
    port, pw = None, None
    if lf:
        text = Path(lf).read_text(encoding="utf-8", errors="ignore").strip()
        parts = text.split(":")
        port, pw = int(parts[2]), parts[3]
    # Akari 配置里的 riotClientPort / riotClientAuthToken 也是等效凭据
    cfg = read_league_akari_config()
    if cfg:
        port = port or cfg.get("riotClientPort")
        pw = pw or cfg.get("riotClientAuthToken")
    if not port or not pw:
        raise RuntimeError("找不到 LCU 凭据。请确认英雄联盟客户端已登录运行。")
    base = f"https://127.0.0.1:{port}"
    s = requests.Session()
    s.headers.update({"Authorization": "Basic " +
                      base64.b64encode(f"riot:{pw}".encode()).decode()})
    s.verify = False
    return base, s, cfg


def get_entitlements(lcu_base, lcu_s):
    """国服可用: 本地 LCU 返回 200, JWT 里 sub=puuid."""
    r = lcu_s.get(lcu_base + "/entitlements/v1/token", timeout=12)
    r.raise_for_status()
    j = r.json()
    # 本地 LCU 返回顶层 accessToken 即 Bearer 令牌(Akari 内部即取此字段)
    token = j.get("accessToken") or j.get("token") or j.get("entitlements_token")
    if not token:
        raise RuntimeError("❌ 无法获取 entitlements 令牌")
    # 解码 JWT payload 取 puuid
    seg = token.split(".")[1]
    seg += "=" * (-len(seg) % 4)
    payload = json.loads(base64.urlsafe_b64decode(seg))
    puuid = payload.get("sub")
    return token, puuid


# ============================================================
# 2) 远程 SGP 战绩拉取(LeagueAkari 同款)
# ============================================================
class SgpFetcher:
    def __init__(self, entitlements_token, rso_platform_id, region):
        self.token = entitlements_token
        self.region = region                     # 如 TENCENT
        self.platform = (rso_platform_id or "HN10").lower()   # 如 hn10
        # SGP 服务器子标识(用于 x-akari-sgp-server-id 头 与 DETAILS 路径)
        self.sgp_sub_id = f"TENCENT_{rso_platform_id}" if region.upper() == "TENCENT" \
            else rso_platform_id
        # 真实 SGP host: 国服用逆向得到的腾讯域名映射, 其余回退 Riot 直营服
        self.host = TENCENT_SGP_HOSTS.get(
            self.sgp_sub_id, f"https://{self.platform}.api.riotgames.com")
        self.s = requests.Session()
        self.s.verify = False
        self._puuid = None   # 由 set_puuid() 注入, get_aram_details 定位"我"用

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.token}",
            "x-akari-sgp-server-id": self.sgp_sub_id,
            "x-akari-token-type": "entitlements",
        }

    def get_summary(self, puuid, count=20, start_index=0):
        url = (f"{self.host}/match-history-query/v1/products/lol/player/"
               f"{puuid}/SUMMARY?startIndex={start_index}&count={count}")
        r = self.s.get(url, headers=self._headers(), timeout=20)
        r.raise_for_status()
        return r.json()

    def get_details(self, game_id):
        """单场 DETAILS。

        注意(2026-10-05 实测修正): 腾讯 SGP 的 DETAILS 路径用
        **rsoPlatformId 而不是 TENCENT_ 前缀**, 即 `HN10_<gameId>/DETAILS`。
        之前拼成 `TENCENT_HN10_<gameId>/DETAILS` 会恒定 404, 导致弹窗拿不到数据。
        另外该接口返回的是 data_version=2 的精简结构(participants 只有 puuid,
        真实数值在 frames 里), **不适合直接算分** —— 算分请用 SUMMARY 里的
        participants(已含完整 kills/deaths/assists/伤害等), 见 get_aram_details。
        """
        url = (f"{self.host}/match-history-query/v1/products/lol/"
               f"{self.platform.upper()}_{game_id}/DETAILS")
        r = self.s.get(url, headers=self._headers(), timeout=20)
        r.raise_for_status()
        return r.json()

    def get_aram_details(self, game_id, timeout=20):
        """**推荐**: 取单场大乱斗的"可算分"数据(走 SUMMARY, 绕开 DETAILS 缺陷)。

        返回 {"gameId","participants","game_creation","champion","win"}，
        participants 是 10 人完整统计, 可直接喂给 aram_web.score_team /
        match_view.build_match_view。查不到返回 None。
        """
        summary = self.get_summary_by_gameid(game_id, timeout=timeout)
        if not summary:
            return None
        j = summary
        parts = j.get("participants") or []
        if len(parts) < 10:
            return None
        me = next((p for p in parts if p.get("puuid") == self._puuid), None)
        if me is None:
            return None
        qid = j.get("queueId")
        # 重要: 腾讯 SGP 的 queueId 在**对局节点**上, participants 里没有该字段。
        # 而 match_view/评分内核按 participants[0].queueId 判定是否大乱斗,
        # 因此这里把 queueId 补进每个 participant, 否则会被误判为"非大乱斗"。
        if qid is not None:
            for p in parts:
                if p.get("queueId") is None:
                    p["queueId"] = qid
        return {
            "gameId": j.get("gameId") or game_id,
            "participants": parts,
            "game_creation": (j.get("gameCreation")
                              or j.get("gameStartTimestamp")
                              or j.get("gameEndTimestamp")),
            "champion": me.get("championName"),
            "win": bool(me.get("win")),
            "queueId": qid,
        }

    def set_puuid(self, puuid):
        """记录当前账号 puuid(get_aram_details 定位"我"用)。"""
        self._puuid = puuid
        return self

    def get_summary_by_gameid(self, game_id, max_pages=3, page=20, timeout=20):
        """翻 SUMMARY 列表直到找到指定 gameId, 返回其 json 节点(找不到 None)。

        比 DETAILS 可靠: SUMMARY 的 participants 自带完整统计, 且路径格式稳定。
        """
        if not game_id:
            return None
        gid = str(game_id)
        index = 0
        for _ in range(max_pages):
            try:
                summary = self.get_summary(self._puuid, page, start_index=index)
            except Exception:
                return None
            games = summary.get("games", [])
            if isinstance(games, dict):
                games = games.get("games", [])
            if not games:
                return None
            for g in games:
                j = g.get("json") if isinstance(g, dict) else None
                if j and str(j.get("gameId")) == gid:
                    return j
            if len(games) < page:
                break
            index += page
        return None


# ============================================================
# 2.5) 解析 SGP SUMMARY: 筛 ARAM + 提取 participants
# ============================================================
def parse_sgp_summary(summary: dict, puuid: str) -> list:
    """从腾讯 SGP 的 SUMMARY 响应里筛出 ARAM(450)场次。
    腾讯 SGP 结构: summary.games = [{'metadata':..., 'json':{...含 participants}}]
    返回 [{'game_id','champion','win','participants'}, ...]"""
    games = summary.get("games", [])
    if isinstance(games, dict):
        games = games.get("games", [])
    out = []
    for g in games:
        j = g.get("json") if isinstance(g, dict) else None
        if not j:
            continue
        if j.get("queueId") not in ARAM_QUEUE_IDS:
            continue
        parts = j.get("participants", [])
        if not parts or not any(p.get("puuid") == puuid for p in parts):
            continue
        me = next(p for p in parts if p.get("puuid") == puuid)
        out.append({
            "game_id": j.get("gameId"),
            "champion": me.get("championName"),
            "win": bool(me.get("win")),
            # 对局开始时间(毫秒时间戳): 用于「红包局统计起点」判定,
            # 与组队识别无关 —— 识别只看共同场次, 统计只看时间起点
            "game_creation": (j.get("gameCreation")
                              or j.get("gameStartTimestamp")
                              or j.get("gameDateTimestamp")),
            "participants": parts,
        })
    return out


def fetch_aram_matches(fetcher, puuid, count=20, page=20, stop_gids=None):
    """分页拉取 SGP, 直到凑够 count 场大乱斗(2400/450)或拉完所有战绩。

    stop_gids: 已入库的 gameId 字符串集合(增量模式用)。连续 2 页的全部
    对局都已在库中时提前停止翻页 —— 用于"补齐上次拉取以来新打的所有
    场次", 不受固定场数限制。连续 2 页(而非 1 页)是为了容忍页面边界
    与历史记录里偶发的空洞, 避免过早停止漏拉新对局。
    """
    collected, seen, index = [], set(), 0
    known_pages = 0
    while len(collected) < count:
        summary = fetcher.get_summary(puuid, page, start_index=index)
        games = summary.get("games", [])
        if isinstance(games, dict):
            games = games.get("games", [])
        if not games:
            break
        for m in parse_sgp_summary(summary, puuid):
            if m["game_id"] not in seen:
                seen.add(m["game_id"])
                collected.append(m)
        # 增量提前停止: 连续 2 页所有对局都已入库 -> 之后全是旧对局
        # (gameId 在腾讯 SGP 的 json 包装层; stop_gids 为字符串集合)
        if stop_gids is not None and collected:
            page_gids = [g.get("json", {}).get("gameId")
                         for g in games if isinstance(g, dict)]
            if page_gids and all(str(gid) in stop_gids for gid in page_gids):
                known_pages += 1
                if known_pages >= 2:
                    break
            else:
                known_pages = 0
        if len(games) < page:
            break
        index += page
    return collected[:count]


# ============================================================
# 2.6) 对局结束检测: SGP 战绩轮询(借鉴 LeagueAkari 的做法)
# ============================================================
def latest_aram_gameid(fetcher, puuid, timeout=20):
    """返回最近一场大乱斗的 gameId(字符串); 没有则 None。

    LeagueAkari 判断"又打了一把"的可靠方式不是看 gameflow phase,
    而是**轮询 SGP 战绩列表并与上一次比对** —— 战绩一旦多出新的一局,
    就说明上一局已结束并入库。本函数取列表首局(最新)的 gameId。
    """
    summary = fetcher.get_summary(puuid, 1, start_index=0)
    games = summary.get("games", [])
    if isinstance(games, dict):
        games = games.get("games", [])
    for g in games:
        j = g.get("json") if isinstance(g, dict) else None
        if not j:
            continue
        if j.get("queueId") not in ARAM_QUEUE_IDS:
            continue
        parts = j.get("participants", []) or []
        if parts and not any(p.get("puuid") == puuid for p in parts):
            continue
        gid = j.get("gameId")
        if gid:
            return str(gid)
    return None


# ============================================================
# 3) 本地缓存回退: 读取 LeagueAkari.db 的 EncounteredGames
# ============================================================
def load_cached_games():
    """LeagueAkari 打开过战绩后, EncounteredGames 表会被填充。
    返回 gameId 列表(本框架仅作离线回退, 不参与评分解析)。"""
    db = os.path.expandvars(r"%APPDATA%\league-akari\LeagueAkari.db")
    if not os.path.exists(db):
        return []
    try:
        con = sqlite3.connect(db)
        rows = con.execute(
            "SELECT gameId, queueType FROM EncounteredGames").fetchall()
        con.close()
        return [g for g, q in rows if q in (None, "ARAM", "450") or "aram" in str(q).lower()]
    except Exception:
        return []


# ============================================================
# 4) 战绩 -> 本系统 Player 模型
# ============================================================
def player_from_participant(p: dict) -> Player:
    return Player(
        name=f"{p.get('championName','?')}#{p.get('riotIdGameName') or p.get('summonerName') or '?'}",
        kills=p.get("kills", 0),
        assists=p.get("assists", 0),
        deaths=p.get("deaths", 0),
        dmg_to_champs=p.get("totalDamageDealtToChampions", 0),
        dmg_taken=p.get("totalDamageTaken", 0),
        healing=p.get("totalHeal", 0),
        shielding=p.get("totalDamageShieldedOnTeammates", 0),
        cc_seconds=float(p.get("timeCCingOthers", 0)),
        tower_dmg=p.get("damageDealtToObjectives", 0),
        minion_dmg=0,
    )


def main():
    print("== ARAM 反刷KDA 评分框架 (基于 LeagueAkari 国服读取机制) ==")
    lcu_base, lcu_s, cfg = lcu_auth()
    print(f"[1] LCU 鉴权 OK (端口 {lcu_base.split(':')[-1]})")

    token, puuid = get_entitlements(lcu_base, lcu_s)
    print(f"[2] entitlements 令牌 OK, puuid={puuid[:8]}...")

    # 区服信息: 优先 Akari 配置, 否则默认黑色玫瑰
    rso = (cfg or {}).get("rsoPlatformId", "HN10")
    region = (cfg or {}).get("region", "TENCENT")
    print(f"[3] 区服: region={region} rsoPlatformId={rso} -> SGP子标识=TENCENT_{rso}")

    count = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    fetcher = SgpFetcher(token, rso, region)

    # ---- 尝试远程 SGP ----
    try:
        print(f"[4] 远程 SGP 拉取最近 {count} 场战绩摘要 ...")
        matches = fetch_aram_matches(fetcher, puuid, count)
        print(f"    拉取并筛出大乱斗 {len(matches)} 场")
        rows = []
        for m in matches:
            parts = m["participants"]
            me = next((p for p in parts if p.get("puuid") == puuid), None)
            team = [p for p in parts if p.get("teamId") == me.get("teamId")]
            res = compute([player_from_participant(p) for p in team])
            tname = next((r["name"] for r in res if puuid in str(r)), res[0]["name"])
            trow = next((r for r in res if r["name"] == tname), res[0])
            rows.append((m["champion"], m["win"], trow))
            note = "  ⚠" + ",".join(trow["reasons"]) if trow["reasons"] else ""
            print(f"    {m['champion']:<12} {'胜' if m['win'] else '负'} "
                  f"KDA {trow['kda']:>5} 评分 {trow['new_score']:>5} 评级 {trow['grade']}{note}")
        if rows:
            avg = sum(r[2]["new_score"] for r in rows) / len(rows)
            wins = sum(1 for r in rows if r[1])
            print("-" * 64)
            print(f"共 {len(rows)} 场 ARAM | 胜率 {wins}/{len(rows)} | 平均评分 {avg:.1f}")
        return
    except Exception as e:
        print(f"    ⚠ 远程 SGP 失败: {type(e).__name__}: {str(e)[:160]}")
        print("    可能是本机网络无法直连 SGP 或被沙箱代理拦截。")

    # ---- 回退: 本地 Akari 缓存 ----
    cached = load_cached_games()
    if cached:
        print(f"[回退] 读取到 LeagueAkari 本地缓存 {len(cached)} 场, "
              f"但需 Akari 已缓存完整 stats 才能解析评分。")
    else:
        print("[回退] LeagueAkari.db 暂无缓存战绩。请在 LeagueAkari 中打开一次"
              "战绩面板(或在本机(非沙箱)运行本脚本以直连 Riot SGP)。")


if __name__ == "__main__":
    main()
