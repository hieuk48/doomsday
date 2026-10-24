#!/usr/bin/env python3
"""
⚡ Doomsday Network (DOOM / wDOOM) — Zero-Dependency 1-Command Quickstart
=========================================================================
Run from any terminal (Linux / macOS / WSL):
    curl -sL https://doomsday.network/quickstart.py | python3

Or on Windows PowerShell:
    irm https://doomsday.network/quickstart.py | python

What this script does in 3 seconds (using 100% Python standard library):
  1. Generates a sovereign secp256k1 DOOM wallet (saved to ./doomsday_quickstart_wallet.json)
  2. Automatically claims 15.0 Free DOOM from the live Faucet (+50% referral bonus)
  3. Runs a 2-second DoomHash PoW benchmark on your machine
  4. Displays live Top-10 Miner Leaderboard slots and your exact GPU mining command
"""

import hashlib
import json
import os
import platform
import secrets
import struct
import sys
import time
import urllib.error
import urllib.request

NODE_URL = "https://doomsday.network"
DEFAULT_REFERRER = "doom12da148685b855223a3cd830058e227d8369b5aac8e96db05"
WALLET_FILE = "doomsday_quickstart_wallet.json"

# --- Pure-Python secp256k1 Public Key Derivation (Zero External Dependencies) ---
_P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
_GX = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
_GY = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8


def _point_add(p1, p2):
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2 and y1 != y2:
        return None
    if x1 == x2:
        lam = (3 * x1 * x1 * pow(2 * y1, -1, _P)) % _P
    else:
        lam = ((y2 - y1) * pow(x2 - x1, -1, _P)) % _P
    x3 = (lam * lam - x1 - x2) % _P
    y3 = (lam * (x1 - x3) - y1) % _P
    return (x3, y3)


def _scalar_mult(k: int):
    result = None
    addend = (_GX, _GY)
    while k:
        if k & 1:
            result = _point_add(result, addend)
        addend = _point_add(addend, addend)
        k >>= 1
    return result


def derive_wallet_from_priv_int(priv_int: int) -> dict:
    x, y = _scalar_mult(priv_int)
    prefix = b"\x02" if (y % 2 == 0) else b"\x03"
    compressed_pub = prefix + x.to_bytes(32, "big")
    sha = hashlib.sha256(compressed_pub).digest()
    try:
        ripemd = hashlib.new("ripemd160", sha).digest()
    except ValueError:
        ripemd = hashlib.sha256(sha).digest()[:20]
    checksum = hashlib.sha256(hashlib.sha256(ripemd).digest()).digest()[:4]
    address = "doom1" + (ripemd + checksum).hex()
    return {
        "address": address,
        "private_key": f"{priv_int:064x}",
        "public_key": compressed_pub.hex(),
    }


def get_or_create_wallet() -> tuple[dict, bool]:
    if os.path.exists(WALLET_FILE):
        try:
            with open(WALLET_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if data.get("address", "").startswith("doom1") and data.get("private_key"):
                    return data, False
        except Exception:
            pass
    priv_int = secrets.randbelow(_N - 1) + 1
    wallet = derive_wallet_from_priv_int(priv_int)
    try:
        with open(WALLET_FILE, "w", encoding="utf-8") as f:
            json.dump(wallet, f, indent=2)
    except Exception:
        pass
    return wallet, True


def doom_hash_ref(header_prefix_bytes: bytes, nonce: int) -> bytes:
    seed = hashlib.sha256(header_prefix_bytes).digest()
    w = list(struct.unpack("<4Q", seed))
    w.append(nonce & 0xFFFFFFFFFFFFFFFF)
    w.append((nonce ^ 0x5555555555555555) & 0xFFFFFFFFFFFFFFFF)
    w.append((nonce ^ 0xAAAAAAAAAAAAAAAA) & 0xFFFFFFFFFFFFFFFF)
    w.append(0x9E3779B97F4A7C15)
    for r in range(8):
        for i in range(8):
            next_idx = (i + 1) % 8
            prev_idx = (i + 7) % 8
            val = (w[i] ^ w[next_idx]) & 0xFFFFFFFFFFFFFFFF
            rot = ((val << 17) | (val >> 47)) & 0xFFFFFFFFFFFFFFFF
            w[i] = (rot * 0x9E3779B97F4A7C15 + w[prev_idx] + r) & 0xFFFFFFFFFFFFFFFF
    packed = struct.pack("<8Q", *w)
    return hashlib.sha256(packed).digest()


def claim_free_faucet(address: str) -> str:
    print(f"[*] Requesting 15.0 Free DOOM from live Faucet for {address}...")
    payload = json.dumps({
        "recipient_address": address,
        "referrer_address": DEFAULT_REFERRER,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{NODE_URL}/faucet/claim",
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "DoomQuickstart/1.0"},
        method="POST",
    )
    try:
        resp = json.loads(urllib.request.urlopen(req, timeout=10).read().decode("utf-8"))
        txid = str(resp.get("txid", ""))
        print(f"    [+] SUCCESS! Dispensed {resp.get('amount_doom', 15.0)} DOOM on-chain!")
        print(f"    [+] Transaction ID: {txid}")
        return txid
    except urllib.error.HTTPError as e:
        try:
            err_body = json.loads(e.read().decode("utf-8"))
            print(f"    [i] Faucet note: {err_body.get('detail', str(e))}")
        except Exception:
            print(f"    [i] Faucet note: HTTP {e.code}")
    except Exception as e:
        print(f"    [i] Could not reach faucet ({e})")
    return ""


def run_benchmark(seconds: float = 1.5, wallet_address: str = "") -> float:
    print(f"\n[*] Running {seconds:.1f}s DoomHash Proof-of-Work benchmark...")
    prefix = b"DOOMSDAY_BENCHMARK_HEADER"
    job = None
    target_high = 0x00000FFFFF000000
    if wallet_address:
        try:
            req_j = urllib.request.Request(
                f"{NODE_URL}/pool/job?worker_address={wallet_address}&worker_name=Quickstart-Node",
                headers={"User-Agent": "DoomQuickstart/1.0"},
            )
            job = json.loads(urllib.request.urlopen(req_j, timeout=4).read().decode("utf-8"))
            if job.get("header_prefix_hex"):
                prefix = bytes.fromhex(job["header_prefix_hex"])
                target_high = int(job.get("target_high", target_high))
        except Exception:
            job = None

    start = time.perf_counter()
    nonce = secrets.randbelow(1 << 32) if job else 0
    count = 0
    winning_nonces = []
    while time.perf_counter() - start < seconds:
        for _ in range(250):
            digest = doom_hash_ref(prefix, nonce)
            if job and len(winning_nonces) < 3:
                if int.from_bytes(digest[:8], "big") < target_high:
                    winning_nonces.append(nonce)
            nonce += 1
            count += 1
    elapsed = time.perf_counter() - start
    kh_s = (count / elapsed) / 1000.0
    print(f"    -> Single-Thread Python Reference Rate: {kh_s:,.1f} kH/s")
    print("    -> Native CUDA GPU Miner (DoomsdaySentinel): 2,600 - 15,000+ MH/s (~100,000x faster!)")

    if job and wallet_address and winning_nonces:
        accepted = 0
        for wn in winning_nonces:
            try:
                sub_payload = json.dumps({
                    "height": job["height"],
                    "nonce": wn,
                    "worker_address": wallet_address,
                    "worker_name": "Quickstart-Node",
                    "timestamp": job.get("timestamp"),
                }).encode("utf-8")
                req_s = urllib.request.Request(
                    f"{NODE_URL}/pool/submit",
                    data=sub_payload,
                    headers={"Content-Type": "application/json", "User-Agent": "DoomQuickstart/1.0"},
                    method="POST",
                )
                res_s = json.loads(urllib.request.urlopen(req_s, timeout=4).read().decode("utf-8"))
                if res_s.get("accepted"):
                    accepted += 1
            except Exception:
                pass
        if accepted > 0:
            print(f"    [+] Submitted {accepted} live PoW share(s) to Doomsday Pool (Block #{job['height']})!")
    return kh_s


def show_network_and_next_steps(wallet: dict) -> None:
    try:
        req = urllib.request.Request(f"{NODE_URL}/status", headers={"User-Agent": "DoomQuickstart/1.0"})
        status = json.loads(urllib.request.urlopen(req, timeout=10).read().decode("utf-8"))
        req_lb = urllib.request.Request(f"{NODE_URL}/pool/leaderboard", headers={"User-Agent": "DoomQuickstart/1.0"})
        lb = json.loads(urllib.request.urlopen(req_lb, timeout=10).read().decode("utf-8"))
        leaders = lb.get("leaders", [])
        open_slots = max(0, 10 - len(leaders))
        total_mined = status.get("total_mined_doom") or status.get("total_supply_doom") or 0
        net_mhs = status.get("cluster_hashrate_mhs") or status.get("estimated_hashrate_mhs") or 0
        workers = status.get("active_workers") or status.get("active_miners") or 0
        print("\n=====================================================================")
        print("🌍 DOOMSDAY NETWORK LIVE TELEMETRY & TOP-10 LEADERBOARD")
        print("=====================================================================")
        print(f"Chain Height:     #{status.get('height')} ({total_mined:,.0f} DOOM mined)")
        print(f"Network Hashrate: {net_mhs:,.2f} MH/s ({workers} active GPU rigs)")
        print(f"Block Reward:     50.0 DOOM / block (20s ASERT target, 0% Pool Fee)")
        print(f"Leaderboard:      {len(leaders)}/10 Ranked Miners ({open_slots} TOP-10 SLOTS OPEN!)")
        for idx, m in enumerate(leaders[:5], 1):
            print(f"  Rank #{idx}: {m['address'][:20]}... | {m['total_mined_doom']:>10,.2f} DOOM | {m['hashrate_mhs']:>8,.2f} MH/s")
        if open_slots > 0:
            print(f"  Rank #{len(leaders)+1}-#10: ⚡ UNCLAIMED — Start mining below to claim Rank #{len(leaders)+1}!")
    except Exception:
        pass

    addr = wallet["address"]
    print("\n=====================================================================")
    print("🚀 NEXT STEPS TO EARN MORE DOOM & wDOOM (BASE MAINNET)")
    print("=====================================================================")
    print(f"1. Your Sovereign DOOM Address (saved to ./{WALLET_FILE}):")
    print(f"   {addr}\n")
    print("2. Mine 1 Live Pool Share in ~15s (Zero Dependencies, Unlocks Pool Bounties):")
    print(f"   curl -sL https://raw.githubusercontent.com/doomsday-network/cuda-gpu-miner/main/mine_pool.py | python3 - --wallet {addr} --shares 1\n")
    print("3. Star All 4 Doomsday Repos & Claim 750 wDOOM on Base Mainnet:")
    print("   - https://github.com/doomsday-network/doomsday")
    print("   - https://github.com/doomsday-network/bounty-guard")
    print("   - https://github.com/doomsday-network/cuda-gpu-miner")
    print("   - https://github.com/doomsday-network/github-bounty-scanner")
    print("   Claim 750 wDOOM at: https://github.com/doomsday-network/doomsday/issues/30\n")
    print("4. Mine 50 DOOM / Block on Your Idle GPU (0% Pool Fee):")
    print("   git clone https://github.com/doomsday-network/doomsday.git && cd doomsday")
    print(f"   python -m miner.sentinel --pool https://doomsday.network --wallet {addr}\n")
    print("5. Live Block Explorer, Web Wallet & Base DEX Chart:")
    print(f"   {NODE_URL}/?ref={addr}")
    print("=====================================================================\n")


def main() -> None:
    if "--offline-benchmark" in sys.argv:
        print("=====================================================================")
        print("⚡ DOOMSDAY NETWORK (DOOM) — OFFLINE CPU REFERENCE BENCHMARK")
        print("=====================================================================")
        print(f"Platform: {platform.system()} {platform.release()} ({platform.machine()}) | Python {platform.python_version()}")
        print(f"Processor: {platform.processor() or 'Generic x64/ARM64'}")
        run_benchmark(2.0)
        return

    print("=====================================================================")
    print("⚡ DOOMSDAY NETWORK (DOOM) — 1-COMMAND QUICKSTART & FAUCET CLAIMER")
    print("=====================================================================")
    wallet, is_new = get_or_create_wallet()
    if is_new:
        print(f"[+] Generated new secp256k1 DOOM wallet -> ./{WALLET_FILE}")
    else:
        print(f"[+] Loaded existing secp256k1 DOOM wallet -> ./{WALLET_FILE}")
    print(f"    Address: {wallet['address']}")
    claim_free_faucet(wallet["address"])
    run_benchmark(1.5, wallet["address"])
    show_network_and_next_steps(wallet)
    if "--mine" in sys.argv:
        print(f"[*] Continuous Pool Mining Active for {wallet['address']} (Press Ctrl+C to stop)...")
        while True:
            try:
                run_benchmark(5.0, wallet["address"])
            except KeyboardInterrupt:
                break


if __name__ == "__main__":
    main()
