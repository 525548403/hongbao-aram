# -*- coding: utf-8 -*-
"""
原生弹窗(PySide6)
================================================================
popup_match(vm) 弹出一个**左下角轻量浮窗**(无边框、不抢焦点、始终置顶),
表格展示本场 10 人的 英雄 / KDA / 评分 / 评级, 高亮"我"并标🧧红包行。

设计要点(2026-10-04 改):
  - 位置: 屏幕左下角, 避开游戏画面中央, 不遮挡操作(不置中、不抢焦点)。
  - 不打断游戏: Qt.Tool 类型 + WA_ShowWithoutActivating, 弹出的瞬间
    不会把焦点从游戏窗口抢走, 游戏中也不会被打断。
  - 15 秒倒计时自动消失, 顶部进度条 + 底部"x 秒后自动关闭 · 手动关闭"提示。
  - 调用方必须持有返回的窗口引用(否则会被 GC 回收)。

GUI 代码全部隔离在本文件: 若你本机有 tkinter, 把这里换成 tkinter 实现
(视图模型 vm 的结构不变, 直接复用)。
"""
from PySide6.QtWidgets import (
    QWidget, QApplication, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QPushButton, QHeaderView, QProgressBar,
)
from PySide6.QtCore import Qt, QTimer, QRect
from PySide6.QtGui import QColor, QBrush, QFont

_TITLE = "红包乱斗 · 本场战绩"
DEFAULT_STAY_MS = 15000     # 15 秒后自动消失
_MARGIN = 18                # 距屏幕左/下边缘留白


def _tint(tbl, row, color):
    for c in range(tbl.columnCount()):
        it = tbl.item(row, c)
        if it:
            it.setBackground(QBrush(color))


def _place_bottom_left(w):
    """把窗口贴到主屏幕左下角(不抢焦点, 避免打断游戏)。"""
    scr = QApplication.primaryScreen()
    if scr is None:
        return
    geo = scr.availableGeometry()
    x = geo.left() + _MARGIN
    y = geo.bottom() - w.height() - _MARGIN
    w.move(int(x), int(max(geo.top() + _MARGIN, y)))


def popup_match(vm, stay_ms=DEFAULT_STAY_MS):
    """在屏幕左下角弹出一个轻量战绩浮窗, 返回 QWidget。

    重要: 调用方必须持有返回的窗口引用(例如放进一个列表), 否则 Python 会在
    事件循环返回后立即把窗口 GC 回收, 表现为"一闪而过"。
    stay_ms>0 时倒计时自动关闭(默认 15s); 传 0 = 不自动关闭。"""
    app = QApplication.instance() or QApplication([])

    w = QWidget()
    w.setWindowTitle(_TITLE)
    # ---- 不打断游戏的关键窗口属性 ----
    w.setWindowFlags(
        Qt.Tool                  # 不占任务栏、不参与 Alt+Tab
        | Qt.FramelessWindowHint  # 无边框, 视觉更轻
        | Qt.WindowStaysOnTopHint  # 始终在最上, 但不遮挡屏幕中央
    )
    w.setAttribute(Qt.WA_ShowWithoutActivating, True)   # 显示时不抢焦点
    w.setAttribute(Qt.WA_DeleteOnClose, True)           # 关闭即销毁
    w.setFocusPolicy(Qt.NoFocus)                        # 完全不接收键盘焦点
    w.resize(392, 300)

    layout = QVBoxLayout(w)
    layout.setContentsMargins(10, 8, 10, 8)
    layout.setSpacing(6)

    # ---- 顶部进度条(15s 倒计时可视化) ----
    bar = QProgressBar()
    bar.setRange(0, 100)
    bar.setValue(100)
    bar.setFixedHeight(6)
    bar.setTextVisible(False)
    bar.setStyleSheet(
        "QProgressBar{background:rgba(255,255,255,.10);border:none;border-radius:3px;}"
        "QProgressBar::chunk{background:#e8b339;border-radius:3px;}")
    layout.addWidget(bar)

    # ---- 标题 ----
    hdr = QLabel()
    win_txt = "胜利" if vm.get("win") else "失败"
    champ = vm.get("champion_cn") or vm.get("champion") or "?"
    hdr.setText(f"{champ}  ·  {win_txt}")
    hdr.setFont(QFont("Microsoft YaHei", 15, QFont.Weight.Bold))
    hdr.setStyleSheet("color:#f0e6d2;")
    hdr.setAlignment(Qt.AlignCenter)
    layout.addWidget(hdr)

    # ---- 表格 ----
    tbl = QTableWidget()
    tbl.setColumnCount(5)
    tbl.setHorizontalHeaderLabels(["玩家", "英雄", "KDA", "评分", "评级"])
    rows = vm.get("players", [])
    tbl.setRowCount(len(rows))
    for i, p in enumerate(rows):
        nm = p.get("name", "")
        if p.get("red_packet"):
            nm = f"{nm} 🧧"
        elif p.get("party_member"):
            nm = f"{nm} ·组队"
        for col, val in enumerate((nm,
                                   p.get("champion_cn") or p.get("champion") or "",
                                   p.get("kda", ""),
                                   p.get("new_score", ""),
                                   p.get("grade", ""))):
            it = QTableWidgetItem(str(val))
            if p.get("is_me"):
                it.setForeground(QBrush(QColor("#ffd97a")))
                it.setFont(QFont("Microsoft YaHei", 9, QFont.Weight.Bold))
            tbl.setItem(i, col, it)
        if p.get("is_me"):
            _tint(tbl, i, QColor(70, 56, 26))        # 暖黄底: 我
        elif p.get("red_packet"):
            _tint(tbl, i, QColor(70, 34, 34))        # 浅红底: 红包
    tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
    tbl.verticalHeader().setVisible(False)
    tbl.setShowGrid(False)
    tbl.setFocusPolicy(Qt.NoFocus)
    tbl.setStyleSheet(
        "QTableWidget{background:rgba(12,16,28,.92);color:#dfe6f3;"
        "gridline-color:rgba(148,170,220,.12);font-size:12px;}"
        "QHeaderView::section{background:rgba(30,38,60,.95);color:#8fa0bf;"
        "border:none;padding:3px;font-size:11px;}")
    layout.addWidget(tbl)

    # ---- 红包提示 ----
    payers = vm.get("party_payers") or []
    if payers:
        tip = QLabel(f"🧧 本场红包: {'、'.join(payers)}")
        tip.setStyleSheet("color:#ff9d9d;font-size:11px;")
        tip.setAlignment(Qt.AlignCenter)
        layout.addWidget(tip)

    # ---- 底部: 倒计时文案 + 手动关闭 ----
    foot = QWidget()
    fl = QHBoxLayout(foot)
    fl.setContentsMargins(0, 0, 0, 0)
    hint = QLabel()
    hint.setStyleSheet("color:#8fa0bf;font-size:11px;")
    btn = QPushButton("关闭")
    btn.setFixedHeight(22)
    btn.setStyleSheet(
        "QPushButton{background:#e8b339;color:#101625;border:none;border-radius:6px;"
        "font-size:11px;font-weight:700;padding:0 12px;}")
    btn.clicked.connect(w.close)
    btn.setFocusPolicy(Qt.NoFocus)
    fl.addWidget(hint, 1)
    fl.addWidget(btn, 0)
    layout.addWidget(foot)

    # 圆角深色卡片
    w.setStyleSheet(
        "QWidget#card{background:#141c33;border:1px solid rgba(232,179,57,.45);"
        "border-radius:12px;}")
    w.setObjectName("card")

    # ---- 15s 倒计时自动关闭 ----
    if stay_ms and stay_ms > 0:
        total = max(1, int(stay_ms / 1000))
        remain = {"n": total}

        def _tick():
            remain["n"] -= 1
            n = remain["n"]
            if n <= 0:
                w.close()
                return
            bar.setValue(int(n / total * 100))
            hint.setText(f"{n} 秒后自动关闭")

        hint.setText(f"{total} 秒后自动关闭")
        t = QTimer(w)
        t.timeout.connect(_tick)
        t.start(1000)

    w.show()
    _place_bottom_left(w)
    # 不激活窗口: 保证游戏仍在焦点, 这里只是"路过"一下
    w.setWindowState(w.windowState() & ~Qt.WindowMinimized)
    w.raise_()
    return w


def popup_info(title, message, stay_ms=DEFAULT_STAY_MS):
    """左下角提示浮窗(如远程战绩延迟失败), 返回 QWidget。"""
    app = QApplication.instance() or QApplication([])

    w = QWidget()
    w.setWindowTitle(title or _TITLE)
    w.setWindowFlags(
        Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
    w.setAttribute(Qt.WA_ShowWithoutActivating, True)
    w.setAttribute(Qt.WA_DeleteOnClose, True)
    w.setFocusPolicy(Qt.NoFocus)
    w.resize(360, 132)

    layout = QVBoxLayout(w)
    layout.setContentsMargins(12, 10, 12, 10)
    layout.setSpacing(6)

    hdr = QLabel(title or _TITLE)
    hdr.setFont(QFont("Microsoft YaHei", 13, QFont.Weight.Bold))
    hdr.setStyleSheet("color:#f0e6d2;")
    hdr.setAlignment(Qt.AlignCenter)
    layout.addWidget(hdr)

    body = QLabel(message or "")
    body.setWordWrap(True)
    body.setAlignment(Qt.AlignCenter)
    body.setStyleSheet("color:#cfd8ea;font-size:12px;")
    layout.addWidget(body)

    foot = QWidget()
    fl = QHBoxLayout(foot)
    fl.setContentsMargins(0, 0, 0, 0)
    hint = QLabel()
    hint.setStyleSheet("color:#8fa0bf;font-size:11px;")
    btn = QPushButton("关闭")
    btn.setFixedHeight(22)
    btn.setStyleSheet(
        "QPushButton{background:#e8b339;color:#101625;border:none;border-radius:6px;"
        "font-size:11px;font-weight:700;padding:0 12px;}")
    btn.clicked.connect(w.close)
    btn.setFocusPolicy(Qt.NoFocus)
    fl.addWidget(hint, 1)
    fl.addWidget(btn, 0)
    layout.addWidget(foot)

    w.setStyleSheet(
        "QWidget#card{background:#141c33;border:1px solid rgba(255,93,93,.45);"
        "border-radius:12px;}")
    w.setObjectName("card")

    if stay_ms and stay_ms > 0:
        total = max(1, int(stay_ms / 1000))
        remain = {"n": total}

        def _tick():
            remain["n"] -= 1
            if remain["n"] <= 0:
                w.close()
                return
            hint.setText(f"{remain['n']} 秒后自动关闭")

        hint.setText(f"{total} 秒后自动关闭")
        t = QTimer(w)
        t.timeout.connect(_tick)
        t.start(1000)

    w.show()
    _place_bottom_left(w)
    w.raise_()
    return w


if __name__ == "__main__":
    # 需要桌面环境才能看到窗口; 仅在没有 GUI 的环境下列印 vm 结构
    import json
    import match_view
    sample = {
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
             "timeCCingOthers": 40, "damageDealtToObjectives": 300,
             "pentaKills": 0, "queueId": 450},
            {"puuid": "T3", "teamId": 100, "win": True, "championName": "Soraka",
             "riotIdGameName": "软妹", "kills": 0, "assists": 22, "deaths": 4,
             "totalDamageDealtToChampions": 1500, "totalDamageTaken": 12000,
             "totalHeal": 12000, "totalDamageShieldedOnTeammates": 3000,
             "timeCCingOthers": 10, "damageDealtToObjectives": 100,
             "pentaKills": 0, "queueId": 450},
            {"puuid": "T4", "teamId": 100, "win": True, "championName": "Garen",
             "riotIdGameName": "大熊", "kills": 6, "assists": 5, "deaths": 6,
             "totalDamageDealtToChampions": 18000, "totalDamageTaken": 25000,
             "totalHeal": 1000, "totalDamageShieldedOnTeammates": 0,
             "timeCCingOthers": 8, "damageDealtToObjectives": 800,
             "pentaKills": 0, "queueId": 450},
            {"puuid": "T5", "teamId": 100, "win": True, "championName": "Veigar",
             "riotIdGameName": "小法", "kills": 9, "assists": 7, "deaths": 5,
             "totalDamageDealtToChampions": 28000, "totalDamageTaken": 9000,
             "totalHeal": 500, "totalDamageShieldedOnTeammates": 0,
             "timeCCingOthers": 5, "damageDealtToObjectives": 400,
             "pentaKills": 0, "queueId": 450},
            {"puuid": "E1", "teamId": 200, "win": False, "championName": "Teemo",
             "riotIdGameName": "蘑菇", "kills": 4, "assists": 6, "deaths": 7,
             "totalDamageDealtToChampions": 16000, "totalDamageTaken": 15000,
             "totalHeal": 800, "totalDamageShieldedOnTeammates": 200,
             "timeCCingOthers": 12, "damageDealtToObjectives": 600,
             "pentaKills": 0, "queueId": 450},
            {"puuid": "E2", "teamId": 200, "win": False, "championName": "Yasuo",
             "riotIdGameName": "亚索", "kills": 8, "assists": 4, "deaths": 8,
             "totalDamageDealtToChampions": 24000, "totalDamageTaken": 14000,
             "totalHeal": 300, "totalDamageShieldedOnTeammates": 0,
             "timeCCingOthers": 6, "damageDealtToObjectives": 500,
             "pentaKills": 0, "queueId": 450},
            {"puuid": "E3", "teamId": 200, "win": False, "championName": "Lux",
             "riotIdGameName": "拉克丝", "kills": 5, "assists": 9, "deaths": 6,
             "totalDamageDealtToChampions": 20000, "totalDamageTaken": 8000,
             "totalHeal": 600, "totalDamageShieldedOnTeammates": 400,
             "timeCCingOthers": 20, "damageDealtToObjectives": 300,
             "pentaKills": 0, "queueId": 450},
            {"puuid": "E4", "teamId": 200, "win": False, "championName": "Braum",
             "riotIdGameName": "布隆", "kills": 2, "assists": 14, "deaths": 7,
             "totalDamageDealtToChampions": 5000, "totalDamageTaken": 22000,
             "totalHeal": 5000, "totalDamageShieldedOnTeammates": 4000,
             "timeCCingOthers": 35, "damageDealtToObjectives": 200,
             "pentaKills": 0, "queueId": 450},
            {"puuid": "E5", "teamId": 200, "win": False, "championName": "Ahri",
             "riotIdGameName": "阿狸", "kills": 7, "assists": 8, "deaths": 6,
             "totalDamageDealtToChampions": 22000, "totalDamageTaken": 11000,
             "totalHeal": 700, "totalDamageShieldedOnTeammates": 0,
             "timeCCingOthers": 18, "damageDealtToObjectives": 450,
             "pentaKills": 0, "queueId": 450},
        ]},
    }
    vm = match_view.build_match_view(sample, "ME", party_names=["阿伟", "老K", "软妹"])
    try:
        app = QApplication([])
        w = popup_match(vm)
        app.exec()
    except Exception as e:
        # 无显示环境(如构建沙箱)时退化为打印
        print("无法显示 GUI(无桌面环境):", e)
        print(json.dumps(vm, ensure_ascii=False, indent=2))
