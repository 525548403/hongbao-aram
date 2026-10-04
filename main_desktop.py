# -*- coding: utf-8 -*-
"""
红包乱斗 · 桌面常驻程序(原型入口)
================================================================
替代 aram_web.py 的 Web 服务: 常驻系统托盘, 后台监听 LCU 事件总线,
对局一结束就自动拉取 SGP 战绩、算分, 并弹出原生结果窗。

运行: python main_desktop.py  (已登录英雄联盟客户端; 国服建议开加速器)
托盘右键: "测试弹窗" / "退出"。

依赖: PySide6(原生 GUI) + websocket-client(LCU 事件总线)
"""
import os
import sys
import json
import time
import queue
import threading
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import (QApplication, QSystemTrayIcon, QMenu, QWidget)
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont, QAction
from PySide6.QtCore import Qt, QObject, Signal

import lcu_watcher
import match_view
import result_popup
import aram_web
from aram_akari_framework import (lcu_auth, get_entitlements, SgpFetcher,
                                  read_league_akari_config)


QUEUE = queue.Queue()
STOP = threading.Event()
SEEN = set()          # 已处理过的 game_id(去重)
LAST_VM = None        # 最近一次结果(供"测试弹窗"复用)
BRIDGE = None         # 跨线程信号桥(在 main 里创建, 位于 GUI 线程)
TRAY = None


def _load_party():
    """可选组队名单: aram_party.json = ["名字1","名字2",...]。无则 None。"""
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "aram_party.json")
    if os.path.exists(p):
        try:
            names = json.load(open(p, encoding="utf-8"))
            if isinstance(names, list):
                return [str(n).strip() for n in names if str(n).strip()]
        except Exception:
            pass
    return None


def _status(text):
    """上报状态(任意线程调用, 经 BRIDGE 切回 GUI 线程更新托盘 tooltip)。"""
    if BRIDGE is not None:
        BRIDGE.status.emit(text)


def _fetch_with_retry(fetcher, game_id, timeout=120.0, base=3.0, cap=10.0):
    """对局结束瞬间 SGP DETAILS 通常延迟 10~30s(国服更慢), 指数退避轮询直到拿到 10 人完整数据。
    超时窗口放宽到 120s, 避免"对局结束却因 SGP 延迟而弹不出窗"。"""
    deadline = time.time() + timeout
    delay = base
    while time.time() < deadline:
        try:
            d = fetcher.get_details(game_id)
            parts, _ = match_view.participants_from_details(d)
            if parts and len(parts) >= 10 and _has_scores(parts):
                return d
        except Exception:
            pass
        if time.time() >= deadline:
            break
        time.sleep(delay)
        delay = min(delay * 1.5, cap)
    return None


def _has_scores(parts):
    """SGP 在战绩就绪前可能返回空壳, 这里确认至少有完整数值字段。"""
    for p in parts:
        if p.get("totalDamageDealtToChampions") is not None and \
           p.get("kills") is not None:
            return True
    return False


def _on_game_end(gid):
    """LCU 事件回调(在 ws 线程): 仅把 game_id 丢进队列, 不在 ws 线程做网络。"""
    QUEUE.put(gid)


def _process_game(gid):
    """worker 线程: 拉取 + 算分 + 触发弹窗(网络在此线程, 弹窗经 BRIDGE 回 GUI 线程)。"""
    try:
        base, s, cfg = lcu_auth()
        token, puuid = get_entitlements(base, s)
        rso = (cfg or {}).get("rsoPlatformId", "HN10")
        region = (cfg or {}).get("region", "TENCENT")
        fetcher = SgpFetcher(token, rso, region)
        _status(f"对局 {gid} 结束, 拉取战绩中…")
        details = _fetch_with_retry(fetcher, gid)
        if not details:
            # 远程战绩延迟拉取失败: 弹信息窗告知用户(而非静默无弹窗),
            # 用户可稍后在战绩面板点「拉取全部战绩」补录该场。
            _status(f"对局 {gid} 拉取超时(SGP 可能延迟)")
            if BRIDGE is not None:
                BRIDGE.popup_info.emit(
                    "🧧 对局已结束",
                    f"对局 {gid} 已结束, 但远程战绩暂未就绪(SGP 延迟/网络), "
                    f"未能自动弹出评分。\n可稍后在战绩面板点「拉取全部战绩」补录本场。")
            return
        vm = match_view.build_match_view(details, puuid, party_names=_load_party())
        if not vm:
            _status(f"对局 {gid} 无法解析(非大乱斗或无我方数据), 不弹窗")
            return
        if vm.get("skip"):
            _status(f"跳过: {vm.get('reason')}")
            return
        global LAST_VM
        LAST_VM = vm
        if BRIDGE is not None:
            BRIDGE.popup.emit(vm)   # 切回 GUI 线程弹窗
        _status(f"已弹出: {vm.get('champion_cn')} {'胜' if vm.get('win') else '负'}")
    except Exception as e:
        _status(f"处理对局失败: {type(e).__name__}: {e}")


def _worker():
    """拉取 worker: 从队列取 game_id 处理。"""
    while not STOP.is_set():
        try:
            gid = QUEUE.get(timeout=1)
        except queue.Empty:
            continue
        _process_game(gid)


def _test_popup():
    """托盘"测试弹窗": 有真实结果就用真实结果, 否则用样例数据演示。"""
    vm = LAST_VM or match_view.build_match_view(
        match_view.sample_details(), "ME", party_names=["阿伟", "老K", "软妹"])
    if BRIDGE is not None:
        BRIDGE.popup.emit(vm)


def _make_icon():
    pm = QPixmap(64, 64)
    pm.fill(QColor("#e8b339"))
    p = QPainter(pm)
    p.setPen(QColor("#1a1a1a"))
    p.setFont(QFont("Microsoft YaHei", 30, QFont.Weight.Bold))
    p.drawText(pm.rect(), Qt.AlignCenter, "红")
    p.end()
    return QIcon(pm)


class _Bridge(QObject):
    """跨线程信号桥: 在 GUI 线程创建, 信号跨线程自动排队到 GUI 线程。"""
    popup = Signal(object)
    popup_info = Signal(str, str)
    status = Signal(str)

    def __init__(self):
        super().__init__()
        self.windows = []                 # 持有所有已弹窗口引用, 防止 GC 一闪而过
        self.popup.connect(self._on_popup)
        self.popup_info.connect(self._on_popup_info)
        self.status.connect(self._set_tip)

    def _on_popup(self, vm):
        # 关键修复: 必须持有返回的窗口引用, 否则 Python 在事件循环返回后
        # 立即 GC 回收该窗口 -> "一闪而过"。destroyed 时从列表移除, 支持多个并存。
        w = result_popup.popup_match(vm)  # 默认不自动关闭, 手动点关闭
        self.windows.append(w)
        w.destroyed.connect(lambda *a, _w=w: self._drop(_w))

    def _on_popup_info(self, title, message):
        # 信息/提示窗(如远程战绩延迟失败), 同样持有引用防止 GC
        w = result_popup.popup_info(title, message)
        self.windows.append(w)
        w.destroyed.connect(lambda *a, _w=w: self._drop(_w))

    def _drop(self, w):
        if w in self.windows:
            self.windows.remove(w)

    @staticmethod
    def _set_tip(t):
        if TRAY is not None:
            TRAY.setToolTip(f"红包乱斗 · {t}")


def _safe_open(url):
    try:
        webbrowser.open(url)
    except Exception:
        pass


def main():
    global BRIDGE, TRAY, SRV
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)   # 关掉弹窗/主面板不退出(常驻托盘)

    BRIDGE = _Bridge()

    # ---- 常驻战绩面板: 复用原 Web 战绩系统(跟 web 一样) ----
    SRV, panel_port = aram_web.make_server()
    threading.Thread(target=SRV.serve_forever, daemon=True).start()
    panel_url = f"http://127.0.0.1:{panel_port}"
    # 启动后自动打开主战绩面板(跟原来 web 一样)
    threading.Timer(1.2, lambda: _safe_open(panel_url)).start()

    icon = _make_icon()
    if QSystemTrayIcon.isSystemTrayAvailable():
        TRAY = QSystemTrayIcon(icon)
        menu = QMenu()
        act_panel = QAction("打开战绩面板", app)
        act_panel.triggered.connect(lambda: _safe_open(panel_url))
        act_test = QAction("测试弹窗", app)
        act_test.triggered.connect(_test_popup)
        act_quit = QAction("退出", app)
        act_quit.triggered.connect(app.quit)
        menu.addAction(act_panel)
        menu.addAction(act_test)
        menu.addAction(act_quit)
        TRAY.setContextMenu(menu)
        TRAY.setToolTip("红包乱斗 · 启动中…")
        TRAY.show()
        _status("监控中 · 等待对局结束")
    else:
        # 无系统托盘环境(如某些虚拟桌面/服务器): 仍常驻监听,
        # 对局结束直接弹原生窗; 仅少一个托盘菜单入口。
        print("[红包乱斗] 系统托盘不可用, 已降级为对局结束直接弹窗模式。", flush=True)
        _status("监控中(无托盘) · 等待对局结束")

    # 后台线程: LCU 监听(检测层) + 拉取 worker
    watcher = threading.Thread(
        target=lcu_watcher.watch_gameflow,
        args=(_on_game_end, STOP, _status),
        kwargs={"seen": SEEN}, daemon=True)
    worker = threading.Thread(target=_worker, daemon=True)
    watcher.start()
    worker.start()

    _status("监控中 · 等待对局结束")
    try:
        app.exec()
    finally:
        STOP.set()
        try:
            SRV.shutdown()
        except Exception:
            pass


if __name__ == "__main__":
    main()
