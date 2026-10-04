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

关键修复点(游戏结束不弹窗):
  检测改为**双通道**, 任一命中即触发, 不再单点依赖 gameflow 事件:
  1) 通道A —— LCU 事件总线(websocket): 跨所有 session 事件持续跟踪
     当前 gameId; 检测到结束阶段时优先用本事件 gameId、缺失则回退跟踪值。
     修复了 gameflow-phase 事件(纯字符串, 自身无 gameId)与 session 在
     EndOfGame 瞬间 gameData 为空时整局检测不到的问题。
  2) 通道B —— SGP 战绩轮询(借鉴 LeagueAkari): 定期拉取战绩列表, 当
     "最新一局 gameId" 发生变化即说明又打完一场。战绩入库与客户端事件
     无关, 因此不受 websocket 订阅失败 / phase 取值差异影响, 是兜底保障。
"""
import json
import time
import threading

import websocket  # websocket-client
from aram_akari_framework import (lcu_auth, get_entitlements, SgpFetcher,
                                  latest_aram_gameid)

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


# ============================================================
# 检测层 2: SGP 战绩轮询(借鉴 LeagueAkari)
# ============================================================
def watch_sgp_poll(on_game_end, stop_event=None, status_cb=None,
                   seen=None, interval=60.0, warmup=2):
    """轮询 SGP 战绩列表, 通过"最新一局 gameId 变化"判断又打了一把。

    为什么要这一层: gameflow 的 phase 事件在国服客户端上时有时无
    (gameData 为空 / websocket 订阅不生效), 单靠它检测会整局漏掉。
    而"战绩列表多出新的一局"是**唯一可靠且与客户端事件无关**的信号 ——
    LeagueAkari 判断"又打了一把"用的正是这个思路。

    warmup: 启动后前 N 次只记录基线不触发, 避免开机时把"上一局"误判为新局。
    """
    seen = seen if seen is not None else set()
    stop_event = stop_event or threading.Event()
    last_gid = [None]
    ticks = [0]

    def _status(t):
        if status_cb:
            status_cb(t)

    # 凭据/抓取器按需重建(长期运行可能因令牌过期需刷新)
    state = {"base": None, "s": None, "cfg": None, "puuid": None}

    def _ensure():
        if state["s"] is not None:
            return
        base, s, cfg = lcu_auth()
        token, puuid = get_entitlements(base, s)
        rso = (cfg or {}).get("rsoPlatformId", "HN10")
        region = (cfg or {}).get("region", "TENCENT")
        state.update({"base": base, "s": s, "cfg": cfg, "puuid": puuid,
                      "fetcher": SgpFetcher(token, rso, region).set_puuid(puuid)})

    _status("监控中 · 等待对局结束（SGP 轮询已启动）")
    while not stop_event.is_set():
        try:
            _ensure()
            gid = latest_aram_gameid(state["fetcher"], state["puuid"])
            ticks[0] += 1
            if gid:
                if last_gid[0] is None:
                    # 首次: 建立基线
                    last_gid[0] = gid
                    seen.add(gid)
                    if ticks[0] <= warmup:
                        _status(f"监控中 · 已建立战绩基线({gid[-6:]})")
                elif gid != last_gid[0]:
                    # 最新一局变了 => 刚打完一场
                    last_gid[0] = gid
                    if gid not in seen:
                        seen.add(gid)
                        _status(f"检测到新对局入库 (game_id={gid})")
                        try:
                            on_game_end(gid)
                        except Exception as e:
                            _status(f"处理对局出错: {e}")
        except Exception as e:
            # 令牌过期/网络波动: 丢弃抓取器, 下轮重建
            state["s"] = None
            state["puuid"] = None
            state.pop("fetcher", None)
            _status(f"战绩轮询暂不可用({type(e).__name__})，稍后重试")
        if stop_event.wait(interval):
            break


if __name__ == "__main__":
    # 简易自测: 打印收到的 game_id(需本机已登录英雄联盟)
    def _print(gid):
        print("[对局结束] game_id =", gid)

    def _status(t):
        print("[状态]", t)

    print("监听 LCU 事件总线 + SGP 战绩轮询(按 Ctrl+C 退出)…")
    stop = threading.Event()
    t1 = threading.Thread(target=watch_gameflow, args=(_print,),
                          kwargs={"status_cb": _status}, daemon=True)
    t2 = threading.Thread(target=watch_sgp_poll, args=(_print,),
                          kwargs={"status_cb": _status, "stop_event": stop},
                          daemon=True)
    t1.start()
    t2.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n已退出")
