# -*- coding: utf-8 -*-
"""
对局结束检测 —— 诊断脚本(排查"游戏结束没弹窗")
================================================================
在**已登录英雄联盟客户端**的机器上运行(国服建议开加速器):

    python diagnose_detect.py

它会依次验证 4 个环节, 明确指出卡在哪一步:
  1) LCU 鉴权 + 能否读到 gameflow 会话
  2) websocket 能否连上并收到事件
  3) SGP 能否拉到战绩列表(双通道检测的兜底)
  4) 最近一局大乱斗的 DETAILS 能否取到并算出评分
"""
import json
import os
import sys
import time
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from aram_akari_framework import (lcu_auth, get_entitlements, SgpFetcher,
                                  latest_aram_gameid, parse_sgp_summary)
import match_view

OK, BAD = "  [OK]  ", "  [!!]  "
results = []


def step(name):
    print("\n" + "=" * 62)
    print(name)
    print("=" * 62)


def mark(ok, msg, detail=""):
    results.append((name_last, ok))
    print((OK if ok else BAD) + msg + (("  -> " + str(detail)) if detail else ""))
    return ok


name_last = ""

# ---------- 1) LCU 鉴权 ----------
step("1) LCU 鉴权(英雄联盟客户端是否已登录)")
name_last = "1) LCU 鉴权"
base = s = cfg = token = puuid = None
try:
    base, s, cfg = lcu_auth()
    mark(True, "LCU 连接成功", base)
    try:
        token, puuid = get_entitlements(base, s)
        mark(True, "entitlements 令牌获取成功", "puuid=" + str(puuid)[:12] + "...")
    except Exception as e:
        mark(False, "取 entitlements 失败", f"{type(e).__name__}: {e}")
        print("\n客户端可能未完全登录, 请登录后重试。")
        sys.exit(1)
except Exception as e:
    mark(False, "LCU 连接失败", f"{type(e).__name__}: {e}")
    print("\n请先启动并登录英雄联盟客户端。")
    sys.exit(1)

# ---------- 2) gameflow 会话 ----------
step("2) gameflow 会话(对局状态)")
name_last = "2) gameflow"
try:
    r = s.get(base + "/lol-gameflow/v1/session", timeout=8)
    if r.status_code == 200:
        sess = r.json()
        phase = sess.get("phase")
        gd = sess.get("gameData") or {}
        gid = gd.get("gameId") or sess.get("gameId")
        mark(True, "读到当前 phase", phase)
        print("         gameData.gameId =", gid)
        if not gid:
            print("         (当前不在对局中, 无 gameId 属正常)")
    else:
        mark(False, "gameflow 返回异常", f"HTTP {r.status_code}")
except Exception as e:
    mark(False, "gameflow 请求失败", f"{type(e).__name__}: {e}")

# ---------- 3) websocket 事件 ----------
step("3) websocket 事件总线(通道A)")
name_last = "3) websocket"
got = []
def _on(gid):
    got.append(gid)
stop = threading.Event()
def run_ws():
    try:
        import lcu_watcher
        lcu_watcher.watch_gameflow(got.append, stop_event=stop,
                                   seen=set(), reconnect_delay=1)
    except Exception as e:
        got.append(("ERR", f"{type(e).__name__}: {e}"))
threading.Thread(target=run_ws, daemon=True).start()
time.sleep(6)
stop.set()
if got and isinstance(got[0], tuple):
    mark(False, "websocket 连接失败", got[0][1])
else:
    mark(True, "websocket 已连接并监听 6 秒(无事件属正常, 需等对局结束)")

# ---------- 4) SGP 战绩 ----------
step("4) SGP 战绩(通道B 兜底 / 弹窗数据源)")
name_last = "4) SGP"
fetcher = None
try:
    rso = (cfg or {}).get("rsoPlatformId", "HN10")
    region = (cfg or {}).get("region", "TENCENT")
    fetcher = SgpFetcher(token, rso, region)
    print("         SGP host =", fetcher.host)
    summary = fetcher.get_summary(puuid, 5, start_index=0)
    games = summary.get("games", [])
    if isinstance(games, dict):
        games = games.get("games", [])
    aram = parse_sgp_summary(summary, puuid)
    mark(True, "拉到战绩列表", f"{len(games)} 局, 其中大乱斗 {len(aram)} 局")
    gid = latest_aram_gameid(fetcher, puuid)
    mark(gid is not None, "最近一场大乱斗 gameId", gid)
except Exception as e:
    mark(False, "SGP 拉取失败(国服需加速器)", f"{type(e).__name__}: {str(e)[:120]}")

# ---------- 5) DETAILS + 评分 ----------
step("5) 最近一局 DETAILS + 评分(弹窗内容)")
name_last = "5) DETAILS"
if fetcher is not None and gid:
    try:
        d = fetcher.get_details(gid)
        parts, got_gid = match_view.participants_from_details(d)
        mark(len(parts) >= 10, f"取到 {len(parts)} 名参与者")
        vm = match_view.build_match_view(d, puuid, party_names=None)
        if vm and not vm.get("skip"):
            mark(True, "评分计算成功(弹窗将显示)",
                 f"{vm.get('champion_cn')} {'胜' if vm.get('win') else '负'}")
        elif vm and vm.get("skip"):
            mark(False, "被判定为非大乱斗", vm.get("reason"))
        else:
            mark(False, "评分计算返回空(可能未找到我方数据)")
    except Exception as e:
        mark(False, "DETAILS 拉取失败(对局刚结束时正常, 稍后重试)",
             f"{type(e).__name__}: {str(e)[:120]}")
else:
    print("  [--]  跳过(前一步未拿到 gameId)")

# ---------- 汇总 ----------
print("\n" + "=" * 62)
print("诊断汇总")
print("=" * 62)
fails = [n for n, ok in results if not ok]
if not fails:
    print("全部通过 —— 检测链路本身正常。")
    print("若仍不弹窗, 可能是: 托盘程序未运行 / 弹窗被拦截 / 旧进程占端口。")
    print("排查: 1) 托盘图标是否存在  2) 任务管理器结束旧 aram_score_desktop.exe")
else:
    print("以下环节有问题:")
    for n in fails:
        print("  -", n)
