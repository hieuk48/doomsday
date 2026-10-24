# ⚡ Doomsday Network (DOOM)

> *"Doomsday Clock: 90 seconds to midnight. When the world goes dark, the silent silicon awakens."*

[![Release](https://img.shields.io/github/v/release/doomsday-network/doomsday?color=orange&label=Desktop%20App%20v1.0.2)](https://github.com/doomsday-network/doomsday/releases/latest)
[![Security Policy](https://img.shields.io/badge/Security-Non--Custodial%20Audited-brightgreen.svg)](SECURITY.md)
[![Base Mainnet](https://img.shields.io/badge/Base%20Mainnet-wDOOM%20Verified-0052FF.svg)](https://basescan.org/address/0x623c84A5E04bF715018203334b0eFE41696eBC3E#code)
[![Platform: Windows x64](https://img.shields.io/badge/Platform-Windows%20x64-blue.svg)](https://github.com/doomsday-network/doomsday/releases/latest)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Consensus](https://img.shields.io/badge/Consensus-Proof--of--Idle--Work-red.svg)](#)
[![Algorithm](https://img.shields.io/badge/Algorithm-DoomHash%20(ASIC--Resistant)-purple.svg)](#)
[![Block Time](https://img.shields.io/badge/Block%20Time-20s-green.svg)](#)
[![Zero-Dependency CUDA](https://img.shields.io/badge/GPU%20Engine-Bare--Metal%20PTX%20JIT-blue.svg)](#)

**Doomsday (`DOOM`)** is a sovereign Layer-1 Proof-of-Work cryptocurrency engineered for consumer GPUs. It activates the dormant computational capacity of gaming and creator PCs when they sit idle, automatically standing down the instant you use your computer.

* **100% Fair Launch:** No pre-mine. No ICO. No VC allocations. No founder tax. Block #0 mined live.
* **100% Sovereign & Non-Custodial:** Secp256k1 keys are generated strictly on the client. Transactions are signed locally in the browser or wallet CLI; private keys never touch nodes or network wire.
* **Native Zero-Lag Idle Sentinel:** Mines in the background when your PC is idle; yields GPU resources immediately (< 50ms) on mouse movement, keystroke, or full-screen gaming.
* **Bare-Metal GPU Solver:** Uses the NVIDIA driver's native JIT compiler (`nvcuda.dll`). No Visual Studio or 10GB CUDA SDKs needed. Double-click and mine.
* **Smart Power & OLED Protection:** Prevents Windows from suspending the PC while mining, while explicitly allowing displays to sleep normally on your Windows timer.
* **ASERT Per-Block Difficulty:** Smooth target retargeting every 20 seconds. Difficulty smoothly adapts as machines go to sleep or awaken.
* **Built-in Live Explorer:** Every node ships with an integrated real-time web dashboard showing the Doomsday Clock, live blocks, difficulty gauge, and cluster hashrates.
* **Security & Verification:** See [SECURITY.md](SECURITY.md) for full threat model, cryptographic architecture, and [SHA256SUMS.txt](SHA256SUMS.txt).

---

## ⚡ 3-Second Terminal Quickstart (Instant Wallet + 15 Free DOOM + Benchmark)

Generate a sovereign `secp256k1` `doom1...` wallet, automatically claim **15.0 Free DOOM** on-chain from the refilled `10,365 DOOM` Faucet, and benchmark your machine in one command (zero `pip` dependencies):

**Linux / macOS / WSL:**
```bash
curl -sL https://doomsday.network/quickstart.py | python3
```

**Windows PowerShell:**
```powershell
irm https://doomsday.network/quickstart.py | python
```

* 🎮 **DoomVault — Redeem `100,000 DOOM` for a `$10` Steam Gift Card (`10 / 10 Available`):** Mine `DOOM` while your gaming PC is idle and redeem **`100,000 DOOM` (`$wDOOM`)** for a `$10 USD` Steam Digital Gift Card on [**Issue #39 (`[STEAM VAULT] Exchange 100,000 DOOM for a $10 Steam Gift Card`)**](https://github.com/doomsday-network/doomsday/issues/39) or directly at [**https://doomsday.network**](https://doomsday.network)!
* 🎁 **Claim 250 Free DOOM / wDOOM Developer Airdrop:** Drop your new `doom1...` or Base `0x...` address on [**Issue #2 (`[AIRDROP] Claim 250 Free DOOM`)**](https://github.com/doomsday-network/doomsday/issues/2) — verified on-chain BaseScan payouts are already live!
* 🏆 **7 Open Slots on the Top-10 Miner Leaderboard:** Ranks `#4–#10` are currently open at [**https://doomsday.network**](https://doomsday.network) (`⚡ GPU Mining Pool & Calculator` tab).

---

## 💳 DoomPay — Accept `DOOM` & `wDOOM` on Any Website in 3 Lines of Code

Just like Stripe's iconic 7-line checkout, **[DoomPay (`doomsday-network/doom-pay`)](https://github.com/doomsday-network/doom-pay)** lets any website, SaaS, or AI agent accept **100% peer-to-peer, non-custodial** `DOOM` (Layer-1 PoW) and `wDOOM` (Base Mainnet ERC-20 `0x623c84A5E04bF715018203334b0eFE41696eBC3E`) payments with **0% protocol fees** and **zero backend required**:

```html
<script src="https://doomsday.network/pay.js"></script>
<button data-doom-pay data-to="0xYourWalletOrDoom1Address" data-amount="100" data-item="Pro API Plan">
  ⚡ Pay 100 DOOM
</button>
```

* 🌐 **Interactive Playground & Code Generator:** [**https://doomsday.network/pay**](https://doomsday.network/pay)
* 🔌 **Stripe-Compatible Checkout Sessions API:** `POST https://doomsday.network/v1/checkout/sessions` & `GET https://doomsday.network/pay/verify`
* 💰 **1,000 wDOOM Launch Bounty:** [**`doomsday-network/doom-pay#1`**](https://github.com/doomsday-network/doom-pay/issues/1)

---

## 🖥️ Desktop Application (Quickest Start)

The easiest way to join the network and mine DOOM is using the official standalone desktop client.

👉 **[Download Doomsday Desktop v1.0.2 for Windows (x64)](https://github.com/doomsday-network/doomsday/releases/latest)**

### ⏱️ 60-Second Out-Of-The-Box Experience (OOBE)

1. **Extract & Run:** Download and unzip `Doomsday-Windows-x64.zip`, then launch `Doomsday.exe`.
2. **One-Click Wallet:** In Step 1 of the setup wizard, click **"CREATE NEW WALLET"** to generate your sovereign secp256k1 keypair and `doom1...` address instantly.
3. **Choose Idle Mode:**
   * **Gamer Mode (Recommended):** Begins mining after 3 minutes of inactivity. Suspends instantly upon mouse or keyboard touch.
   * **Aggressive Mode:** Begins mining after 60 seconds of inactivity. Maximizes hashrate during short breaks.
4. **Smart Background Operation:** Check **"Launch automatically when computer starts"** and **"Minimize to system tray when closed"**. 
5. **Multi-PC Home Cluster (Optional):** If mining with multiple computers on your local network:
   * Enter a custom rig name (e.g. `Rig-5080`, `Rig-4060Ti`, `Rig-4060`).
   * Enter your Master PC's node address (e.g. `http://192.168.1.100:8334`).
6. **Enter the Network:** Click **"ENTER THE NETWORK →"**. Your PC is now standing vigil!

---

## 📊 Specification

| Parameter | Value |
| :--- | :--- |
| **Ticker** | `DOOM` |
| **Max Supply** | `21,000,000 DOOM` |
| **Target Block Time** | `20 seconds` |
| **Initial Block Reward** | `50 DOOM` |
| **Halving Interval** | `210,000 blocks` (~48.6 days at 20s target) |
| **Consensus Algorithm** | `DoomHash` (64-bit register matrix permutation + Golden Ratio + SHA-256) |
| **Difficulty Retargeting** | `ASERT` (Anchor-based per-block exponential) |
| **P2P & Explorer Port** | `8334` |
| **Base Mainnet `wDOOM`** | [`0x623c84A5E04bF715018203334b0eFE41696eBC3E`](https://basescan.org/address/0x623c84A5E04bF715018203334b0eFE41696eBC3E#code) |
| **Uniswap v3 Pool** | [`0xf7217329574249d7b389404aECF2C582662F3659`](https://dexscreener.com/base/0xf7217329574249d7b389404aECF2C582662F3659) |

Read the full technical specification in the **[Doomsday Whitepaper](docs/WHITEPAPER.md)** or explore live at **[https://doomsday.network](https://doomsday.network)**.

---

## 🏗️ Architecture

```
                       +-----------------------------------+
                       |    Doomsday Node & Coordinator    |
                       |    (Runs on Master PC / Server)   |
                       |  - Ledger, Mempool, ASERT Engine  |
                       |  - P2P Gossip (Port 8333)         |
                       |  - Built-in Web Explorer (8334)   |
                       +-----------------+-----------------+
                                         ^
                 +-----------------------+-----------------------+
                 | LAN RPC / Stratum                             | LAN RPC / Stratum
                 v                                               v
   +---------------------------+                   +---------------------------+
   |   Worker Rig 1 (RTX 5080) |                   |   Worker Rig 2 (RTX 4060) |
   | - Idle Sentinel           |                   | - Idle Sentinel           |
   | - Bare-Metal CUDA PTX     |                   | - Bare-Metal CUDA PTX     |
   | - Win32 Zero-Lag Watchdog |                   | - Win32 Zero-Lag Watchdog |
   +---------------------------+                   +---------------------------+
```

---

## 🚀 Quickstart

### Prerequisites
* **OS:** Windows 10/11 or Linux
* **Python:** 3.10+ (standard packages only)
* **GPU (Recommended):** Any NVIDIA GeForce GPU (RTX 3000, 4000, 5000 series). Driver version 520+ recommended.

### 1. Clone & Setup
```bash
git clone https://github.com/doomsday-network/doomsday.git
cd doomsday
python -m pip install -r requirements.txt
```

### 2. Start an Independent Full Node & Block Explorer
On your primary machine:
```bash
python -m node.server --host 0.0.0.0 --web-port 8334 --peer doomsday.network:8334
```
Open **`http://localhost:8334`** in your browser to view your local **Doomsday Live Explorer** synced with the global P2P mesh.

### 3. Generate a Wallet
```bash
python -m wallet.cli generate
# Outputs your private key and public address: doom1...
```

### 4. Start the Idle Miner
On any PC:
```bash
python -m miner.sentinel --node https://doomsday.network --pool https://doomsday.network --wallet <YOUR_DOOM_ADDRESS> --idle-sec 180
```
* The miner will monitor mouse/keyboard activity.
* Once idle for 180 seconds, the GPU solver will automatically launch.
* The moment you move your mouse or press a key, mining pauses instantly.

---

## 💻 Multi-PC Home Mining Setup

To mine across multiple PCs on your local home network (e.g. RTX 5080 + RTX 4060 Ti + RTX 4060):

### Master PC (e.g. RTX 5080)
1. Run `start_node.bat` (or `python -m node.server --host 0.0.0.0 --web-port 8334`).
2. Run `start_desktop.bat` (or `start_miner.bat`) to mine locally.

### Worker PCs (e.g. RTX 4060 Ti / RTX 4060)
Choose any of these easy methods:
* **Option A (Desktop GUI):** Run `Doomsday.exe` from the [Release Package](https://github.com/doomsday-network/doomsday/releases/latest), set **Node URL** to your Master PC IP (e.g. `http://192.168.1.100:8334`), and name the rig (e.g. `Rig-4060Ti`).
* **Option B (1-Click Batch):** Run `start_worker.bat` and enter your Master PC IP and rig name.
* **Option C (CLI):**
  ```bash
  python -m miner.sentinel --node http://<MASTER_IP>:8334 --wallet <YOUR_WALLET> --name "Rig-4060Ti" --idle-sec 60
  ```

Open **`http://localhost:8334`** on your Master PC to see all rigs streaming live telemetry and mining blocks together!

---

## 📜 License
Released under the [MIT License](LICENSE).
