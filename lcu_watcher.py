# -*- coding: utf-8 -*-
"""
LCU 事件总线(检测层)
================================================================
订阅英雄联盟客户端本地 websocket 的 gameflow 会话事件, 检测"对局结束"
(phase 进入 EndOfGame / WaitingForStats / PreEndOfGame), 回调
on_game_end(game_id)。这是"自动感知游戏结束并弹窗"的核心。

复用 aram_akari_framework.lcu_auth() 拿到的 LCU 端口与 Basic 令牌。

LCU websocket 协议(逆向自 Riot LCU):
  - 连接 wss://127.0.0.1:<port>/ , 请求头带 Basic 鉴权
  - 订阅: 发送 [5, "OnJsonApiEvent", <uri>]
  - 事件: 收到 [8, "OnJsonApiEvent_<uri>", <uri|null>, <data>]

关键修复点(游戏结束不弹窗的常见根因):
  - lol-gameflow/v1/gameflow-phase 事件返回的是**纯字符串 phase**(如 "EndOfGame"),
    自身不带 gameId, 旧逻辑只能靠会话事件在该瞬间恰好带 gameId, 否则整局检测不到。
  - 现改为: 跨所有 session 事件**持续跟踪当前 gameId**; 检测到结束阶段时,
    优先用本事件自带的 gameId, 缺失则回退到最近一次跟踪到的 gameId,
    保证 EndOfGame 一定能拿到对局号并触发弹窗。
"""
import json
import threading

import websocket  # websocket-client
from aram_akari_framework import lcu_auth

# 这些阶段表示"这局已经打完, 可以拉战绩了"
END_PHASES = {"EndOfGame", "WaitingForStats", "PreEndOfGame"}
# 订阅的两个 uri: 会话(含 gameData.gameId) + 纯阶段字符串
WATCH_URIS = ["lol-gameflow/v1/session", "lol-gameflow/v1/gameflow-phase"]


def _extract_game_id(data):
    """从 gameflow 会话对象里取 gameId(字符串)。"""
    if not isinstance(data, dict):
        return None
    gd = data.get("gameData") or {}
    gid = gd.get("gameId") or data.get("gameId")
    if gid:
        return str(gid)
    mp = data.get("map") or {}
    gid = mp.get("gameId")
    return str(gid) if gid else None


def _phase_of(data):
    """会话对象或纯阶段字符串都兼容, 返回 phase 字符串或 None。"""
    if isinstance(data, dict):
        return data.get("phase")
    if isinstance(data, str):
        return data
    return None


def watch_gameflow(on_game_end, stop_event=None, status_cb=None,
                   seen=None, reconnect_delay=5.0, recv_timeout=30):
    """阻塞式监听(应在后台线程调用)。持续运行, 断线自动重连。
    仅对"新"的 game_id 调用 on_game_end(去重, 防止 EndOfGame 多次触发重复弹窗)。

    on_game_end(game_id): 回调, 在 ws 线程调用, 调用方需线程安全地更新 GUI。
    status_cb(text): 可选, 上报连接状态(用于托盘 tooltip)。
    stop_event:    threading.Event, set 后退出。
    """
    seen = seen if seen is not None else set()
    stop_event = stop_event or threading.Event()
    # 跨事件持续跟踪的当前 gameId: 即便 EndOfGame 当次事件没带 gameId,
    # 也能回退到上一刻(InProgress / PreEndOfGame 等)跟踪到的 gameId。
    last_game_id = [None]

    while not stop_event.is_set():
        try:
            if status_cb:
                status_cb("正在连接 LCU 事件总线…")
            base, s, _cfg = lcu_auth()
            port = base.split(":")[-1]
            auth = s.headers.get("Authorization")
            if not auth:
                raise RuntimeError("LCU 鉴权头缺失")
            ws_url = f"wss://127.0.0.1:{port}/"
            ws = websocket.create_connection(
                ws_url, header=[auth], sslopt={"cert_reqs": 0},
                skip_utf8_validation=True, timeout=recv_timeout)
            for uri in WATCH_URIS:
                ws.send(json.dumps([5, "OnJsonApiEvent", uri]))
            if status_cb:
                status_cb("监控中 · 等待对局结束")

            while not stop_event.is_set():
                try:
                    raw = ws.recv()
                except websocket.WebSocketTimeoutException:
                    continue  # 心跳超时, 连接仍在, 继续收
                except Exception:
                    break  # 连接断开, 跳出内层重连
                if not raw:
                    break
                try:
                    arr = json.loads(raw)
                except Exception:
                    continue
                # arr 形如 [op, "OnJsonApiEvent...", uri, data]
                if not (isinstance(arr, list) and len(arr) >= 4):
                    continue
                evt = arr[1]
                if not (isinstance(evt, str) and evt.startswith("OnJsonApiEvent")):
                    continue
                uri = arr[2]
                data = arr[3]
                # 1) 持续跟踪 session 里的 gameId(所有阶段都带, 作为回退来源)
                if uri == "lol-gameflow/v1/session" and isinstance(data, dict):
                    gid = _extract_game_id(data)
                    if gid:
                        last_game_id[0] = gid
                # 2) 检测结束阶段 -> 触发弹窗
                phase = _phase_of(data)
                if phase in END_PHASES:
                    gid = _extract_game_id(data) or last_game_id[0]
                    if gid and gid not in seen:
                        seen.add(gid)
                        if status_cb:
                            status_cb(f"检测到对局结束 (phase={phase}, game_id={gid})")
                        try:
                            on_game_end(gid)
                        except Exception as e:  # 回调出错不应中断监听
                            if status_cb:
                                status_cb(f"处理对局出错: {e}")
            try:
                ws.close()
            except Exception:
                pass
        except Exception as e:
            if status_cb:
                status_cb(f"连接中断: {type(e).__name__}, {reconnect_delay}s 后重连")
            if stop_event.wait(reconnect_delay):
                break  # 被外部 set, 退出


if __name__ == "__main__":
    # 简易自测: 打印收到的 phase / game_id(需本机已登录英雄联盟)
    def _print(gid):
        print("[对局结束] game_id =", gid)

    def _status(t):
        print("[状态]", t)

    print("监听 LCU 事件总线(按 Ctrl+C 退出)…")
    try:
        watch_gameflow(_print, status_cb=_status)
    except KeyboardInterrupt:
        print("\n已退出")
