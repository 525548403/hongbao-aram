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
import subprocess

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
# 游戏内进程名(对局进行中才会出现)。它一消失 = 对局刚结束, 这是**本地即时信号**,
# 比等 SGP 入库快得多(后者通常要等回到大厅/退出房间后才可查)。
GAME_PROCESS = "league of legends.exe"

# 进程退出时置位, 由 SGP 轮询线程读取并切换到快频轮询(跨线程轻量信号)
_fast_flag = {"on": False}


def game_running():
    """游戏内进程是否在运行(用于判断"是否在对局中")。失败时返回 None(未知)。"""
    try:
        out = subprocess.run(["tasklist", "/FO", "CSV", "/NH", "/FI",
                              f"IMAGENAME eq {GAME_PROCESS}"],
                             capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=15)
        if out.returncode != 0:
            return None
        return GAME_PROCESS in (out.stdout or "").lower()
    except Exception:
        return None


def watch_game_process(on_game_end, stop_event=None, status_cb=None,
                       seen=None, interval=2.0, settle=6.0):
    """监控游戏进程: 由"在运行"变为"已退出"时, 立即回调一次。

    这是最快的通道 —— 进程退出即刻感知, 不等 SGP 入库。
    退出后延迟 settle 秒再回调, 给战绩入库留出时间; 真正的数据获取与重试
    由调用方的 _fetch_match_data 负责(它会轮询等待)。
    每次"检测到"通过 seen 里的 game_process 标记防重复触发。
    """
    seen = seen if seen is not None else set()
    stop_event = stop_event or threading.Event()
    in_game = [False]      # 上一轮是否在对局中
    reported = [False]     # 本次"结束"是否已上报

    while not stop_event.is_set():
        try:
            now = game_running()
            if now is None:
                pass# 检测不了, 忽略本轮
            elif now and not in_game[0]:
                in_game[0] = True
                reported[0] = False
                if status_cb:
                    status_cb("检测到对局开始 · 等待结束")
            elif (not now) and in_game[0] and not reported[0]:
                # 游戏进程刚退出 -> 对局结束
                in_game[0] = False
                reported[0] = True
                _fast_flag["on"] = True   # 通知 SGP 轮询切快频
                if status_cb:
                    status_cb(f"检测到游戏进程退出，{int(settle)}s 后拉取战绩…")
                if stop_event.wait(settle):
                    break
                try:
                    on_game_end("__PROCESS_EXIT__")
                except Exception as e:
                    if status_cb:
                        status_cb(f"处理对局出错: {e}")
        except Exception as e:
            if status_cb:
                status_cb(f"进程监控异常: {type(e).__name__}")
        if stop_event.wait(interval):
            break


def watch_sgp_poll(on_game_end, stop_event=None, status_cb=None,
                   seen=None, interval=20.0, warmup=2, fast_window=150.0):
    """轮询 SGP 战绩列表, 通过"最新一局 gameId 变化"判断又打了一把。

    为什么要这一层: gameflow 的 phase 事件在国服客户端上不可用(Riot Client 端口
    不提供 lol-* 接口), 而 SGP 战绩入库又慢于游戏进程退出。
    "战绩列表多出新的一局"与客户端事件无关, 是**最终兜底保障**。

    interval: 平时轮询间隔(默认 20s, 兼顾及时性与请求量)。
    fast_window: 进程退出后这段时间内改用快频轮询(fast_interval),
    尽快拿到新局gameId。
    warmup: 启动后前 N 次只记录基线不触发, 避免开机时把"上一局"误判为新局。
    """
    seen = seen if seen is not None else set()
    stop_event = stop_event or threading.Event()
    last_gid = [None]
    ticks = [0]
    fast_until = [0.0]      # 快频轮询截止时间戳

    def _status(t):
        if status_cb:
            status_cb(t)

    def _enter_fast(seconds):
        fast_until[0] = max(fast_until[0], time.time() + seconds)

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
        # 进程退出通道已进入快频窗口 -> 立即切快频抢新局
        if _fast_flag["on"]:
            _fast_flag["on"] = False
            _enter_fast(fast_window)
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
                    fast_until[0] = 0.0   # 已拿到新局, 退出快频
        except Exception as e:
            # 令牌过期/网络波动: 丢弃抓取器, 下轮重建
            state["s"] = None
            state["puuid"] = None
            state.pop("fetcher", None)
            _status(f"战绩轮询暂不可用({type(e).__name__})，稍后重试")
        # 快频窗口内(进程刚退出)用短间隔抢新局, 否则用常规间隔
        wait = 3.0 if time.time() < fast_until[0] else interval
        if stop_event.wait(wait):
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
