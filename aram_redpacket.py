# -*- coding: utf-8 -*-
"""
大乱斗红包局规则框架
====================
在反刷KDA评分之上叠加"红包局"玩法规则:

组队识别(按玩家名匹配, 支持精确/包含):
    面板填入组队成员名单, 每场自动匹配出组队成员与组队人数 N。

红包规则(组内按"新评分"从高到低排名):
    N=3  -> 组内最后 1 名发红包
    N=4  -> 组内最后 2 名发红包
    N=5  -> 组内最后 2 名发红包
    N=2 或散人 -> 不触发红包(仅标注组队成员)
    红包由组内第 1、2 名拆"随机金额", 因此评分红包只统计发出
    (次数 x 单价), 收入金额随机、不计入榜单。

五杀赏金规则:
    组队成员拿到五杀(pentaKills>0) -> 其余组队队友每人给五杀者
    发一个赏金红包; 五杀 x2 则触发两次(每人发两份)。
    非组队成员的五杀不触发赏金。

统计系统(aggregate_stats):
    按玩家聚合: 场数 / 胜率 / 场均分 / 组队场数 / 红包次数 /
    五杀次数 / 赏金收付 / 应发总额。
"""

from typing import List, Optional

# 组队人数 -> 发红包的人数(组内评分"最后"的 N 名, 1 = 组内评分最高)
#   3人局: 最后 1 名发红包;  4/5人局: 最后 2 名发红包
RED_PACKET_RULES = {3: 1, 4: 2, 5: 2}

RULE_HINT = ("红包规则: 组队3人→组内最后1名发 · 组队4/5人→组内最后2名发 · 按组内新评分排名\n"
             "      红包由组内前1、2名拆随机金额(收入随机, 不计入榜单)\n"
             "五杀赏金: 组队成员五杀 → 其余组队队友每人发赏金(每个五杀触发一次)")

# 自动识别组队的门槛: 与"我"共同游戏 >= N 场即列为队友候选。
# 策略: 宁多勿漏 —— 候选可能混入偶尔同局的路人, 在面板点 ✕ 手动删除即可。
# 说明: Riot 新版战绩接口(SGP match-history-query)的单场数据里没有
# 组队(party)标记 —— wasPremadeWith* 是挂机/演员惩罚标记,
# playerSubteamId 是公会战(Clash)字段, 都不是开黑组队数据。
# 因此"队友共同出现场次"是从历史战绩识别固定开黑的最可靠依据
# (大乱斗玩家池数千人, 纯路人重复匹配概率趋近 0)。
DETECT_MIN_GAMES = 2   # 共同游戏 >= 2 场即视为队友(面板可调 2/3/4 场)
DETECT_MAX_PARTY = 8   # 候选上限(按共同场数降序), 误识别的在面板手动删除


def detect_party(matches: List[dict], min_games: int = None) -> List[dict]:
    """根据拉取的多场战绩自动识别固定组队(开黑)队友。

    原理: 逐场统计"我"的队友出现次数 —— 与我共同游戏 >= min_games
    场的玩家列为队友候选(默认 2 场, 宁多勿漏, 误识别可手动删除)。

    返回: [{'name': 名字, 'count': 共同场次, 'rate': 出现率%}, ...]
          按共同场次降序, 最多 DETECT_MAX_PARTY 人。
    """
    n = len(matches)
    if n < 2:
        return []
    mg = int(min_games) if min_games else DETECT_MIN_GAMES
    mg = max(1, mg)
    counter: dict = {}
    for m in matches:
        me = m.get("me_name")
        seen = set()
        for p in (m.get("players") or []):
            name = p.get("name")
            if not name or name == me or name in seen:
                continue
            seen.add(name)
            counter[name] = counter.get(name, 0) + 1
    info = [{"name": k, "count": v, "rate": round(v / n * 100)}
            for k, v in counter.items() if v >= mg]
    info.sort(key=lambda x: -x["count"])
    return info[:DETECT_MAX_PARTY]


def find_party(players: List[dict], party_names: List[str]):
    """在一场比赛的玩家列表中匹配组队成员。

    匹配规则: 名单名与玩家名"完全相等"才计入(严谨优先)。
    自动识别的名单来自战绩中的真实玩家名, 手动添加也应输入完整名字;
    不做包含匹配 —— 否则"老K"会误匹配路人"老K丶xx", 导致组队人数
    虚增、红包多算。好友改名后请在面板删除旧名并添加新名。

    返回: (匹配到的玩家 dict 列表, 组队人数)
    """
    matched: List[dict] = []
    if not party_names:
        return matched, 0
    names = {str(p.get("name", "")): p for p in players}
    for pn in party_names:
        pn = str(pn).strip()
        if not pn:
            continue
        p = names.get(pn)
        if p is not None and p not in matched:
            matched.append(p)
    return matched, len(matched)


def apply_red_packet(match: dict, party_names: List[str]) -> dict:
    """对单场比赛应用红包规则, 就地标注并返回 match。

    玩家级标注:
        party_member: bool  是否组队成员
        party_rank:   int|None  组内新评分名次(1最高)
        red_packet:   bool  是否需要发红包
    比赛级标注:
        party_size:         组队人数
        party_payers:       本场发红包的玩家名列表
    """
    players = match.get("players", []) or []
    matched, size = find_party(players, party_names)

    for p in players:
        p["party_member"] = p in matched
        p["party_rank"] = None
        p["red_packet"] = False

    match["party_size"] = size
    # 候选过多导致匹配数 >5 时, 仍按 5 人规则取最后 2 名(游戏内组队上限5人)
    n_pay = RED_PACKET_RULES.get(size) or (2 if size > 5 else 0)
    payers: List[str] = []

    if n_pay:
        ranked = sorted(matched, key=lambda x: -x.get("new_score", 0))
        for i, p in enumerate(ranked, 1):
            # 发红包者 = 组内评分最后的 n_pay 名(倒数第 n_pay 名及以后)
            p["party_rank"] = i
            p["red_packet"] = i > len(ranked) - n_pay
            if p["red_packet"]:
                payers.append(p.get("name", "?"))

    match["party_payers"] = payers
    return match


def apply_penta_bounty(match: dict, penta_unit: float = 20.0) -> dict:
    """对单场比赛应用五杀赏金规则, 就地标注并返回 match。

    规则: 组队成员拿到五杀(penta_kills>0) -> 其余组队队友每人给
    五杀者发 penta_unit 元赏金; 五杀 x2 触发两次; 非组队成员
    的五杀不触发。

    依赖: 需先跑 apply_red_packet(提供 party_member 标注)。
    玩家级标注:
        penta_holds: int   该场五杀次数(组队成员才有意义)
        penta_pays:  int   该场需支付的五杀赏金份数
    比赛级标注:
        penta_events: [{'holder':名, 'count':五杀次数,
                        'payers':[名...], 'amount':本场赏金总额}]
    """
    players = match.get("players", []) or []
    for p in players:
        p["penta_holds"] = 0          # 每次重算先清零, 防止上次标注残留导致重复
        p["penta_pays"] = 0
    match["penta_events"] = []

    party = [p for p in players if p.get("party_member")]
    if len(party) < 2 or float(penta_unit or 0) <= 0:
        return match

    events: List[dict] = []
    for holder in party:
        n = int(holder.get("penta_kills", 0) or 0)
        holder["penta_holds"] = n
        if n <= 0:
            continue
        payers = [p for p in party if p is not holder]
        for p in payers:
            p["penta_pays"] += n
        events.append({
            "holder": holder.get("name", "?"),
            "count": n,
            "payers": [p.get("name", "?") for p in payers],
            "amount": round(n * len(payers) * float(penta_unit), 2),
        })
    match["penta_events"] = events
    return match


def aggregate_stats(matches: List[dict], unit_price: float = 10.0,
                    penta_unit: float = 20.0) -> List[dict]:
    """跨场聚合每名玩家的统计(红包榜数据源)。

    返回按 应发总额 -> 场数 -> 场均分 降序的列表:
        name, games, wins, win_rate(%), avg_score,
        party_games, red_packets, rp_amount(评分红包发出, 收入随机不计),
        penta_kills(五杀总数), penta_income(五杀赏金收入),
        penta_out(五杀赏金支出), amount(应发总额), net(净结算: 正=收)
    net = 五杀收入 - 评分红包发出 - 五杀支出 (评分收入随机, 不参与净结算)
    """
    agg: dict = {}
    for m in matches:
        win = bool(m.get("win"))
        for p in (m.get("players") or []):
            name = str(p.get("name", "?"))
            rec = agg.setdefault(name, {
                "name": name, "games": 0, "wins": 0,
                "score_sum": 0.0, "party_games": 0, "red_packets": 0,
                "penta_kills": 0, "penta_paid": 0, "penta_income": 0.0,
            })
            rec["games"] += 1
            if win:
                rec["wins"] += 1
            rec["score_sum"] += float(p.get("new_score", 0) or 0)
            if p.get("party_member"):
                rec["party_games"] += 1
            if p.get("red_packet"):
                rec["red_packets"] += 1
            rec["penta_kills"] += int(p.get("penta_kills", 0) or 0)
            rec["penta_paid"] += int(p.get("penta_pays", 0) or 0)
            # 收入按比赛级 penta_events 结算(持有者按五杀次数收)
            for ev in (m.get("penta_events") or []):
                if ev.get("holder") == name:
                    rec["penta_income"] += float(ev.get("amount", 0) or 0)

    unit = float(unit_price or 0)
    pu = float(penta_unit or 0)
    out = []
    for r in agg.values():
        games = r["games"] or 1
        r["win_rate"] = round(r["wins"] / games * 100)
        r["avg_score"] = round(r["score_sum"] / games, 1)
        r["rp_amount"] = round(r["red_packets"] * unit, 2)
        r["penta_out"] = round(r["penta_paid"] * pu, 2)
        r["amount"] = round(r["rp_amount"] + r["penta_out"], 2)
        r["net"] = round(r["penta_income"] - r["amount"], 2)
        del r["score_sum"]
        r["penta_income"] = round(r["penta_income"], 2)
        out.append(r)

    out.sort(key=lambda x: (-x["amount"], -x["games"], -x["avg_score"]))
    return out


def demo():
    """红包+五杀赏金规则快速演示。"""
    match = {
        "win": True,
        "players": [
            {"name": "阿伟",   "new_score": 88.5, "penta_kills": 1},
            {"name": "老K",    "new_score": 71.2},
            {"name": "摸鱼怪", "new_score": 32.9},
            {"name": "软妹",   "new_score": 80.6, "penta_kills": 1},
            {"name": "大熊",   "new_score": 65.0},
        ],
    }
    apply_red_packet(match, ["阿伟", "摸鱼怪", "老K"])
    apply_penta_bounty(match, penta_unit=20)
    print(RULE_HINT)
    print("-" * 72)
    for p in sorted(match["players"], key=lambda x: -(x.get("new_score") or 0)):
        mark = "🧧 需发红包" if p["red_packet"] else ""
        if p.get("penta_holds"):
            mark += f" 🔥五杀x{p['penta_holds']}(收赏金)"
        if p.get("penta_pays"):
            mark += f" 🗡付赏金x{p['penta_pays']}"
        party = f"组内第{p['party_rank']}名" if p["party_rank"] else "非组队"
        print(f"  {p['name']:<6} 分={p['new_score']:>5}  {party:<8} {mark}")
    print("-" * 72)
    print("  本场红包:", "、".join(match["party_payers"]))
    print("  本场五杀赏金:", match["penta_events"])
    print("  跨场统计:", aggregate_stats([match], unit_price=10, penta_unit=20))


if __name__ == "__main__":
    demo()
