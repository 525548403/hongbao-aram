# 红包ARAM (Hongbao ARAM)

英雄联盟极地大乱斗（ARAM）成绩查询与红包分红系统

## 项目简介

红包ARAM 是一款专为《英雄联盟》极地大乱斗模式设计的成绩查询与收益分红工具。通过分析玩家在 ARAM 比赛中的表现，计算个人评分，并根据评分发放"红包"奖励。

## 功能特性

- **比赛数据获取**：支持从拳头 API（国服/国际服）或本地 LCU（英雄联盟客户端）获取比赛数据
- **智能评分系统**：基于英雄画像（伤害型、坦克型、辅助型等）进行多维度评分
- **红包分红**：根据玩家表现自动计算并分配红包收益
- **组队检测**：自动识别五排车队，自动分配红包
- **Web 界面**：提供直观的 Web 界面查看比赛记录和分红详情
- **本地运行**：支持直接读取客户端数据，无需外部 API

## 核心模块

### 数据获取
- `aram_akari_framework.py` - 核心框架，负责获取游戏数据、LCU 认证
- `fetch_aram_scores.py` - 通过远程 API 获取比赛成绩
- `fetch_lcu_scores.py` - 通过本地客户端获取比赛数据

### 评分系统
- `aram_score_system.py` - 核心评分算法，根据英雄类型和表现计算得分
- `aram_champions.py` - 英雄名称规范化（中文化）

### 红包系统
- `aram_redpacket.py` - 红包分红计算逻辑，支持组队检测、击杀奖励

### Web 服务
- `aram_web.py` - HTTP 服务器，提供 Web 界面 API
- `index.html` / `release/index.html` - 前端页面

## 安装说明

### 环境要求
- Python 3.8+
- 需安装《英雄联盟》客户端

### 依赖安装
```bash
pip install requests
```

### 运行方式

#### 方式一：Web 界面
```bash
python aram_web.py
```
然后访问 `http://localhost:xxxx` 查看界面

#### 方式二：直接运行
```bash
# 使用本地客户端数据
python fetch_lcu_scores.py

# 使用远程 API
python fetch_aram_scores.py
```

## 使用说明

1. **启动程序**：运行 `aram_web.py` 启动 Web 服务
2. **查看数据**：打开浏览器访问本地地址
3. **设置参数**：
   - 设置单场/总场统计模式
   - 设置分红单价（默认 10 元/分）
   - 设置五杀奖励（默认 20 元/次）
   - 设置最低场次过滤
4. **查看分红**：系统自动计算并展示每位玩家的红包金额

## 评分算法

评分基于英雄画像进行多维度计算：
- **伤害型**：侧重伤害占比
- **坦克型**：侧重承伤和控制
- **辅助型**：侧重治疗、护盾和保护
- **混合型**：兼顾多个维度

## 项目结构

```
hongbao-aram/
├── aram_akari_framework.py   # 核心数据获取框架
├── aram_champions.py         # 英雄名称处理
├── aram_redpacket.py         # 红包分红逻辑
├── aram_score_system.py      # 评分系统
├── aram_web.py               # Web 服务
├── fetch_aram_scores.py      # 远程数据获取
├── fetch_lcu_scores.py       # 本地客户端数据获取
├── score_aram_import.py      # 数据导入
├── index.html                # 前端页面
└── release/                  # 打包发布目录
```

## 注意事项

- 本工具仅供学习交流使用
- 请遵守拳头公司服务条款
- 红包金额仅为娱乐模拟，非真实交易

## 许可证

本项目仅供个人学习研究使用，禁止商业用途。