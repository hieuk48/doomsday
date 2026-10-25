"""
doomsday-network/doomsday: Python Quickstart Patch

This module provides a clean, modular, and pure Python implementation for a "3-Second Terminal Quickstart"
and a CPU-based miner simulation for the doomsday-network/doomsday project, as referenced in:
https://github.com/doomsday-network/doomsday/issues/4

Constraints:
- No external dependencies
- No use of subprocess, ctypes, socket, sys.exit, os.system, or eval
- Pure Python, production-ready, and secure

Author: OpenAI Assistant
"""

import hashlib
import time
import threading
from typing import Optional, Callable


def quickstart_demo() -> None:
    """
    Runs a 3-second quickstart demo, simulating a network connection and mining process.
    Prints output to the terminal.
    """
    print("🚀 [Doomsday Quickstart] Initializing node...")
    time.sleep(0.5)
    print("🔗 Connecting to Doomsday Network...")
    time.sleep(0.5)
    print("⛏️  Starting CPU miner (simulated)...")
    mined = cpu_miner_simulation(duration_seconds=2)
    print(f"✅ Mining complete! {mined} hashes computed in 2 seconds.")
    print("🌎 Node is ready and connected to Doomsday Network.")


def cpu_miner_simulation(duration_seconds: int = 2, hash_target: Optional[str] = None) -> int:
    """
    Simulates a simple CPU miner by hashing incrementing nonces for a fixed duration.

    Args:
        duration_seconds (int): How long to run the miner simulation.
        hash_target (Optional[str]): Optional hex string; if provided, stop if a hash starts with this prefix.

    Returns:
        int: Number of hashes computed.
    """
    start_time = time.time()
    nonce = 0
    hashes = 0
    last_report = start_time

    while time.time() - start_time < duration_seconds:
        data = f"doomsday:{nonce}".encode()
        digest = hashlib.sha256(data).hexdigest()
        hashes += 1
        nonce += 1
        if hash_target and digest.startswith(hash_target):
            print(f"🎉 Target found: {digest} (nonce={nonce})")
            break
        # Optional: Print progress every 0.5s
        now = time.time()
        if now - last_report > 0.5:
            print(f"  ...{hashes} hashes so far")
            last_report = now

    return hashes


def run_gpu_miner_simulation(duration_seconds: int = 3, threads: int = 4) -> int:
    """
    Simulates a multi-threaded (CPU) miner to mimic GPU mining.

    Args:
        duration_seconds (int): How long to run the miner simulation.
        threads (int): Number of threads to simulate parallel mining.

    Returns:
        int: Total number of hashes computed across all threads.
    """
    print(f"⚡ Starting simulated GPU miner with {threads} threads for {duration_seconds}s...")

    results = [0] * threads

    def worker(idx: int) -> None:
        results[idx] = cpu_miner_simulation(duration_seconds=duration_seconds // threads or 1)

    thread_list = []
    for i in range(threads):
        t = threading.Thread(target=worker, args=(i,))
        t.start()
        thread_list.append(t)
    for t in thread_list:
        t.join()

    total_hashes = sum(results)
    print(f"✅ Simulated GPU mining complete! {total_hashes} hashes computed.")
    return total_hashes


def run_tests() -> None:
    """
    Runs basic tests to verify miner simulation.
    """
    print("[TEST] Running quickstart_demo()...")
    quickstart_demo()
    print("[TEST] Running cpu_miner_simulation() for 1s...")
    hashes = cpu_miner_simulation(duration_seconds=1)
    assert hashes > 0, "Miner should compute at least one hash"
    print(f"[TEST] cpu_miner_simulation() OK: {hashes} hashes")
    print("[TEST] Running run_gpu_miner_simulation() for 2s, 2 threads...")
    gpu_hashes = run_gpu_miner_simulation(duration_seconds=2, threads=2)
    assert gpu_hashes > 0, "GPU miner should compute at least one hash"
    print(f"[TEST] run_gpu_miner_simulation() OK: {gpu_hashes} hashes")
    print("[TEST] All tests passed.")


if __name__ == "__main__":
    # Run the quickstart demo and tests if executed as a script
    quickstart_demo()
    print("\n---\n")
    run_tests()