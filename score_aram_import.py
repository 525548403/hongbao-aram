# -*- coding: utf-8 -*-
"""
大乱斗(ARAM)战绩导入 + 本规则评分
====================================
适用场景: 国服(QQ/微信区)等无法用 Riot 官方 API 自动抓取的情况。
用法: 在 matches_input.json 按模板填好每场你所在队伍的 5 人数据,
      然后运行:  python score_aram_import.py
字段对照(每场 team 数组填 5 个队友):
  name   显示名(把自己的 me 设为 true 以高亮)
  kills / assists / deaths  击杀/助攻/死亡
  dmg    对英雄伤害
  taken  承受伤害
  heal   治疗量
  shield 护盾量
  cc     控制时长(秒)
  obj    对防御塔/目标伤害(推进)
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from aram_score_system import Player, compute  # 本规则评分内核

DEFAULT_IN = "matches_input.json"


def to_player(d: dict) -> Player:
    return Player(
        name=d.get("name", "?"),
        kills=int(d.get("kills", 0)),
        assists=int(d.get("assists", 0)),
        deaths=int(d.get("deaths", 0)),
        dmg_to_champs=int(d.get("dmg", 0)),
        dmg_taken=int(d.get("taken", 0)),
        healing=int(d.get("heal", 0)),
        shielding=int(d.get("shield", 0)),
        cc_seconds=float(d.get("cc", 0)),
        tower_dmg=int(d.get("obj", 0)),
        minion_dmg=int(d.get("minion", 0)),
    )


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_IN
    if not os.path.exists(path):
        raise SystemExit(f"❌ 找不到 {path}, 请先按模板填写战绩")
    data = json.load(open(path, encoding="utf-8"))
    matches = data.get("matches", [])
    if not matches:
        raise SystemExit("❌ matches 为空, 请参考模板填写")

    print(f"读取 {len(matches)} 场战绩, 按本规则评分...\n")
    out_lines = []
    for idx, m in enumerate(matches, 1):
        label = m.get("label", f"第{idx}场")
        team_raw = m.get("team", [])
        team = [to_player(p) for p in team_raw]
        if len(team) < 2:
            print(f"[{idx}] {label}: 队伍人数不足, 跳过")
            continue
        res = compute(team)
        block = f"=== [{idx}] {label} ===\n"
        for r in sorted(res, key=lambda x: -x["new_score"]):
            me = "  ◀我" if any(p.get("me") and p.get("name") == r["name"] for p in team_raw) else ""
            reason = ("  " + ",".join(r["reasons"])) if r["reasons"] else ""
            line = (f"  {r['name']:<10} 评分{r['new_score']:>5} {r['grade']} "
                    f"KDA{r['kda']} KP{r['kp']} ECI{r['eci']}{me}{reason}")
            block += line + "\n"
            out_lines.append(f"[{idx}] {label} | {r['name']} {r['new_score']} {r['grade']}")
        print(block)

    with open("aram_scores_imported.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(out_lines) + "\n")
    print(f"已保存: aram_scores_imported.txt")


if __name__ == "__main__":
    main()
