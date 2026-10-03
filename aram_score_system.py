# -*- coding: utf-8 -*-
"""
大乱斗(ARAM)反刷KDA评分系统 —— 每英雄专属画像版
================================================
核心问题:
    传统 WeGame 式评分以 KDA 为主权重, 部分玩家通过"保KDA"
    (躲在后方只混助攻、不参团、不承伤) 刷出虚高评分。

本方案思路:
    1. 用"同队相对贡献占比"替代绝对 KDA —— 队内横向比较, 防止躺赢。
    2. 引入"实质贡献指数(sub_eci)"检测摸鱼: 高 KDA 但低贡献者被惩罚。
    3. 【每英雄专属画像】每个英雄有自己的"贡献倾向(tilt)":
       技能偏向伤害? 承伤? 治疗护盾控制? 还是推塔推进?
       由 tilt 生成该英雄的专属评分权重 —— 每个英雄一套标准。
       (例: Soraka 效用主导 0.48; Ashe 伤害主导 0.45;
             Karma 伤害/效用各半 —— 打输出不亏, 打辅助也合理)
    4. 打法倾向标签: 输出/承伤/效用/推进, 让定位一目了然。

运行: python aram_score_system.py
"""

from dataclasses import dataclass
from typing import List


@dataclass
class Player:
    name: str
    kills: int = 0
    assists: int = 0
    deaths: int = 0
    dmg_to_champs: int = 0   # 对英雄伤害
    dmg_taken: int = 0       # 承受伤害
    healing: int = 0          # 治疗量
    shielding: int = 0        # 护盾量
    cc_seconds: float = 0.0   # 控制时长(秒)
    tower_dmg: int = 0        # 对防御塔伤害
    minion_dmg: int = 0       # 对小兵/建筑伤害(推进)
    champion: str = ""        # 英雄名(英文 championName), 用于查画像
    role: str = ""            # 角色 key, 留空则自动按英雄查/推断


# ============================================================
# 角色模板: 每类角色的贡献倾向 tilt = (伤害, 承伤, 效用, 推进)
#   效用 = 治疗 + 护盾 + 控制
# ============================================================
ROLE_TILT = {
    "tank":     ((0.35, 1.00, 0.60, 0.20), "坦克/前排"),
    "fighter":  ((0.80, 0.60, 0.30, 0.30), "战士"),
    "mage":     ((1.00, 0.15, 0.35, 0.20), "法师"),
    "marksman": ((1.00, 0.10, 0.15, 0.35), "射手"),
    "assassin": ((1.00, 0.05, 0.20, 0.20), "刺客"),
    "support":  ((0.15, 0.25, 1.00, 0.10), "辅助"),
    "generic":  ((0.70, 0.50, 0.50, 0.30), "通用"),
}

# ============================================================
# 特殊英雄定制画像: 与角色模板不同的英雄单独写 tilt
#   tilt = (伤害, 承伤, 效用, 推进);  label 为定位标签
# 这就是"每个英雄都有自己的评分标准"的核心表。
# 未列出的英雄按 CHAMPION_ROLES 的角色取 ROLE_TILT 模板 tilt。
# ============================================================
CHAMPION_TILT = {
    # ---- 双形态/功能交叉英雄 ----
    "karma":       ((0.60, 0.30, 0.70, 0.15), "法师/辅助"),   # 输出辅助两开花
    "seraphine":   ((0.45, 0.25, 0.85, 0.10), "法师/辅助"),
    "morgana":     ((0.40, 0.30, 0.80, 0.10), "法师/辅助"),
    "senna":       ((0.80, 0.20, 0.60, 0.25), "射手/辅助"),
    "pyke":        ((0.70, 0.20, 0.70, 0.15), "刺客/辅助"),
    "thresh":      ((0.35, 0.70, 0.80, 0.15), "坦克/辅助"),
    "brand":       ((0.95, 0.15, 0.40, 0.15), "法师"),        # 辅助位但本质输出
    "zyra":        ((0.90, 0.15, 0.45, 0.15), "法师"),
    "swain":       ((0.55, 0.70, 0.45, 0.15), "法师/坦克"),
    "galio":       ((0.50, 0.85, 0.60, 0.20), "坦克/法师"),
    "gragas":      ((0.55, 0.75, 0.45, 0.20), "坦克/战士"),
    "poppy":       ((0.45, 0.85, 0.45, 0.20), "坦克/战士"),
    "ekko":        ((0.85, 0.35, 0.35, 0.20), "刺客/法师"),
    "diana":       ((0.90, 0.40, 0.25, 0.20), "刺客/战士"),
    "volibear":    ((0.60, 0.75, 0.40, 0.30), "坦克/战士"),
    "shyvana":     ((0.75, 0.60, 0.20, 0.35), "战士"),
    "trundle":     ((0.60, 0.70, 0.30, 0.30), "战士/坦克"),
    # ---- 推进/分推特色 ----
    "ziggs":       ((0.95, 0.10, 0.20, 0.60), "法师/推进"),
    "heimerdinger":((0.80, 0.20, 0.40, 0.55), "法师/推进"),
    "yorick":      ((0.70, 0.40, 0.15, 0.75), "战士/推进"),
    "fiora":       ((0.85, 0.35, 0.10, 0.60), "战士/推进"),
    "tristana":    ((0.90, 0.10, 0.15, 0.55), "射手/推进"),
    "jayce":       ((0.90, 0.20, 0.25, 0.30), "射手/法师"),
    # ---- 极端承伤 ----
    "leona":       ((0.30, 1.00, 0.75, 0.20), "坦克"),
    "braum":       ((0.25, 0.95, 0.70, 0.15), "坦克"),
    "malphite":    ((0.45, 0.90, 0.60, 0.20), "坦克"),
    "amumu":       ((0.40, 0.90, 0.70, 0.15), "坦克"),
    "rammus":      ((0.30, 1.00, 0.55, 0.15), "坦克"),
    "sejuani":     ((0.35, 0.90, 0.70, 0.15), "坦克"),
    "zac":         ((0.35, 0.95, 0.65, 0.15), "坦克"),
    "ornn":        ((0.45, 0.90, 0.55, 0.25), "坦克"),
    "ksante":      ((0.45, 0.95, 0.50, 0.15), "坦克"),
    "dr. mundo":   ((0.55, 0.90, 0.20, 0.20), "坦克/战士"),
    "sion":        ((0.45, 0.90, 0.45, 0.30), "坦克"),
    "tahm kench":  ((0.35, 0.90, 0.60, 0.20), "坦克"),
    # ---- 极端输出 ----
    "ashe":        ((0.95, 0.10, 0.30, 0.35), "射手"),
    "jinx":        ((1.00, 0.10, 0.10, 0.35), "射手"),
    "vayne":       ((1.00, 0.10, 0.10, 0.30), "射手"),
    "draven":      ((1.00, 0.10, 0.05, 0.25), "射手"),
    "kaisa":       ((1.00, 0.10, 0.10, 0.25), "射手"),
    "zed":         ((1.00, 0.05, 0.10, 0.20), "刺客"),
    "katarina":    ((1.00, 0.05, 0.10, 0.15), "刺客"),
    "veigar":      ((1.00, 0.10, 0.20, 0.15), "法师"),
    "syndra":      ((1.00, 0.10, 0.25, 0.15), "法师"),
    "karthus":     ((1.00, 0.10, 0.25, 0.10), "法师"),
    # ---- 极端效用 ----
    "soraka":      ((0.10, 0.25, 1.00, 0.05), "辅助"),
    "janna":       ((0.10, 0.25, 1.00, 0.10), "辅助"),
    "lulu":        ((0.15, 0.25, 1.00, 0.10), "辅助"),
    "nami":        ((0.15, 0.25, 1.00, 0.10), "辅助"),
    "sona":        ((0.20, 0.25, 1.00, 0.10), "辅助"),
    "yuumi":       ((0.10, 0.15, 1.00, 0.05), "辅助"),
    "milio":       ((0.10, 0.20, 1.00, 0.05), "辅助"),
    "zilean":      ((0.20, 0.25, 0.95, 0.10), "辅助"),
    "renata":      ((0.15, 0.30, 0.95, 0.10), "辅助"),
    "taric":       ((0.20, 0.55, 0.85, 0.10), "辅助/坦克"),
    "ivern":       ((0.15, 0.30, 0.95, 0.20), "辅助"),
}

# 英雄名 -> 默认角色 (championName 英文, 不区分大小写)
# 未在上面 CHAMPION_TILT 定制的英雄, 按此角色取 ROLE_TILT 模板 tilt。
CHAMPION_ROLES = {
    # ---- 坦克 / 前排 ----
    "leona": "tank", "braum": "tank", "galio": "tank", "ornn": "tank",
    "sion": "tank", "tahm kench": "tank", "nautilus": "tank", "alistar": "tank",
    "maokai": "tank", "amumu": "tank", "rammus": "tank", "cho'gath": "tank",
    "zac": "tank", "sejuani": "tank", "poppy": "tank", "singed": "tank",
    "malphite": "tank", "blitzcrank": "tank", "taric": "tank", "nunu": "tank",
    "volibear": "tank", "dr. mundo": "tank", "mundo": "tank", "shen": "tank",
    "gragas": "tank", "rell": "tank", "rakan": "tank", "thresh": "tank",
    "ksante": "tank", "skarner": "tank", "tahmkench": "tank",
    # ---- 战士 ----
    "darius": "fighter", "garen": "fighter", "camille": "fighter",
    "fiora": "fighter", "jax": "fighter", "vi": "fighter", "wukong": "fighter",
    "aatrox": "fighter", "renekton": "fighter", "kled": "fighter",
    "illaoi": "fighter", "olaf": "fighter", "tryndamere": "fighter",
    "yasuo": "fighter", "yone": "fighter", "irelia": "fighter", "urgot": "fighter",
    "pantheon": "fighter", "mordekaiser": "fighter", "kayle": "fighter",
    "riven": "fighter", "gwen": "fighter", "briar": "fighter", "warwick": "fighter",
    "hecarim": "fighter", "nocturne": "fighter", "xin zhao": "fighter",
    "reksai": "fighter", "jarvan iv": "fighter", "lee sin": "fighter",
    "kayn": "fighter", "naafiri": "fighter", "sett": "fighter",
    "yorick": "fighter", "shyvana": "fighter", "trundle": "fighter",
    # ---- 法师 ----
    "syndra": "mage", "lux": "mage", "brand": "mage", "ziggs": "mage",
    "xerath": "mage", "vel'koz": "mage", "orianna": "mage", "ahri": "mage",
    "veigar": "mage", "annie": "mage", "viktor": "mage", "swain": "mage",
    "taliyah": "mage", "azir": "mage", "cassiopeia": "mage", "ryze": "mage",
    "zoe": "mage", "malzahar": "mage", "heimerdinger": "mage",
    "fiddlesticks": "mage", "karthus": "mage", "lissandra": "mage",
    "zyra": "mage", "hwei": "mage", "mel": "mage", "seraphine": "mage",
    "twisted fate": "mage", "vladimir": "mage", "anivia": "mage",
    "aurora": "mage", "neeko": "mage",
    # ---- 射手 ----
    "ashe": "marksman", "jinx": "marksman", "caitlyn": "marksman",
    "ezreal": "marksman", "kog'maw": "marksman", "miss fortune": "marksman",
    "sivir": "marksman", "tristana": "marksman", "varus": "marksman",
    "xayah": "marksman", "zeri": "marksman", "aphelios": "marksman",
    "jhin": "marksman", "kaisa": "marksman", "vayne": "marksman",
    "twitch": "marksman", "quinn": "marksman", "draven": "marksman",
    "lucian": "marksman", "samira": "marksman", "akshan": "marksman",
    "nilah": "marksman", "smolder": "marksman", "senna": "marksman",
    # ---- 刺客 ----
    "zed": "assassin", "kha'zix": "assassin", "talon": "assassin",
    "akali": "assassin", "qiyana": "assassin", "katarina": "assassin",
    "fizz": "assassin", "leblanc": "assassin", "ekko": "assassin",
    "pyke": "assassin", "rengar": "assassin", "shaco": "assassin",
    "viego": "assassin", "khazix": "assassin", "diana": "assassin",
    # ---- 辅助(纯辅助; 伤害型辅助已在 CHAMPION_TILT 单独定制) ----
    "soraka": "support", "janna": "support", "lulu": "support",
    "nami": "support", "sona": "support", "yuumi": "support",
    "zilean": "support", "morgana": "support", "milio": "support",
    "renata": "support", "bard": "support", "ivern": "support",
    "karma": "support",
}


def _normalize_champion(name: str) -> str:
    return (name or "").strip().lower()


def tilt_to_weights(tilt) -> tuple:
    """tilt(伤害,承伤,效用,推进) -> 权重(伤害,承伤,参战,效用,推进,KDA), 合计=1.0.

    参战 KP 固定 0.20、KDA 调节固定 0.10, 其余 0.70 按 tilt 归一分配。"""
    td, tt, tu, to = tilt
    s = max(0.01, td + tt + tu + to)
    a = 0.70 / s
    return (td * a, tt * a, 0.20, tu * a, to * a, 0.10)


def playstyle_of(tilt) -> str:
    """打法倾向标签: 主导维度 + 显著副维度(>=0.55)."""
    names = ["伤害", "承伤", "效用", "推进"]
    pairs = sorted(zip(names, tilt), key=lambda x: -x[1])
    main = f"{pairs[0][0]}型"
    sub = [n for n, v in pairs[1:] if v >= 0.55]
    if sub:
        return main[:-1] + "+" + "+".join(sub)
    return main


def infer_role(champion: str, dmg_share: float, tank_share: float,
               util_share: float) -> str:
    """数据兜底推断(仅用于英雄库未收录的英雄).

    兜底对 support 非常保守(util 占比极高且伤害极低才算),
    防止战士/坦克靠堆控制误入辅助权重档。"""
    if util_share > 0.40 and dmg_share < 0.15:
        return "support"
    if tank_share > 0.35 and dmg_share < 0.32:
        return "tank"
    if dmg_share > 0.45:
        return "mage"
    return "generic"


def get_profile(champion: str):
    """查英雄画像: 返回 {role, label, tilt, style}; 未收录返回 None."""
    c = _normalize_champion(champion)
    if c in CHAMPION_TILT:
        tilt, label = CHAMPION_TILT[c]
        return {"role": "champion_db", "label": label, "tilt": tilt,
                "style": playstyle_of(tilt)}
    if c in CHAMPION_ROLES:
        role = CHAMPION_ROLES[c]
        tilt, label = ROLE_TILT[role]
        return {"role": role, "label": label, "tilt": tilt,
                "style": playstyle_of(tilt)}
    return None


def _util_of(p: Player) -> float:
    """辅助效用统一量纲: 控制按每秒≈800等效伤害估值."""
    return float(p.healing or 0) + float(p.shielding or 0) + float(p.cc_seconds or 0) * 800


def compute(players: List[Player]) -> List[dict]:
    n = len(players)
    team_kills = max(1, sum(p.kills for p in players))
    total_dmg = max(1, sum(p.dmg_to_champs for p in players))
    total_tank = max(1, sum(p.dmg_taken for p in players))
    total_obj = max(1, sum(p.tower_dmg + p.minion_dmg for p in players))
    total_util = max(1, sum(_util_of(p) for p in players))

    exp = 1.0 / n  # 期望占比: 假设队内 n 人理想均摊

    def kda(p):
        return (p.kills + p.assists) / max(1, p.deaths)

    kdas = [kda(p) for p in players]
    mean_kda = sum(kdas) / n if n else 1.0
    max_kda = max(kdas) or 1.0

    # ---- 第一遍: 各维度占队内比例 + 查英雄画像 + 专属权重 ----
    pre = []
    for p in players:
        dmg_share = p.dmg_to_champs / total_dmg
        tank_share = p.dmg_taken / total_tank
        kp = (p.kills + p.assists) / team_kills
        util_share = _util_of(p) / total_util
        obj_share = (p.tower_dmg + p.minion_dmg) / total_obj

        # ---- 英雄画像: 定制 tilt > 角色模板 > 数据兜底 ----
        prof = get_profile(p.champion)
        if prof is None:
            role = infer_role(p.champion, dmg_share, tank_share, util_share)
            tilt, label = ROLE_TILT[role]
            prof = {"role": role, "label": label, "tilt": tilt,
                    "style": playstyle_of(tilt)}
        w = tilt_to_weights(prof["tilt"])

        # 与"均摊期望"比较, 超过即满分 -> 奖励真正高贡献者
        sd = min(1.0, dmg_share / exp)
        st = min(1.0, tank_share / exp)
        su = min(1.0, util_share / exp)
        so = min(1.0, obj_share / exp)
        kp_score = min(1.0, kp / 0.20)     # 参战率期望 20%

        # 该英雄专属加权基础分(0~1), 即其有效贡献指数 ECI
        eci = (w[0] * sd + w[1] * st + w[2] * kp_score
               + w[3] * su + w[4] * so)
        kda_norm = min(1.0, kda(p) / max_kda)
        base = min(1.0, eci + w[5] * kda_norm)
        # 实质贡献指数(不含参战率/KDA): 专用于防刷判定
        sub_eci = w[0] * sd + w[1] * st + w[3] * su + w[4] * so

        # 划水判定按该英雄的主导维度(tilt 最大项)
        shares = {"dmg": dmg_share, "tank": tank_share,
                  "util": util_share, "obj": obj_share}
        key = max(zip(prof["tilt"], ("dmg", "tank", "util", "obj")))[1]

        pre.append({
            "p": p, "role": prof["role"], "label": prof["label"],
            "style": prof["style"], "tilt": prof["tilt"], "w": w, "key": key,
            "dmg_share": dmg_share, "tank_share": tank_share,
            "kp": kp, "util_share": util_share, "obj_share": obj_share,
            "sd": sd, "st": st, "su": su, "so": so,
            "kp_score": kp_score, "eci": base, "sub_eci": sub_eci, "kda": kda(p),
        })

    mean_sub_eci = sum(x["sub_eci"] for x in pre) / n if n else 0.0

    # ---- 第二遍: 专属基础分 + 防刷惩罚 ----
    results = []
    for x in pre:
        score = x["eci"] * 100.0
        penalty = 1.0
        reasons = []

        # 规则1: KDA 远超队内均值, 但实质贡献(不含参战率/KDA)低于队内一半
        if x["kda"] > 1.5 * mean_kda and x["sub_eci"] < mean_sub_eci * 0.5:
            penalty *= 0.70
            reasons.append("高KDA低贡献(疑似保KDA)")

        # 规则2: 参战率过低(<35%)
        if x["kp"] < 0.35:
            penalty *= 0.85
            reasons.append("参战率过低")

        # 规则3: 该英雄主导维度显著低于期望(低于均摊的60%) 且实质贡献低 -> 划水
        key_val = x[x["key"] + "_share"]
        if key_val < exp * 0.6 and x["sub_eci"] < mean_sub_eci * 0.5:
            penalty *= 0.80
            reasons.append(f"全程划水({x['key']}维度缺失)")

        final = score * penalty
        grade = ("S" if final >= 85 else "A" if final >= 70 else
                 "B" if final >= 55 else "C" if final >= 40 else "D")
        results.append({
            "name": x["p"].name,
            "champion": x["p"].champion,
            "role": x["role"],
            "role_label": x["label"],
            "style": x["style"],            # 打法倾向: 伤害型/承伤+效用型...
            "tilt": list(x["tilt"]),        # 英雄贡献倾向 (伤害,承伤,效用,推进)
            "kda": round(x["kda"], 2),
            "kp": round(x["kp"], 2),
            "dmg_share": round(x["dmg_share"], 3),
            "tank_share": round(x["tank_share"], 3),
            "util_share": round(x["util_share"], 3),
            "eci": round(x["eci"], 3),
            "classic_kda": round(min(1.0, x["kda"] / max_kda) * 100, 1),
            "new_score": round(final, 1),
            "grade": grade,
            "reasons": reasons,
        })
    return results


def demo():
    # 同队5人演示, 覆盖不同英雄画像:
    # A 射手(Ashe)   —— 伤害主导
    # B 摸鱼法师(Lux) —— KDA靠助攻刷高, 伤害/承伤极低
    # C 坦克(Leona)   —— 承伤+控制主导
    # D 辅助(Soraka)  —— 效用主导(纯辅助)
    # E 卡尔玛(Karma) —— 伤害/效用双修画像, 打输出打辅助都按同一套画像评
    team = [
        Player("A-射手", kills=12, assists=8, deaths=4, champion="Ashe",
               dmg_to_champs=48000, dmg_taken=18000,
               cc_seconds=6, tower_dmg=3000, minion_dmg=9000),
        Player("B-摸鱼法师", kills=5, assists=14, deaths=2, champion="Lux",
               dmg_to_champs=9000, dmg_taken=4000,
               cc_seconds=1, tower_dmg=500, minion_dmg=1500),
        Player("C-坦克", kills=3, assists=10, deaths=9, champion="Leona",
               dmg_to_champs=22000, dmg_taken=42000,
               cc_seconds=18, tower_dmg=2000, minion_dmg=5000),
        Player("D-辅助", kills=1, assists=16, deaths=5, champion="Soraka",
               dmg_to_champs=6000, dmg_taken=12000, healing=18000, shielding=14000,
               cc_seconds=22, tower_dmg=800, minion_dmg=2000),
        Player("E-卡尔玛", kills=6, assists=9, deaths=6, champion="Karma",
               dmg_to_champs=25000, dmg_taken=20000, healing=6000, shielding=5000,
               cc_seconds=8, tower_dmg=1500, minion_dmg=4000),
    ]
    res = compute(team)
    print("=" * 112)
    print("大乱斗反刷KDA评分系统 —— 每英雄专属画像演示")
    print("=" * 112)
    hdr = (f"{'玩家':<10}{'英雄':<8}{'定位':<12}{'打法倾向':<16}"
           f"{'KDA':>6}{'伤害占比':>9}{'承伤占比':>9}{'新分':>7}{'评级':>5}  专属权重(伤/坦/效用/推进)")
    print(hdr)
    print("-" * 112)
    for r in res:
        t = r["tilt"]
        s = max(0.01, sum(t))
        aw = "/".join(f"{v / s * 0.7:.2f}" for v in t)
        print(f"{r['name']:<10}{r['champion']:<8}{r['role_label']:<12}{r['style']:<16}"
              f"{r['kda']:>6}{r['dmg_share']:>9}{r['tank_share']:>9}"
              f"{r['new_score']:>7}{r['grade']:>5}  {aw}")
    print("-" * 112)
    for r in res:
        if r["reasons"]:
            print(f"  ⚠ {r['name']}({r['role_label']}/{r['style']}): {', '.join(r['reasons'])}")
    print()
    print("要点:")
    print("  · 每个英雄按自己的画像权重评分: Soraka 效用权重≈0.48, Ashe 伤害权重≈0.45,")
    print("    Leona 承伤权重≈0.30 —— 英雄擅长什么贡献, 就在哪个维度给分")
    print("  · Karma 画像伤害/效用各半: 打输出不亏分, 打辅助不低分, 无红利可钻")
    print("  · Lux 靠高助攻刷KDA但伤害极低 -> 实质贡献指数(sub_eci)检测 + 惩罚压分")


if __name__ == "__main__":
    demo()
