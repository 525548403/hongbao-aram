# Red Packet ARAM

League of Legends Howling Abyss (ARAM) Score Query & Red Packet Distribution System

## Project Overview

Red Packet ARAM is a score query and revenue sharing tool designed specifically for the "League of Legends" Howling Abyss (ARAM) mode. By analyzing player performance in ARAM matches, it calculates individual scores and distributes "Red Packet" rewards based on those scores.

## Features

- **Match Data Acquisition**: Supports fetching match data from the Riot API (CN Server / International Servers) or local LCU (League Client Update)
- **Smart Scoring System**: Multi-dimensional scoring based on champion archetypes (Damage, Tank, Support, etc.)
- **Red Packet Distribution**: Automatically calculates and allocates red packet revenue based on player performance
- **Party Detection**: Automatically identifies 5-stack teams and allocates red packets accordingly
- **Web Interface**: Provides an intuitive web interface to view match history and distribution details
- **Local Execution**: Supports reading client data directly without relying on external APIs

## Core Modules

### Data Acquisition
- `aram_akari_framework.py` - Core framework responsible for fetching game data and LCU authentication
- `fetch_aram_scores.py` - Fetches match scores via remote API
- `fetch_lcu_scores.py` - Fetches match data via local client

### Scoring System
- `aram_score_system.py` - Core scoring algorithm, calculates scores based on champion type and performance
- `aram_champions.py` - Champion name normalization (Chinese localization)

### Red Packet System
- `aram_redpacket.py` - Red packet distribution calculation logic, supports party detection and kill rewards

### Web Service
- `aram_web.py` - HTTP server providing Web interface API
- `index.html` / `release/index.html` - Frontend pages

## Installation Instructions

### Environment Requirements
- Python 3.8+
- "League of Legends" client must be installed

### Dependency Installation
```bash
pip install requests
```

### Running Methods

#### Method 1: Web Interface
```bash
python aram_web.py
```
Then visit `http://localhost:xxxx` to view the interface

#### Method 2: Direct Execution
```bash
# Use local client data
python fetch_lcu_scores.py

# Use remote API
python fetch_aram_scores.py
```

## Usage Instructions

1. **Start Program**: Run `aram_web.py` to start the Web service
2. **View Data**: Open your browser and access the local address
3. **Set Parameters**:
   - Set single-match / total-match statistics mode
   - Set distribution rate per point (default: 10 CNY/point)
   - Set Pentakill bonus (default: 20 CNY/time)
   - Set minimum match count filter
4. **View Distribution**: The system automatically calculates and displays each player's red packet amount

## Scoring Algorithm

Scoring is calculated multi-dimensionally based on champion archetypes:
- **Damage**: Focuses on damage percentage
- **Tank**: Focuses on damage taken and crowd control
- **Support**: Focuses on healing, shielding, and protection
- **Hybrid**: Balances multiple dimensions

## Project Structure

```
hongbao-aram/
├── aram_akari_framework.py   # Core data acquisition framework
├── aram_champions.py         # Champion name processing
├── aram_redpacket.py         # Red packet distribution logic
├── aram_score_system.py      # Scoring system
├── aram_web.py               # Web service
├── fetch_aram_scores.py      # Remote data acquisition
├── fetch_lcu_scores.py       # Local client data acquisition
├── score_aram_import.py      # Data import
├── index.html                # Frontend page
└── release/                  # Packaging and release directory
```

## Notes

- This tool is for learning and communication purposes only
- Please comply with Riot Games' Terms of Service
- Red packet amounts are for entertainment simulation only and do not represent real transactions

## License

This project is for personal learning and research purposes only. Commercial use is prohibited.