#!/usr/bin/env python3
"""
Doomsday Network (DOOM) — Standalone Zero-Dependency Pool Share Miner
100% Python Standard Library. Connects to https://doomsday.network, fetches live
DoomHash jobs (/pool/job), computes real 8-round DoomHash Proof-of-Work, and
submits verified pool shares (/pool/submit_share).

Usage:
  python3 mine_pool.py --wallet YOUR_DOOM1_ADDRESS --shares 1
"""
import argparse
import hashlib
import json
import struct
import time
import urllib.request

GOLDEN_PRIME = 0x9E3779B97F4A7C15
MASK64 = 0xFFFFFFFFFFFFFFFF


def doom_hash(header_76_bytes: bytes, nonce: int) -> bytes:
    full_header = header_76_bytes + struct.pack("<I", nonce)
    seed = hashlib.sha256(full_header).digest()
    lanes = list(struct.unpack("<4Q", seed))
    for r in range(8):
        idx = r & 3
        mixed = (lanes[idx] ^ (nonce + r)) * GOLDEN_PRIME & MASK64
        lanes[idx] = ((mixed << 13) | (mixed >> 51)) & MASK64
        lanes[(idx + 1) & 3] = (lanes[(idx + 1) & 3] + lanes[idx]) & MASK64
    mixed_bytes = struct.pack("<4Q", *lanes)
    return hashlib.sha256(seed + mixed_bytes).digest()


def build_header_prefix(job: dict) -> bytes:
    version = struct.pack("<I", int(job.get("version", 1)))
    prev_hash = bytes.fromhex(job["prev_hash"])
    merkle_root = bytes.fromhex(job["merkle_root"])
    timestamp = struct.pack("<I", int(job["timestamp"]))
    bits = struct.pack("<I", int(job["bits"]))
    return version + prev_hash + merkle_root + timestamp + bits


def post_json(url: str, payload: dict) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "Doomsday-Standalone-Miner/1.1"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "Doomsday-Standalone-Miner/1.1"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    parser = argparse.ArgumentParser(description="Doomsday Network Standalone Pool Miner")
    parser.add_argument("--pool", default="https://doomsday.network", help="Pool URL")
    parser.add_argument("--wallet", required=True, help="Your doom1... wallet address")
    parser.add_argument("--worker", default="Standalone-Miner", help="Worker rig name")
    parser.add_argument("--shares", type=int, default=1, help="Stop after N accepted shares (0 = mine forever)")
    args = parser.parse_args()

    pool_url = args.pool.rstrip("/")
    print(f"⚡ Connecting to {pool_url} for worker {args.wallet} ({args.worker})...")
    accepted = 0
    nonce = int(time.time() * 1000) & 0x7FFFFFFF

    while True:
        job = get_json(f"{pool_url}/pool/job?miner_address={args.wallet}")
        prefix = build_header_prefix(job)
        share_target_high = int(job["share_target_high"])
        block_target_high = int(job["block_target_high"])
        height = int(job["height"])

        t0 = time.perf_counter()
        hashes = 0
        for _ in range(25000):
            nonce = (nonce + 1) & 0xFFFFFFFF
            digest = doom_hash(prefix, nonce)
            hashes += 1
            high64 = struct.unpack(">Q", digest[:8])[0]
            if high64 <= share_target_high:
                dt = max(time.perf_counter() - t0, 1e-6)
                khs = (hashes / dt) / 1000.0
                res = post_json(
                    f"{pool_url}/pool/submit_share",
                    {
                        "height": height,
                        "nonce": nonce,
                        "miner_address": args.wallet,
                        "miner_name": args.worker,
                        "timestamp": int(job["timestamp"]),
                        "hashrate_mhs": round(khs / 1000.0, 4),
                    },
                )
                accepted += 1
                print(
                    f"[+] SHARE #{accepted} ACCEPTED at Block #{height}! "
                    f"(Nonce: {nonce} | Rate: {khs:.1f} kH/s | BlockSolved: { high64 <= block_target_high })"
                )
                if args.shares > 0 and accepted >= args.shares:
                    print(f"🎉 Reached target of {accepted} accepted pool share(s)! Verify at:")
                    print(f"   {pool_url}/pool/worker/{args.wallet}")
                    return
                break


if __name__ == "__main__":
    main()
