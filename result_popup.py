# -*- coding: utf-8 -*-
"""
原生弹窗(PySide6)
================================================================
popup_match(vm) 用 PySide6 创建一个"置顶"的原生窗口, 表格展示本场
10 人的 英雄 / KDA / 评分 / 评级, 高亮"我"并标🧧红包行。

GUI 代码全部隔离在本文件: 若你本机有 tkinter, 把这里换成 tkinter 实现
(视图模型 vm 的结构不变, 直接复用)。
"""
from PySide6.QtWidgets import (
    QWidget, QApplication, QVBoxLayout, QLabel, QTableWidget, QTableWidgetItem,
    QPushButton, QHeaderView,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QBrush, QFont

_TITLE = "红包乱斗 · 战绩结果"


def _tint(tbl, row, color):
    for c in range(tbl.columnCount()):
        it = tbl.item(row, c)
        if it:
            it.setBackground(QBrush(color))


def popup_match(vm, stay_ms=30000):
    """弹出一个置顶战绩窗口。返回 QWidget(由调用方的事件循环驱动)。
    stay_ms>0 时定时自动关闭。"""
    app = QApplication.instance() or QApplication([])

    w = QWidget()
    w.setWindowTitle(_TITLE)
    w.setWindowFlag(Qt.WindowStaysOnTopHint)
    w.resize(640, 480)

    layout = QVBoxLayout(w)

    # 标题
    hdr = QLabel()
    win_txt = "胜利" if vm.get("win") else "失败"
    champ = vm.get("champion_cn") or vm.get("champion") or "?"
    hdr.setText(f"{champ}  ·  {win_txt}")
    hdr.setFont(QFont("Microsoft YaHei", 18, QFont.Weight.Bold))
    hdr.setAlignment(Qt.AlignCenter)
    layout.addWidget(hdr)

    # 表格
    tbl = QTableWidget()
    tbl.setColumnCount(6)
    tbl.setHorizontalHeaderLabels(["#", "玩家", "英雄", "KDA", "评分", "评级"])
    rows = vm.get("players", [])
    tbl.setRowCount(len(rows))
    for i, p in enumerate(rows):
        tbl.setItem(i, 0, QTableWidgetItem(str(i + 1)))
        nm = p.get("name", "")
        if p.get("red_packet"):
            nm = f"{nm} 🧧"
        elif p.get("party_member"):
            nm = f"{nm} ·组队"
        tbl.setItem(i, 1, QTableWidgetItem(nm))
        tbl.setItem(i, 2, QTableWidgetItem(str(p.get("champion_cn") or p.get("champion") or "")))
        tbl.setItem(i, 3, QTableWidgetItem(str(p.get("kda", ""))))
        tbl.setItem(i, 4, QTableWidgetItem(str(p.get("new_score", ""))))
        tbl.setItem(i, 5, QTableWidgetItem(str(p.get("grade", ""))))
        if p.get("is_me"):
            _tint(tbl, i, QColor(255, 238, 196))   # 暖黄: 我
        elif p.get("red_packet"):
            _tint(tbl, i, QColor(250, 214, 214))   # 浅红: 红包
    tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
    tbl.verticalHeader().setVisible(False)
    layout.addWidget(tbl)

    # 红包提示
    payers = vm.get("party_payers") or []
    if payers:
        tip = QLabel(f"🧧 本场红包: {'、'.join(payers)}")
        tip.setStyleSheet("color:#a32d2d;")
        layout.addWidget(tip)

    # 关闭按钮
    btn = QPushButton("关闭")
    btn.clicked.connect(w.close)
    layout.addWidget(btn)

    # 自动关闭
    if stay_ms and stay_ms > 0:
        QTimer.singleShot(stay_ms, w.close)

    w.show()
    return w


def popup_and_exec(vm, stay_ms=0):
    """独立演示: 起一个 app 并阻塞直到窗口关闭。"""
    app = QApplication([])
    popup_match(vm, stay_ms)
    app.exec()


if __name__ == "__main__":
    # 需要桌面环境才能看到窗口; 仅在没有 GUI 的环境下列印 vm 结构
    import match_view
    sample = {
        "metadata": {"gameId": "TEST-123"},
        "info": {"participants": [
            {"puuid": "ME", "teamId": 100, "win": True, "championName": "Jinx",
             "riotIdGameName": "阿伟", "kills": 12, "assists": 8, "deaths": 3,
             "totalDamageDealtToChampions": 35000, "totalDamageTaken": 18000,
             "totalHeal": 2000, "totalDamageShieldedOnTeammates": 500,
             "timeCCingOthers": 15, "damageDealtToObjectives": 1200, "pentaKills": 1,
             "queueId": 450},
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
    vm = match_view.build_match_view(sample, "ME", party_names=["阿伟", "老K", "软妹"])
    try:
        popup_and_exec(vm)
    except Exception as e:
        # 无显示环境(如构建沙箱)时退化为打印
        print("无法显示 GUI(无桌面环境):", e)
        import json
        print(json.dumps(vm, ensure_ascii=False, indent=2))
