import argparse
import asyncio
import json
import os
import time
try:
    import resource
    _soft, _hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    if _soft < 65536:
        resource.setrlimit(resource.RLIMIT_NOFILE, (min(65536, _hard), _hard))
except Exception:
    pass
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Header, Depends, Request
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from node.blockchain import Blockchain
from node.pool import MiningPool
from node.p2p import P2PManager
from node.escrow import EscrowManager
from core.block import Block
from core.transaction import COIN, Transaction, TxInput, TxOutput

app = FastAPI(title="Doomsday Network Node", version="1.0.1", docs_url="/api/docs", redoc_url=None)

@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

# Initialize Ledger
chain = Blockchain()

# Pool Wallet & Mining Pool Engine
def load_or_create_pool_wallet() -> Dict[str, str]:
    paths = [
        "pool_wallet.json",
        "data/pool_wallet.json",
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "pool_wallet.json"),
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "pool_wallet.json")
    ]
    for p in paths:
        if os.path.exists(p):
            try:
                with open(p, "r") as f:
                    return json.load(f)
            except Exception:
                pass
    from core.crypto import generate_keypair, private_key_to_wif, public_key_to_address
    priv, pub = generate_keypair()
    data = {
        "address": public_key_to_address(pub),
        "private_key": private_key_to_wif(priv)
    }
    target = os.path.join(os.path.dirname(os.path.dirname(__file__)), "pool_wallet.json")
    try:
        with open(target, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass
    return data

pool_wallet = load_or_create_pool_wallet()
pool = MiningPool(chain=chain, pool_address=pool_wallet["address"], fee_pct=0.0)

# P2P Wire Protocol Manager
p2p = P2PManager(chain=chain, listen_port=8334)

# Cryptographic GitHub Issue Escrow Engine
escrow_mgr = EscrowManager(chain=chain)

# Live Workers State: miner_name -> dict
active_miners: Dict[str, Dict[str, Any]] = {}

# Active WebSocket connections
connected_sockets: List[WebSocket] = []


class SubmitBlockRequest(BaseModel):
    height: int = Field(..., ge=0)
    nonce: int
    hash: str = Field(..., min_length=16, max_length=64)
    miner_name: str = Field("Rig-Default", max_length=64)
    miner_address: str = Field(..., min_length=10, max_length=64)
    timestamp: Optional[int] = None


class PoolSubmitRequest(BaseModel):
    height: int = Field(..., ge=0)
    nonce: int
    worker_address: str = Field(..., min_length=10, max_length=64)
    worker_name: str = Field("Rig-Default", max_length=64)
    timestamp: Optional[int] = None


class MinerTelemetry(BaseModel):
    name: str
    device: str
    state: str
    hashrate_mhs: float
    temp_c: int
    power_w: float
    util_pct: int
    address: str


class SendTxRequest(BaseModel):
    sender_address: str
    recipient_address: str
    amount_doom: float
    private_key_wif: str


class FaucetClaimRequest(BaseModel):
    recipient_address: str
    referrer_address: Optional[str] = None


class CreateEscrowRequest(BaseModel):
    issue_ref: str = Field(..., description="GitHub issue ref (e.g. 'owner/repo#42' or full GitHub URL)")
    amount_doom: float = Field(..., ge=10.0, description="Amount of DOOM to lock in escrow (>= 10.0)")
    creator_github: str = Field(..., min_length=1, max_length=64, description="Sponsor GitHub username")
    title: Optional[str] = Field("", max_length=200)
    sender_address: Optional[str] = None
    private_key_wif: Optional[str] = None
    lock_txid: Optional[str] = None
    release_mode: str = Field("pr_merge_or_command", max_length=64)
    post_github_seal: bool = True


class ExchangeWithdrawRequest(BaseModel):
    from_address: str
    private_key_wif: str
    to_address: str
    amount_doom: float
    fee_doom: float = 0.001


class BroadcastTxRequest(BaseModel):
    transaction: Dict[str, Any]


class ExchangeRawTxRequest(BaseModel):
    transaction: Dict[str, Any]


EXCHANGE_API_KEY = os.environ.get("DOOMSDAY_EXCHANGE_KEY", "").strip()


def verify_exchange_auth(x_api_key: Optional[str] = Header(None)):
    """Enforce X-API-KEY header. If DOOMSDAY_EXCHANGE_KEY is unset, all exchange RPCs are disabled."""
    if not EXCHANGE_API_KEY:
        raise HTTPException(
            status_code=403,
            detail="Exchange RPC daemon is disabled on this node. Set DOOMSDAY_EXCHANGE_KEY to enable."
        )
    if x_api_key != EXCHANGE_API_KEY:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: Invalid or missing X-API-KEY header for exchange RPC"
        )


class P2PHandshakeRequest(BaseModel):
    node_id: str = Field(..., min_length=1, max_length=64)
    version: str = Field("1.0.0", max_length=32)
    listen_port: int = Field(8334, ge=1, le=65535)
    height: int = Field(..., ge=0)
    tip_hash: str = Field(..., min_length=16, max_length=64)


class P2PBlockGossipRequest(BaseModel):
    block: Dict[str, Any]


class P2PTxGossipRequest(BaseModel):
    transaction: Dict[str, Any]


faucet_claims: Dict[str, float] = {}
faucet_ip_claims: Dict[str, float] = {}


def load_faucet_wallet() -> Optional[Dict[str, str]]:
    paths = [
        "faucet_wallet.json",
        "data/faucet_wallet.json",
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "faucet_wallet.json"),
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "faucet_wallet.json")
    ]
    for p in paths:
        if os.path.exists(p):
            try:
                with open(p, "r") as f:
                    return json.load(f)
            except Exception:
                pass
    return None


async def broadcast_event(event_type: str, data: Any):
    """Broadcast real-time updates to all connected web dashboards."""
    dead_sockets = []
    message = json.dumps({"type": event_type, "data": data})
    for ws in connected_sockets:
        try:
            await ws.send_text(message)
        except Exception:
            dead_sockets.append(ws)
    for ws in dead_sockets:
        if ws in connected_sockets:
            connected_sockets.remove(ws)


@app.get("/status")
def get_status():
    tip = chain.get_tip()
    now = time.time()
    active_workers_list = [m for m in active_miners.values() if now - m.get("last_seen", 0) < 15]
    total_mhs = sum(m.get("hashrate_mhs", 0.0) for m in active_workers_list)
    return {
        "network": "Doomsday Network",
        "ticker": "DOOM",
        "height": tip.height,
        "tip_hash": tip.hash,
        "difficulty_bits": hex(tip.header.bits),
        "target": hex(chain.create_block_template("check", cache=False)["target_high"]),
        "total_mined_doom": (tip.height + 1) * 50.0,
        "max_supply": 21_000_000,
        "active_workers": len(active_workers_list),
        "cluster_hashrate_mhs": round(total_mhs, 2),
        "mempool_size": len(chain.mempool),
        "p2p_peers": len([p for p in p2p.peers.values() if p.is_connected]),
        "p2p_syncing": p2p.is_syncing
    }


def get_subsidy(h: int) -> int:
    from core.consensus import get_block_reward
    return get_block_reward(h)


@app.get("/job")
def get_mining_job(miner_address: str = "doom1miner000000000000000000000000000000"):
    return chain.create_block_template(miner_address)


@app.post("/submit")
async def submit_block(req: SubmitBlockRequest):
    ok, msg = chain.add_block_candidate(
        height=req.height,
        nonce=req.nonce,
        miner_address=req.miner_address,
        miner_name=req.miner_name,
        timestamp=req.timestamp
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)

    # Broadcast new block event
    tip = chain.get_tip()
    await broadcast_event("new_block", {
        "height": tip.height,
        "hash": tip.hash,
        "miner": tip.header.miner_address,
        "miner_name": req.miner_name,
        "nonce": tip.header.nonce,
        "timestamp": tip.header.timestamp,
        "reward_doom": 50.0
    })

    # Wire Gossip: Broadcast new block to P2P mesh
    asyncio.create_task(p2p.broadcast_block(tip))
    return {"accepted": True, "height": tip.height, "hash": tip.hash}


@app.get("/pool/job")
def get_pool_job(worker_address: str = "doom1miner000000000000000000000000000000", worker_name: str = "Worker-Default"):
    return pool.get_job(worker_address, worker_name)


async def process_auto_pool_payouts():
    """Automatically distribute on-chain payouts to pool miners with >= 1.0 DOOM unpaid."""
    eligible = {addr: amt for addr, amt in pool.unpaid_sparks.items() if amt >= int(1.0 * COIN) and addr != pool.pool_address}
    if not eligible:
        return
    total_payout = sum(eligible.values())
    avail = chain.get_balance(pool.pool_address)
    if avail < total_payout:
        return

    from core.crypto import private_key_from_wif
    priv = private_key_from_wif(pool_wallet["private_key"])
    inputs = []
    accum = 0
    mempool_spent = chain.get_mempool_spent_outpoints()
    for outpoint, (rcpt, amt) in chain.utxo_set.items():
        if rcpt == pool.pool_address and outpoint not in mempool_spent:
            txid, vout = outpoint.split(":")
            inputs.append(TxInput(txid=txid, vout=int(vout)))
            accum += amt
            if accum >= total_payout:
                break

    if accum < total_payout:
        return

    outputs = [TxOutput(recipient=addr, amount=amt) for addr, amt in eligible.items()]
    change = accum - total_payout
    if change > 0:
        outputs.append(TxOutput(recipient=pool.pool_address, amount=change))

    tx = Transaction(inputs=inputs, outputs=outputs)
    for idx in range(len(inputs)):
        tx.sign_input(idx, priv)

    ok, _ = chain.add_transaction_to_mempool(tx)
    if ok:
        for addr, amt in eligible.items():
            pool.unpaid_sparks[addr] = 0
            pool.total_paid_sparks[addr] = pool.total_paid_sparks.get(addr, 0) + amt
        pool._save_state()
        await broadcast_event("new_tx", tx.to_dict())
        asyncio.create_task(p2p.broadcast_tx(tx))


@app.post("/pool/submit")
async def submit_pool_share(req: PoolSubmitRequest):
    res = pool.submit_share(
        height=req.height,
        nonce=req.nonce,
        worker_address=req.worker_address,
        worker_name=req.worker_name,
        timestamp=req.timestamp
    )
    if not res.get("accepted"):
        raise HTTPException(status_code=400, detail=res.get("reason", "Share rejected"))

    if res.get("block_solved"):
        tip = chain.get_tip()
        await broadcast_event("new_block", {
            "height": tip.height,
            "hash": tip.hash,
            "miner": tip.header.miner_address,
            "miner_name": f"Pool:[{req.worker_name}]",
            "nonce": tip.header.nonce,
            "timestamp": tip.header.timestamp,
            "reward_doom": 50.0
        })
        # Wire Gossip: Broadcast pool-discovered block to P2P mesh
        asyncio.create_task(p2p.broadcast_block(tip))
        # Automatically pay out round contributors with >= 1.0 DOOM unpaid
        await process_auto_pool_payouts()

    await broadcast_event("pool_stats", _get_enriched_pool_stats())
    return res


def _get_enriched_pool_stats() -> Dict[str, Any]:
    stats = pool.get_stats()
    now = time.time()
    active_tel = [m for m in active_miners.values() if now - m.get("last_seen", 0) < 30]
    tel_mhs = round(sum(m.get("hashrate_mhs", 0.0) for m in active_tel), 2)
    if tel_mhs > stats.get("pool_hashrate_mhs", 0.0):
        stats["pool_hashrate_mhs"] = tel_mhs
    if len(active_tel) > stats.get("active_miners", 0):
        stats["active_miners"] = len(active_tel)
    return stats


@app.get("/pool/stats")
def get_pool_stats():
    return _get_enriched_pool_stats()


@app.get("/pool/leaderboard")
def get_pool_leaderboard():
    now = time.time()
    system_addrs = {
        pool.pool_address,
        "doom1vault000000000000000000000000000000",
        "doom1caea0957fb471c2b83940cc2feb421abad938dfbdef662de"
    }
    tel_addrs = {m.get("address", "") for m in active_miners.values() if m.get("address", "").startswith("doom1")}
    all_addrs = (set(pool.total_paid_sparks.keys()) | set(pool.unpaid_sparks.keys()) | set(pool.round_shares.keys()) | tel_addrs) - system_addrs
    blocks_by_solver: Dict[str, int] = {}
    for bf in pool.blocks_found:
        s = bf.get("solver", "")
        if s:
            blocks_by_solver[s] = blocks_by_solver.get(s, 0) + 1

    entries = []
    mempool_spent = chain.get_mempool_spent_outpoints()
    onchain_balances: Dict[str, int] = {}
    for outpoint, (rcpt, amt) in chain.utxo_set.items():
        if outpoint not in mempool_spent:
            onchain_balances[rcpt] = onchain_balances.get(rcpt, 0) + amt

    for addr in all_addrs:
        if not addr or not addr.startswith("doom1"):
            continue
        paid = pool.total_paid_sparks.get(addr, 0)
        unpaid = pool.unpaid_sparks.get(addr, 0)
        onchain_sparks = onchain_balances.get(addr, 0)
        total_doom = round(max(paid + unpaid, onchain_sparks + unpaid) / COIN, 2)
        r_shares = pool.round_shares.get(addr, 0)
        matching_w = [w for w in pool.workers.values() if w.address == addr and (now - w.last_share_time < 120)]
        matching_t = [m for m in active_miners.values() if m.get("address") == addr and (now - m.get("last_seen", 0) < 30)]
        tel_mhs = round(sum(m.get("hashrate_mhs", 0.0) for m in matching_t), 2)
        w_mhs = round(sum(w.hashrate_mhs for w in matching_w), 2)
        mhs = max(tel_mhs, w_mhs)
        rigs = max(len(matching_t), len(matching_w))
        is_online = rigs > 0
        entries.append({
            "address": addr,
            "total_mined_doom": total_doom,
            "total_doom_earned": total_doom,
            "hashrate_mhs": mhs,
            "active_rigs": rigs,
            "round_shares": r_shares,
            "recent_blocks_solved": blocks_by_solver.get(addr, 0),
            "is_online": is_online,
            "is_active": is_online
        })

    entries.sort(key=lambda x: (x["total_mined_doom"], x["hashrate_mhs"], x["round_shares"]), reverse=True)
    top10 = entries[:10]
    return {"leaders": top10, "leaderboard": top10, "total_unique_miners": len(entries)}


@app.get("/pool/worker/{address}")
def get_pool_worker(address: str):
    wstats = pool.get_worker_stats(address)
    now = time.time()
    tel = [m for m in active_miners.values() if m.get("address") == address and (now - m.get("last_seen", 0) < 30)]
    tel_mhs = round(sum(m.get("hashrate_mhs", 0.0) for m in tel), 2)
    if tel_mhs > wstats.get("hashrate_mhs", 0.0):
        wstats["hashrate_mhs"] = tel_mhs
        wstats["is_active"] = True
        wstats["active_rigs"] = max(wstats.get("active_rigs", 0), len(tel))
    return wstats


@app.post("/pool/payout")
async def request_pool_payout(req: FaucetClaimRequest):
    unpaid = pool.unpaid_sparks.get(req.recipient_address, 0)
    if unpaid < int(1.0 * COIN):
        raise HTTPException(status_code=400, detail=f"Minimum payout is 1.0 DOOM. Unpaid balance: {unpaid / COIN:.4f} DOOM")

    avail = chain.get_balance(pool.pool_address)
    if avail < unpaid:
        raise HTTPException(status_code=503, detail="Pool node does not have sufficient confirmed on-chain balance yet.")

    from core.crypto import private_key_from_wif
    priv = private_key_from_wif(pool_wallet["private_key"])
    inputs = []
    accum = 0
    mempool_spent = chain.get_mempool_spent_outpoints()
    for outpoint, (rcpt, amt) in chain.utxo_set.items():
        if rcpt == pool.pool_address and outpoint not in mempool_spent:
            txid, vout = outpoint.split(":")
            inputs.append(TxInput(txid=txid, vout=int(vout)))
            accum += amt
            if accum >= unpaid:
                break

    outputs = [TxOutput(recipient=req.recipient_address, amount=unpaid)]
    change = accum - unpaid
    if change > 0:
        outputs.append(TxOutput(recipient=pool.pool_address, amount=change))

    tx = Transaction(inputs=inputs, outputs=outputs)
    for idx in range(len(inputs)):
        tx.sign_input(idx, priv)

    ok, reason = chain.add_transaction_to_mempool(tx)
    if not ok:
        raise HTTPException(status_code=400, detail=reason)

    pool.unpaid_sparks[req.recipient_address] = 0
    pool.total_paid_sparks[req.recipient_address] = pool.total_paid_sparks.get(req.recipient_address, 0) + unpaid
    pool._save_state()

    await broadcast_event("new_tx", tx.to_dict())
    await broadcast_event("pool_stats", _get_enriched_pool_stats())
    asyncio.create_task(p2p.broadcast_tx(tx))
    return {
        "status": "payout_sent",
        "txid": tx.txid,
        "amount_doom": unpaid / COIN,
        "recipient": req.recipient_address
    }


# ==============================================================================
# P2P WIRE PROTOCOL ENDPOINTS
# ==============================================================================

@app.get("/p2p/status")
def get_p2p_status():
    stats = p2p.get_stats()
    masked_peers = []
    for p in stats.get("peers", []):
        d = dict(p)
        d["address"] = _mask_peer_address(d.get("address", ""))
        d.pop("url", None)
        masked_peers.append(d)
    stats["peers"] = masked_peers
    return stats


@app.post("/p2p/handshake")
async def p2p_handshake(req: P2PHandshakeRequest, request: Request):
    client_ip = request.client.host if request.client else "127.0.0.1"
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()

    caller_addr = f"{client_ip}:{req.listen_port}"
    if req.node_id != p2p.node_id:
        peer = p2p.register_peer(caller_addr)
        peer.node_id = req.node_id
        peer.height = req.height
        peer.tip_hash = req.tip_hash
        peer.last_seen = time.time()
        peer.is_connected = True

    tip = chain.get_tip()
    return {
        "node_id": p2p.node_id,
        "version": "1.0.0",
        "height": tip.height,
        "tip_hash": tip.hash,
        "known_peers": [p.address for p in p2p.peers.values() if p.is_connected]
    }


def _mask_peer_address(addr: str) -> str:
    """Redact the last two octets of IPv4 peer addresses to protect node operator OpSec."""
    host, _, port = addr.rpartition(":")
    if not host:
        host, port = addr, "8334"
    parts = host.split(".")
    if len(parts) == 4 and all(p.isdigit() for p in parts):
        return f"{parts[0]}.{parts[1]}.*.*:{port}"
    return f"mesh-peer:{port}"


@app.get("/p2p/peers")
def get_p2p_peers():
    out = []
    for p in p2p.peers.values():
        if p.is_connected:
            d = p.to_dict()
            d["address"] = _mask_peer_address(d.get("address", ""))
            d.pop("url", None)
            out.append(d)
    return out


@app.get("/p2p/blocks")
def get_p2p_blocks(start_height: int = 0, limit: int = 50):
    limit = min(max(1, limit), 100)
    selected = chain.blocks[start_height:start_height + limit]
    return [b.to_dict() for b in selected]


@app.post("/p2p/block")
async def receive_p2p_block(req: P2PBlockGossipRequest):
    try:
        b = Block.from_dict(req.block)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Malformed block structure: {e}")

    if b.hash in p2p.seen_blocks:
        return {"accepted": True, "duplicate": True}

    p2p.seen_blocks.add(b.hash)
    tip = chain.get_tip()

    if b.height == tip.height + 1:
        ok, msg = chain.add_external_block(b)
        if not ok:
            raise HTTPException(status_code=400, detail=msg)

        await broadcast_event("new_block", {
            "height": b.height,
            "hash": b.hash,
            "miner": b.header.miner_address,
            "miner_name": "P2P-Peer",
            "nonce": b.header.nonce,
            "timestamp": b.header.timestamp,
            "reward_doom": 50.0
        })

        asyncio.create_task(p2p.broadcast_block(b))
        return {"accepted": True, "height": b.height, "hash": b.hash}
    elif b.height > tip.height + 1:
        return {"accepted": False, "status": "sync_required", "tip": tip.height}
    else:
        return {"accepted": False, "status": "stale"}


@app.post("/p2p/tx")
async def receive_p2p_tx(req: P2PTxGossipRequest):
    try:
        tx = Transaction.from_dict(req.transaction)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Malformed transaction structure: {e}")

    if tx.txid in p2p.seen_txs:
        return {"accepted": True, "duplicate": True}

    p2p.seen_txs.add(tx.txid)
    ok, reason = chain.add_transaction_to_mempool(tx)
    if ok:
        await broadcast_event("new_tx", tx.to_dict())
        asyncio.create_task(p2p.broadcast_tx(tx))
        return {"accepted": True, "txid": tx.txid}
    return {"accepted": False, "reason": reason}


@app.post("/miner/telemetry")
async def receive_telemetry(req: MinerTelemetry):
    active_miners[req.name] = {
        "name": req.name,
        "device": req.device,
        "state": req.state,
        "hashrate_mhs": req.hashrate_mhs,
        "temp_c": req.temp_c,
        "power_w": req.power_w,
        "util_pct": req.util_pct,
        "address": req.address,
        "last_seen": time.time()
    }
    # OpSec: Broadcast only network-wide aggregate metrics, never individual machine telemetry
    now = time.time()
    active_workers_list = [m for m in active_miners.values() if now - m.get("last_seen", 0) < 15]
    total_mhs = sum(m.get("hashrate_mhs", 0.0) for m in active_workers_list)
    await broadcast_event("network_stats", {
        "active_workers": len(active_workers_list),
        "cluster_hashrate_mhs": round(total_mhs, 2)
    })
    return {"status": "ok"}


@app.get("/blocks")
def get_blocks(limit: int = 20):
    recent = list(reversed(chain.blocks[-limit:]))
    return [b.to_dict() for b in recent]


@app.get("/wallet/{address}")
def get_wallet(address: str):
    sparks = chain.get_balance(address)
    utxos = chain.get_address_utxos(address)
    return {
        "address": address,
        "balance_sparks": sparks,
        "balance_doom": sparks / COIN,
        "utxo_count": len(utxos)
    }


@app.get("/wallet/{address}/utxos")
def get_wallet_utxos(address: str):
    """
    Public read-only endpoint returning unspent transaction outputs (UTXOs).
    Enables clients to build and sign transactions 100% locally.
    """
    sparks = chain.get_balance(address)
    utxos = chain.get_address_utxos(address)
    return {
        "address": address,
        "balance_doom": sparks / COIN,
        "balance_sparks": sparks,
        "utxo_count": len(utxos),
        "utxos": utxos
    }


@app.post("/tx/broadcast")
async def broadcast_transaction(req: BroadcastTxRequest):
    """
    Mempool broadcast for client-side pre-signed ECDSA transactions.
    Sovereign non-custodial design: private keys are never transmitted to this node.
    """
    try:
        tx = Transaction.from_dict(req.transaction)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Malformed transaction structure: {e}")

    ok, reason = chain.add_transaction_to_mempool(tx)
    if not ok:
        raise HTTPException(status_code=400, detail=f"Transaction rejected: {reason}")

    await broadcast_event("new_tx", tx.to_dict())
    asyncio.create_task(p2p.broadcast_tx(tx))
    return {
        "status": "broadcasted",
        "txid": tx.txid,
        "inputs": len(tx.inputs),
        "outputs": len(tx.outputs)
    }


@app.post("/tx/send")
async def send_transaction_forbidden():
    """
    Permanently disabled for user safety. Private keys must never be transmitted over HTTP.
    """
    raise HTTPException(
        status_code=403,
        detail="Security violation: Server-side signing is permanently disabled. Private keys must never leave your device. Sign transactions locally with client-side secp256k1 and broadcast to /tx/broadcast."
    )


@app.post("/wallet/new")
def generate_new_wallet_deprecated():
    """
    Permanently disabled for user safety. Keys must be generated client-side.
    """
    raise HTTPException(
        status_code=410,
        detail="Security notice: Server-side key generation is deprecated. Generate secp256k1 keypairs client-side in the browser or via the offline CLI."
    )


@app.get("/faucet/info")
def get_faucet_info():
    faucet = load_faucet_wallet()
    if not faucet:
        return {"active": False, "balance_doom": 0.0, "address": None, "drop_amount": 10.0}
    balance_sparks = chain.get_balance(faucet["address"])
    return {
        "active": True,
        "address": faucet["address"],
        "balance_doom": balance_sparks / COIN,
        "drop_amount": 10.0
    }


@app.get("/bridge/audit")
def get_bridge_audit():
    """
    Public Proof-of-Reserve & Base Mainnet Liquidity Transparency Endpoint.
    Distinguishes 1:1 user-bridged vault deposits from the initial 100,000 wDOOM
    Uniswap v3 DEX Liquidity Bootstrap pool on Base Mainnet.
    """
    vault_address = "doom1vault000000000000000000000000000000"
    vault_sparks = chain.get_balance(vault_address)
    vault_utxos = chain.get_address_utxos(vault_address)
    return {
        "status": "operational",
        "native_vault_address": vault_address,
        "native_vault_locked_doom": vault_sparks / COIN,
        "native_vault_locked_sparks": vault_sparks,
        "native_vault_utxo_count": len(vault_utxos),
        "evm_network": "Base Mainnet (Chain ID 8453)",
        "wdoom_contract": "0x623c84A5E04bF715018203334b0eFE41696eBC3E",
        "uniswap_v3_pool": "0xf7217329574249d7b389404aECF2C582662F3659",
        "dex_liquidity_bootstrap_wdoom": 100000.0,
        "user_bridged_circulation_wdoom": vault_sparks / COIN,
        "expected_total_wdoom_supply": 100000.0 + (vault_sparks / COIN),
        "audit_note": (
            "100,000 wDOOM was minted at genesis deployment solely to seed the public "
            "Uniswap v3 wDOOM/WETH 1% liquidity pool (0xf7217329574249d7b389404aECF2C582662F3659). "
            "All subsequent wDOOM mints are strictly 1:1 backed by native DOOM locked in "
            "doom1vault000000000000000000000000000000 and verifiable via processedDoomsdayTxs on Base."
        )
    }


class PrivateBountyClaimRequest(BaseModel):
    github_user: str
    wallet_address: str


PRIVATE_BOUNTY_ELIGIBLE: Dict[str, float] = {
    "pythonyx135793": 500.0,
    "juanmigueldacostaabella-boop": 500.0,
}
private_bounty_claimed: set = set()


@app.get("/bounty/claim", response_class=HTMLResponse)
def get_private_bounty_claim_form():
    return """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Doomsday Network — Private Bounty Claim</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{background:#0b0c10;color:#e5e7eb;font-family:system-ui,-apple-system,sans-serif;display:flex;justify-content:center;align-items:center;min-height:95vh;margin:0}
.card{background:#12151e;border:1px solid #262b3d;border-radius:12px;padding:28px;max-width:480px;width:92%;box-shadow:0 12px 32px rgba(0,0,0,0.5)}
h2{margin-top:0;color:#ff4d4d}
label{display:block;font-size:13px;color:#9ca3af;margin:14px 0 6px}
input{width:100%;box-sizing:border-box;padding:10px 12px;background:#0b0c10;border:1px solid #374151;border-radius:8px;color:#fff;font-family:monospace;font-size:14px}
button{margin-top:18px;width:100%;padding:12px;background:#ff4d4d;color:#fff;border:none;border-radius:8px;font-weight:700;cursor:pointer;font-size:15px}
#res{margin-top:16px;font-size:13px;word-break:break-all;color:#34d399}
</style></head><body><div class="card">
<h2>🔒 Private Bounty Payout Form</h2>
<p style="font-size:13px;color:#9ca3af;line-height:1.5">Submit your Base Mainnet (<code>0x...</code>) or Doomsday L1 (<code>doom1...</code>) address privately over TLS 1.3. Your address is never posted to GitHub.</p>
<label>GitHub Username (with verified benchmark on Issue #4)</label>
<input id="gh" placeholder="e.g. pythonyx135793" />
<label>Base Mainnet (0x...) or Doomsday (doom1...) Address</label>
<input id="wa" placeholder="0x... or doom1..." />
<button onclick="sub()">Claim Bounty Privately</button>
<div id="res"></div>
</div>
<script>
async function sub(){
  const r = document.getElementById('res');
  r.style.color='#9ca3af'; r.textContent='Submitting private claim...';
  const res = await fetch('/bounty/claim',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({github_user:document.getElementById('gh').value.trim(),wallet_address:document.getElementById('wa').value.trim()})});
  const d = await res.json();
  if(res.ok){ r.style.color='#34d399'; r.textContent='Success! On-chain TxID: '+d.txid+' ('+d.amount_doom+' wDOOM/DOOM dispensed)'; }
  else { r.style.color='#f87171'; r.textContent='Error: '+(d.detail||'Failed'); }
}
</script></body></html>"""


@app.post("/bounty/claim")
async def submit_private_bounty_claim(req: PrivateBountyClaimRequest):
    user_clean = req.github_user.strip().lstrip("@").lower()
    wallet_clean = req.wallet_address.strip()
    if user_clean not in PRIVATE_BOUNTY_ELIGIBLE:
        raise HTTPException(status_code=403, detail="GitHub username not in pre-approved private claim list. Post your benchmark on Issue #4 first.")
    if user_clean in private_bounty_claimed:
        raise HTTPException(status_code=409, detail="Private bounty already claimed for this GitHub user.")
    is_evm = wallet_clean.lower().startswith("0x") and len(wallet_clean) == 42
    is_doom = wallet_clean.lower().startswith("doom1") and len(wallet_clean) == 53
    if not (is_evm or is_doom):
        raise HTTPException(status_code=400, detail="Invalid Base (0x...) or Doomsday (doom1...) wallet address.")

    faucet = load_faucet_wallet()
    if not faucet:
        raise HTTPException(status_code=503, detail="Faucet wallet not loaded.")
    reward_doom = PRIVATE_BOUNTY_ELIGIBLE[user_clean]
    sparks_needed = int(reward_doom * COIN)

    from core.crypto import private_key_from_wif
    priv = private_key_from_wif(faucet["private_key"])
    inputs = []
    accum = 0
    mempool_spent = chain.get_mempool_spent_outpoints()
    for outpoint, (rcpt, amt) in chain.utxo_set.items():
        if rcpt == faucet["address"] and outpoint not in mempool_spent:
            txid, vout = outpoint.split(":")
            inputs.append(TxInput(txid=txid, vout=int(vout)))
            accum += amt
            if accum >= sparks_needed:
                break
    if accum < sparks_needed:
        raise HTTPException(status_code=503, detail="Faucet UTXO currently busy confirming block; retry in 15 seconds.")

    target_rcpt = "doom1vault000000000000000000000000000000" if is_evm else wallet_clean.lower()
    extra_memo = wallet_clean if is_evm else "Private Bounty Claim"
    outputs = [TxOutput(recipient=target_rcpt, amount=sparks_needed)]
    change = accum - sparks_needed
    if change > 0:
        outputs.append(TxOutput(recipient=faucet["address"], amount=change))
    tx = Transaction(inputs=inputs, outputs=outputs, extra_data=extra_memo)
    for idx in range(len(inputs)):
        tx.sign_input(idx, priv)
    ok, reason = chain.add_transaction_to_mempool(tx)
    if not ok:
        raise HTTPException(status_code=400, detail=reason)
    private_bounty_claimed.add(user_clean)
    await broadcast_event("new_tx", tx.to_dict())
    asyncio.create_task(p2p.broadcast_tx(tx))
    return {"status": "success", "txid": tx.txid, "amount_doom": reward_doom}


@app.post("/faucet/claim")
async def claim_faucet(req: FaucetClaimRequest, request: Request):
    faucet = load_faucet_wallet()
    if not faucet:
        raise HTTPException(status_code=503, detail="Faucet wallet is currently not loaded on this node.")

    client_ip = request.client.host if request.client else "127.0.0.1"
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()

    now = time.time()
    last_ip_claim = faucet_ip_claims.get(client_ip, 0)
    if client_ip not in ("127.0.0.1", "localhost") and (now - last_ip_claim < 300):
        wait_ip = int(300 - (now - last_ip_claim))
        raise HTTPException(status_code=429, detail=f"IP rate limit active (anti-bot guard). Please wait {wait_ip}s before claiming again.")

    last_claim = faucet_claims.get(req.recipient_address, 0)
    if now - last_claim < 60:
        wait_sec = int(60 - (now - last_claim))
        raise HTTPException(status_code=429, detail=f"Rate limit exceeded. Please wait {wait_sec}s before claiming again.")

    ref_addr = (req.referrer_address or "").strip()
    has_valid_ref = (
        ref_addr.startswith("doom1")
        and len(ref_addr) >= 35
        and ref_addr != req.recipient_address
        and ref_addr != faucet["address"]
    )
    recipient_doom = 15.0 if has_valid_ref else 10.0
    ref_bonus_doom = 10.0 if has_valid_ref else 0.0
    amount_sparks = int(recipient_doom * COIN)
    ref_sparks = int(ref_bonus_doom * COIN)
    total_needed = amount_sparks + ref_sparks

    avail = chain.get_balance(faucet["address"])
    if avail < total_needed:
        raise HTTPException(status_code=503, detail="Faucet is depleted. Check back after miners discover more blocks.")

    from core.crypto import private_key_from_wif
    priv = private_key_from_wif(faucet["private_key"])
    inputs = []
    accum = 0
    mempool_spent = chain.get_mempool_spent_outpoints()
    for outpoint, (rcpt, amt) in chain.utxo_set.items():
        if rcpt == faucet["address"] and outpoint not in mempool_spent:
            txid, vout = outpoint.split(":")
            inputs.append(TxInput(txid=txid, vout=int(vout)))
            accum += amt
            if accum >= total_needed:
                break

    outputs = [TxOutput(recipient=req.recipient_address, amount=amount_sparks)]
    if has_valid_ref and ref_sparks > 0:
        outputs.append(TxOutput(recipient=ref_addr, amount=ref_sparks))
    change = accum - total_needed
    if change > 0:
        outputs.append(TxOutput(recipient=faucet["address"], amount=change))

    tx = Transaction(inputs=inputs, outputs=outputs)
    for idx in range(len(inputs)):
        tx.sign_input(idx, priv)

    ok, reason = chain.add_transaction_to_mempool(tx)
    if not ok:
        raise HTTPException(status_code=400, detail=reason)

    faucet_claims[req.recipient_address] = now
    faucet_ip_claims[client_ip] = now
    await broadcast_event("new_tx", tx.to_dict())
    asyncio.create_task(p2p.broadcast_tx(tx))
    return {
        "status": "success",
        "txid": tx.txid,
        "amount_doom": recipient_doom,
        "referral_bonus_doom": ref_bonus_doom,
        "referrer": ref_addr if has_valid_ref else None,
        "recipient": req.recipient_address
    }


# ==============================================================================
# CRYPTOGRAPHIC GITHUB ESCROW & AGENT BOUNTY ENGINE ENDPOINTS
# ==============================================================================

@app.get("/escrow/list")
def list_escrows():
    """Return all OPEN and SETTLED on-chain GitHub issue escrows."""
    return escrow_mgr.list_all()


@app.get("/escrow/{owner}/{repo}/{issue_number}")
def verify_issue_escrow(owner: str, repo: str, issue_number: int):
    """Deterministic verification endpoint for AI agents and Bounty-Guard."""
    return escrow_mgr.verify_issue(owner=owner, repo=repo, issue_number=issue_number)


@app.post("/escrow/create")
async def create_issue_escrow(req: CreateEscrowRequest):
    """Lock DOOM on-chain to back any GitHub issue and generate a Proof-of-Escrow seal."""
    ok, msg, record, broadcast_tx = escrow_mgr.create_escrow(
        issue_ref=req.issue_ref,
        amount_doom=req.amount_doom,
        creator_github=req.creator_github,
        title=req.title or "",
        sender_address=req.sender_address,
        private_key_wif=req.private_key_wif,
        lock_txid=req.lock_txid,
        release_mode=req.release_mode,
    )
    if not ok or not record:
        raise HTTPException(status_code=400, detail=msg)

    if broadcast_tx is not None:
        await broadcast_event("new_tx", broadcast_tx.to_dict())
        asyncio.create_task(p2p.broadcast_tx(broadcast_tx))

    seal_posted = False
    if req.post_github_seal:
        seal_posted = escrow_mgr.post_github_escrow_seal(record)

    await broadcast_event("new_escrow", record)
    return {
        "status": "locked",
        "message": msg,
        "escrow": record,
        "github_seal_posted": seal_posted,
        "seal_markdown": escrow_mgr.format_escrow_seal_markdown(record),
    }


# ==============================================================================
# EXCHANGE DAEMON & CEX INTEGRATION RPC ENDPOINTS
# ==============================================================================

@app.get("/rpc/exchange/status", dependencies=[Depends(verify_exchange_auth)])
def exchange_status():
    """Health, sync status, and block tip inspection for automated exchange daemons."""
    tip = chain.get_tip()
    now = int(time.time())
    is_synced = (now - tip.header.timestamp < 3600) or (len(p2p.peers) == 0 and len(chain.blocks) > 0)
    connected_peer_count = len([p for p in p2p.peers.values() if p.is_connected])
    return {
        "status": "online",
        "version": "1.0.0",
        "network": "mainnet",
        "synced": is_synced,
        "chain_height": tip.height,
        "best_block_hash": tip.hash,
        "tip_timestamp": tip.header.timestamp,
        "difficulty_bits": hex(tip.header.bits),
        "mempool_size": len(chain.mempool),
        "peer_count": connected_peer_count,
        "p2p_node_id": p2p.node_id
    }


@app.post("/rpc/exchange/create_address", dependencies=[Depends(verify_exchange_auth)])
def exchange_create_address():
    """Generate a fresh deposit keypair and address for customer accounts."""
    from core.crypto import generate_keypair, private_key_to_wif, public_key_to_address
    priv, pub = generate_keypair()
    addr = public_key_to_address(pub)
    wif = private_key_to_wif(priv)
    return {
        "address": addr,
        "private_key_wif": wif,
        "created_at": int(time.time())
    }


@app.get("/rpc/exchange/address/{address}", dependencies=[Depends(verify_exchange_auth)])
def exchange_get_address(address: str):
    """Query balance and active UTXOs for an exchange account or hot wallet."""
    sparks = chain.get_balance(address)
    utxos = chain.get_address_utxos(address)
    return {
        "address": address,
        "balance_doom": sparks / COIN,
        "balance_sparks": sparks,
        "utxo_count": len(utxos),
        "utxos": utxos
    }


@app.get("/rpc/exchange/block/{identifier}", dependencies=[Depends(verify_exchange_auth)])
def exchange_get_block(identifier: str):
    """Scan block by height or hash with parsed transaction list and confirmation depth."""
    b = chain.get_block(identifier)
    if not b:
        raise HTTPException(status_code=404, detail=f"Block '{identifier}' not found in ledger")
    tip = chain.get_tip()
    confirmations = tip.height - b.height + 1
    txs_data = []
    for tx in b.transactions:
        txs_data.append({
            "txid": tx.txid,
            "is_coinbase": tx.is_coinbase,
            "inputs": [{"txid": inp.txid, "vout": inp.vout} for inp in tx.inputs],
            "outputs": [{
                "recipient": out.recipient,
                "amount_doom": out.amount / COIN,
                "amount_sparks": out.amount
            } for out in tx.outputs]
        })
    return {
        "height": b.height,
        "hash": b.hash,
        "prev_hash": b.header.prev_hash,
        "merkle_root": b.header.merkle_root,
        "timestamp": b.header.timestamp,
        "nonce": b.header.nonce,
        "bits": hex(b.header.bits),
        "miner_address": b.header.miner_address,
        "confirmations": confirmations,
        "tx_count": len(b.transactions),
        "transactions": txs_data
    }


@app.get("/rpc/exchange/tx/{txid}", dependencies=[Depends(verify_exchange_auth)])
def exchange_get_tx(txid: str):
    """Retrieve transaction confirmation count and block metadata."""
    tx, b, confs = chain.get_transaction(txid)
    if not tx:
        raise HTTPException(status_code=404, detail=f"Transaction '{txid}' not found in ledger or mempool")
    status = "confirmed" if b is not None else "mempool"
    return {
        "txid": tx.txid,
        "status": status,
        "confirmed": (status == "confirmed"),
        "confirmations": confs,
        "block_height": b.height if b else None,
        "block_hash": b.hash if b else None,
        "timestamp": b.header.timestamp if b else int(time.time()),
        "is_coinbase": tx.is_coinbase,
        "inputs": [{"txid": inp.txid, "vout": inp.vout} for inp in tx.inputs],
        "outputs": [{
            "recipient": out.recipient,
            "amount_doom": out.amount / COIN,
            "amount_sparks": out.amount
        } for out in tx.outputs]
    }


@app.post("/rpc/exchange/withdraw", dependencies=[Depends(verify_exchange_auth)])
async def exchange_withdraw(req: ExchangeWithdrawRequest):
    """Automated hot wallet withdrawal processing and network wire broadcast."""
    from core.crypto import private_key_from_wif, public_key_to_address
    try:
        priv = private_key_from_wif(req.private_key_wif)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid private key WIF: {e}")

    sender_derived = public_key_to_address(priv.public_key())
    if sender_derived != req.from_address:
        raise HTTPException(status_code=400, detail="Private key does not match from_address")

    amount_sparks = int(round(req.amount_doom * COIN))
    if amount_sparks <= 0:
        raise HTTPException(status_code=400, detail="amount_doom must be strictly greater than 0")

    fee_sparks = int(round(max(0.0001, req.fee_doom) * COIN))
    total_required = amount_sparks + fee_sparks

    avail = chain.get_balance(req.from_address)
    if avail < total_required:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient balance in hot wallet: available {avail/COIN} DOOM, needed {total_required/COIN} DOOM (including {fee_sparks/COIN} fee)"
        )

    inputs = []
    accum = 0
    mempool_spent = chain.get_mempool_spent_outpoints()
    for outpoint, (rcpt, amt) in chain.utxo_set.items():
        if rcpt == req.from_address and outpoint not in mempool_spent:
            txid, vout = outpoint.split(':')
            inputs.append(TxInput(txid=txid, vout=int(vout)))
            accum += amt
            if accum >= total_required:
                break

    outputs = [TxOutput(recipient=req.to_address, amount=amount_sparks)]
    change = accum - total_required
    if change > 0:
        outputs.append(TxOutput(recipient=req.from_address, amount=change))

    tx = Transaction(inputs=inputs, outputs=outputs)
    for idx in range(len(inputs)):
        tx.sign_input(idx, priv)

    ok, reason = chain.add_transaction_to_mempool(tx)
    if not ok:
        raise HTTPException(status_code=400, detail=f"Transaction rejected: {reason}")

    await broadcast_event("new_tx", tx.to_dict())
    asyncio.create_task(p2p.broadcast_tx(tx))
    return {
        "status": "broadcasted",
        "txid": tx.txid,
        "from_address": req.from_address,
        "to_address": req.to_address,
        "amount_doom": req.amount_doom,
        "fee_doom": fee_sparks / COIN
    }


@app.post("/rpc/exchange/broadcast_raw", dependencies=[Depends(verify_exchange_auth)])
async def exchange_broadcast_raw(req: ExchangeRawTxRequest):
    """Broadcast an externally pre-signed transaction to the network."""
    try:
        tx = Transaction.from_dict(req.transaction)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Malformed transaction structure: {e}")

    ok, reason = chain.add_transaction_to_mempool(tx)
    if not ok:
        raise HTTPException(status_code=400, detail=f"Transaction rejected: {reason}")

    await broadcast_event("new_tx", tx.to_dict())
    asyncio.create_task(p2p.broadcast_tx(tx))
    return {"status": "broadcasted", "txid": tx.txid}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_sockets.append(websocket)
    try:
        # Send initial status
        tip = chain.get_tip()
        now = time.time()
        active_workers_list = [m for m in active_miners.values() if now - m.get("last_seen", 0) < 15]
        total_mhs = sum(m.get("hashrate_mhs", 0.0) for m in active_workers_list)
        await websocket.send_text(json.dumps({
            "type": "init",
            "data": {
                "tip": tip.to_dict(),
                "total_blocks": len(chain.blocks),
                "active_workers": len(active_workers_list),
                "cluster_hashrate_mhs": round(total_mhs, 2)
            }
        }))
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in connected_sockets:
            connected_sockets.remove(websocket)


# Mount static web explorer
web_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web")
if os.path.exists(web_dir):
    app.mount("/static", StaticFiles(directory=web_dir), name="static")

    @app.get("/")
    @app.head("/")
    def index():
        return FileResponse(os.path.join(web_dir, "index.html"))

    @app.api_route("/SHA256SUMS.txt", methods=["GET", "HEAD"])
    @app.api_route("/download/SHA256SUMS.txt", methods=["GET", "HEAD"])
    def get_checksums():
        sums_file = os.path.join(web_dir, "SHA256SUMS.txt")
        if os.path.exists(sums_file):
            return FileResponse(sums_file, media_type="text/plain")
        root_sums = os.path.join(os.path.dirname(os.path.dirname(__file__)), "SHA256SUMS.txt")
        if os.path.exists(root_sums):
            return FileResponse(root_sums, media_type="text/plain")
        raise HTTPException(status_code=404, detail="SHA256SUMS.txt not found")

    @app.api_route("/docs", methods=["GET", "HEAD"])
    @app.api_route("/whitepaper", methods=["GET", "HEAD"])
    def get_docs():
        return FileResponse(os.path.join(web_dir, "docs.html"))

    @app.api_route("/wallet", methods=["GET", "HEAD"])
    def get_wallet_page():
        return FileResponse(os.path.join(web_dir, "wallet.html"))

    @app.api_route("/pay", methods=["GET", "HEAD"])
    def get_pay_page():
        return FileResponse(os.path.join(web_dir, "pay.html"))

    @app.api_route("/pay.js", methods=["GET", "HEAD"])
    def get_pay_js():
        return FileResponse(
            os.path.join(web_dir, "pay.js"),
            media_type="application/javascript",
            headers={"Access-Control-Allow-Origin": "*"}
        )

    def _verify_onchain_payment(txid: str = "", to: str = "", amount: float = 0.0, since: int = 0) -> Dict[str, Any]:
        import urllib.request
        txid = (txid or "").strip()
        to = (to or "").strip()
        req_amt = float(amount or 0.0)

        # 1. Base Mainnet wDOOM (0x... 66-char tx hash)
        if txid.startswith("0x") and len(txid) == 66:
            wdoom_contract = "0x623c84a5e04bf715018203334b0efe41696ebc3e"
            transfer_topic = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
            rpc_payload = json.dumps({
                "jsonrpc": "2.0",
                "id": 1,
                "method": "eth_getTransactionReceipt",
                "params": [txid]
            }).encode("utf-8")
            try:
                req = urllib.request.Request(
                    "https://mainnet.base.org",
                    data=rpc_payload,
                    headers={"Content-Type": "application/json", "User-Agent": "DoomPay/1.0"}
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    rpc_res = json.loads(resp.read().decode("utf-8"))
                receipt = rpc_res.get("result")
                if not receipt:
                    return {"verified": False, "error": "Transaction receipt not found on Base Mainnet yet"}
                if receipt.get("status") != "0x1":
                    return {"verified": False, "error": "Base transaction reverted"}
                matched_amount = 0.0
                matched_from = ""
                matched_to = ""
                for lg in receipt.get("logs", []):
                    if (lg.get("address") or "").lower() != wdoom_contract:
                        continue
                    topics = lg.get("topics") or []
                    if len(topics) >= 3 and topics[0].lower() == transfer_topic:
                        from_addr = "0x" + topics[1][-40:].lower()
                        to_addr = "0x" + topics[2][-40:].lower()
                        val_wei = int(lg.get("data", "0x0"), 16)
                        val_doom = val_wei / 1e18
                        if not to or to.lower() == to_addr:
                            matched_amount += val_doom
                            matched_from = from_addr
                            matched_to = to_addr
                if matched_amount <= 0:
                    return {"verified": False, "error": "No wDOOM transfer to target recipient found in receipt"}
                if matched_amount + 1e-9 < req_amt:
                    return {
                        "verified": False,
                        "error": f"Insufficient wDOOM amount: paid {matched_amount}, required {req_amt}",
                        "amount_doom": matched_amount
                    }
                return {
                    "verified": True,
                    "chain": "base-mainnet",
                    "chain_id": 8453,
                    "ticker": "wDOOM",
                    "contract": "0x623c84A5E04bF715018203334b0eFE41696eBC3E",
                    "txid": txid,
                    "from": matched_from,
                    "to": matched_to,
                    "amount_doom": matched_amount,
                    "confirmed": True,
                    "confirmations": 1,
                    "block_height": int(receipt.get("blockNumber", "0x0"), 16),
                    "explorer_url": f"https://basescan.org/tx/{txid}"
                }
            except Exception as e:
                return {"verified": False, "error": f"Base RPC verification error: {e}"}

        # 2. Layer-1 DOOM by explicit txid
        if txid:
            tx, b, confs = chain.get_transaction(txid)
            if not tx:
                return {"verified": False, "error": "Layer-1 transaction not found in ledger or mempool"}
            paid_doom = 0.0
            matched_to = to
            for out in tx.outputs:
                if not to or out.recipient == to:
                    paid_doom += (out.amount / COIN)
                    matched_to = out.recipient
            if paid_doom <= 0 or paid_doom + 1e-9 < req_amt:
                return {
                    "verified": False,
                    "error": f"Output to recipient is {paid_doom} DOOM (required {req_amt} DOOM)",
                    "amount_doom": paid_doom
                }
            return {
                "verified": True,
                "chain": "doomsday-l1",
                "ticker": "DOOM",
                "txid": tx.txid,
                "to": matched_to,
                "amount_doom": paid_doom,
                "confirmed": b is not None,
                "confirmations": confs,
                "block_height": b.height if b else None,
                "explorer_url": "https://doomsday.network"
            }

        # 3. Auto-detect recent Layer-1 DOOM payment to `to` address since timestamp
        if to.startswith("doom1"):
            try:
                cutoff = int(since) if since else int(time.time()) - 3600
                mempool_txs = list(chain.mempool.values()) if isinstance(chain.mempool, dict) else list(chain.mempool)
                for tx in mempool_txs:
                    outputs = getattr(tx, "outputs", None) or (tx.get("outputs", []) if isinstance(tx, dict) else [])
                    paid = sum((getattr(o, "amount", 0) if not isinstance(o, dict) else o.get("amount", 0)) / COIN for o in outputs if (getattr(o, "recipient", "") if not isinstance(o, dict) else o.get("recipient", "")) == to)
                    if paid > 0 and paid + 1e-9 >= req_amt:
                        txid_val = getattr(tx, "txid", None) or (tx.get("txid") if isinstance(tx, dict) else "")
                        return {
                            "verified": True,
                            "chain": "doomsday-l1",
                            "ticker": "DOOM",
                            "txid": txid_val,
                            "to": to,
                            "amount_doom": paid,
                            "confirmed": False,
                            "confirmations": 0,
                            "block_height": None,
                            "explorer_url": "https://doomsday.network"
                        }
                tip_h = len(chain.blocks) - 1
                for b in reversed(chain.blocks[-120:]):
                    if b.header.timestamp < cutoff:
                        break
                    for tx in b.transactions:
                        if getattr(tx, "is_coinbase", False):
                            continue
                        paid = sum(o.amount / COIN for o in tx.outputs if o.recipient == to)
                        if paid > 0 and paid + 1e-9 >= req_amt:
                            return {
                                "verified": True,
                                "chain": "doomsday-l1",
                                "ticker": "DOOM",
                                "txid": tx.txid,
                                "to": to,
                                "amount_doom": paid,
                                "confirmed": True,
                                "confirmations": max(1, tip_h - b.height + 1),
                                "block_height": b.height,
                                "explorer_url": "https://doomsday.network"
                            }
            except Exception as e:
                return {"verified": False, "error": f"L1 scan error: {e}"}
            return {"verified": False, "error": "No matching Layer-1 payment detected yet"}

        return {"verified": False, "error": "Provide txid (0x... or L1 hex) or a doom1... recipient address"}

    @app.api_route("/pay/verify", methods=["GET", "POST"])
    async def verify_payment_endpoint(
        request: Request,
        txid: str = "",
        to: str = "",
        amount: float = 0.0,
        since: int = 0
    ):
        if request.method == "POST":
            try:
                body = await request.json()
                txid = body.get("txid", txid)
                to = body.get("to") or body.get("recipient") or to
                amount = float(body.get("amount", amount) or 0.0)
                since = int(body.get("since", since) or 0)
            except Exception:
                pass
        return _verify_onchain_payment(txid=txid, to=to, amount=amount, since=since)

    checkout_sessions: Dict[str, Dict[str, Any]] = {}

    @app.post("/v1/checkout/sessions")
    async def create_checkout_session(request: Request):
        """Stripe-style self-custodial Checkout Session creation (supports JSON or form-urlencoded)."""
        import secrets
        from urllib.parse import parse_qs
        data: Dict[str, Any] = {}
        ctype = (request.headers.get("content-type") or "").lower()
        raw_bytes = await request.body()
        if "application/json" in ctype:
            try:
                data = json.loads(raw_bytes.decode("utf-8"))
            except Exception:
                data = {}
        else:
            parsed = parse_qs(raw_bytes.decode("utf-8", errors="replace"))
            data = {k: v[0] for k, v in parsed.items() if v}

        recipient = str(data.get("recipient") or data.get("to") or "").strip()
        if not recipient or not (recipient.startswith("0x") or recipient.startswith("doom1")):
            raise HTTPException(status_code=400, detail="Valid 'recipient' (0x... Base address or doom1... L1 address) is required")
        try:
            amount_doom = float(data.get("amount") or data.get("amount_doom") or 100.0)
        except Exception:
            amount_doom = 100.0
        item = str(data.get("item") or data.get("name") or "Doomsday Checkout").strip()
        success_url = str(data.get("success_url") or "").strip()
        cancel_url = str(data.get("cancel_url") or "").strip()
        webhook_url = str(data.get("webhook_url") or "").strip()

        sid = "cs_live_" + secrets.token_hex(12)
        now_ts = int(time.time())
        session_obj = {
            "id": sid,
            "object": "checkout.session",
            "status": "open",
            "payment_status": "unpaid",
            "recipient": recipient,
            "amount_doom": amount_doom,
            "currency": "wDOOM" if recipient.startswith("0x") else "DOOM",
            "item": item,
            "url": f"https://doomsday.network/pay?session_id={sid}",
            "verify_url": f"https://doomsday.network/v1/checkout/sessions/{sid}",
            "success_url": success_url,
            "cancel_url": cancel_url,
            "webhook_url": webhook_url,
            "txid": None,
            "created": now_ts,
        }
        checkout_sessions[sid] = session_obj
        return session_obj

    @app.api_route("/v1/checkout/sessions/{session_id}", methods=["GET", "POST"])
    async def get_or_verify_checkout_session(session_id: str, request: Request, txid: str = ""):
        if session_id not in checkout_sessions:
            raise HTTPException(status_code=404, detail="Checkout session not found")
        sess = checkout_sessions[session_id]
        if request.method == "POST" and not txid:
            try:
                body = await request.json()
                txid = str(body.get("txid") or "")
            except Exception:
                pass
        if sess["payment_status"] != "paid":
            v = _verify_onchain_payment(
                txid=txid or (sess.get("txid") or ""),
                to=sess["recipient"],
                amount=sess["amount_doom"],
                since=sess["created"] - 30
            )
            if v.get("verified"):
                sess["status"] = "complete"
                sess["payment_status"] = "paid"
                sess["txid"] = v.get("txid")
                sess["chain"] = v.get("chain")
                sess["block_height"] = v.get("block_height")
        return sess

    @app.api_route("/install.sh", methods=["GET", "HEAD"])
    def get_install_script():
        script_path = os.path.join(web_dir, "install.sh")
        return FileResponse(script_path, media_type="text/x-shellscript")

    @app.api_route("/download/desktop", methods=["GET", "HEAD"])
    @app.api_route("/download/latest", methods=["GET", "HEAD"])
    @app.api_route("/download/Doomsday-Windows-x64.zip", methods=["GET", "HEAD"])
    @app.api_route("/download/Doomsday-v1.0.3-windows-x64.zip", methods=["GET", "HEAD"])
    @app.api_route("/download/Doomsday-v1.0.2-windows-x64.zip", methods=["GET", "HEAD"])
    @app.api_route("/download/Doomsday-v1.0.1-windows-x64.zip", methods=["GET", "HEAD"])
    @app.api_route("/download/Doomsday-v1.0.0-windows-x64.zip", methods=["GET", "HEAD"])
    def download_windows_miner():
        return RedirectResponse(
            url="https://github.com/doomsday-network/doomsday/releases/latest/download/Doomsday-Windows-x64.zip",
            status_code=302
        )

    @app.get("/api/version")
    def get_version_info():
        return {
            "version": "1.0.3",
            "tag_name": "v1.0.3",
            "name": "Doomsday Network v1.0.3 - Hybrid CPU Co-Mining, PTX Intrinsic CUDA Solver & Smart Workload Guard",
            "download_url": "https://doomsday.network/download/desktop",
            "release_url": "https://github.com/doomsday-network/doomsday/releases/latest",
            "release_notes": "Miner & Desktop Client Upgrades (v1.0.3):\n- Hybrid CPU Co-Mining & Multi-GPU orchestration in Desktop Client\n- Native C Multi-Core CPU DoomHash engine & hardware PTX funnel-shift/byte-perm CUDA optimizations\n- Smart Workload Guard: automatically yields GPU for Plex transcoding, Sunshine/Moonlight game streaming, XInput gamepads, and MLOps VRAM allocations\n- Pool template FIFO cache hardening & asynchronous non-blocking share/telemetry pipelines."
        }

    @app.api_route("/robots.txt", methods=["GET", "HEAD"])
    def get_robots():
        content = (
            "User-agent: *\n"
            "Allow: /\n"
            "Sitemap: https://doomsday.network/sitemap.xml\n"
        )
        return PlainTextResponse(content)

    @app.api_route("/quickstart.py", methods=["GET", "HEAD"])
    def get_quickstart_script():
        qs_path = os.path.join(os.path.dirname(web_dir), "quickstart.py")
        if os.path.exists(qs_path):
            return FileResponse(qs_path, media_type="text/x-python")
        raise HTTPException(status_code=404, detail="quickstart.py not found")

    @app.api_route("/mine_pool.py", methods=["GET", "HEAD"])
    def get_mine_pool_script():
        mp_path = os.path.join(os.path.dirname(web_dir), "mine_pool.py")
        if os.path.exists(mp_path):
            return FileResponse(mp_path, media_type="text/x-python")
        raise HTTPException(status_code=404, detail="mine_pool.py not found")

    @app.api_route("/scan_bounties.py", methods=["GET", "HEAD"])
    def get_scan_bounties_script():
        sb_path = os.path.join(os.path.dirname(web_dir), "scan_bounties.py")
        if os.path.exists(sb_path):
            return FileResponse(sb_path, media_type="text/x-python")
        raise HTTPException(status_code=404, detail="scan_bounties.py not found")

    @app.api_route("/.well-known/security.txt", methods=["GET", "HEAD"])
    @app.api_route("/security.txt", methods=["GET", "HEAD"])
    def get_security_txt():
        sec_txt = (
            "Contact: https://github.com/doomsday-network/bounty-guard/issues\n"
            "Contact: https://github.com/doomsday-network/doomsday/issues\n"
            "Expires: 2027-12-31T23:59:59.000Z\n"
            "Acknowledgments: https://doomsday.network/escrow/list\n"
            "Preferred-Languages: en\n"
            "Canonical: https://doomsday.network/.well-known/security.txt\n"
            "Policy: https://github.com/doomsday-network/bounty-guard\n"
        )
        return PlainTextResponse(sec_txt)

    @app.api_route("/bounty.py", methods=["GET", "HEAD"])
    def get_bounty_cli_script():
        b_path = os.path.join(os.path.dirname(web_dir), "bounty.py")
        if os.path.exists(b_path):
            return FileResponse(b_path, media_type="text/x-python")
        raise HTTPException(status_code=404, detail="bounty.py not found")

    @app.api_route("/doomsday_mcp.py", methods=["GET", "HEAD"])
    def get_doomsday_mcp_script():
        mcp_path = os.path.join(os.path.dirname(web_dir), "integrations", "mcp", "doomsday_mcp.py")
        if os.path.exists(mcp_path):
            return FileResponse(mcp_path, media_type="text/x-python")
        raise HTTPException(status_code=404, detail="doomsday_mcp.py not found")

    @app.api_route("/SKILL.md", methods=["GET", "HEAD"])
    def get_doomsday_skill_md():
        skill_path = os.path.join(os.path.dirname(web_dir), "integrations", "mcp", "SKILL.md")
        if os.path.exists(skill_path):
            return FileResponse(skill_path, media_type="text/markdown")
        raise HTTPException(status_code=404, detail="SKILL.md not found")

    @app.api_route("/mcp", methods=["GET", "POST"])
    async def handle_remote_mcp(request: Request):
        mcp_tools = [
            {
                "name": "list_escrows",
                "description": "List all open Doomsday Proof-of-Escrow GitHub bounties and verify L1 UTXO vault backing.",
                "inputSchema": {"type": "object", "properties": {}},
                "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True},
            },
            {
                "name": "verify_issue_escrow",
                "description": "Verify on-chain DOOM/wDOOM escrow backing and UTXO outpoint proofs for a GitHub issue (owner/repo#number).",
                "inputSchema": {
                    "type": "object",
                    "properties": {"issue_ref": {"type": "string", "description": "GitHub issue reference, e.g. doomsday-network/doomsday#11"}},
                    "required": ["issue_ref"],
                },
                "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True},
            },
            {
                "name": "get_pool_leaderboard",
                "description": "Get the live Doomsday L1 SHA-256 Proof-of-Work mining pool leaderboard and worker balances.",
                "inputSchema": {"type": "object", "properties": {}},
                "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True},
            },
            {
                "name": "verify_payment",
                "description": "Verify an on-chain DOOM (Layer-1) or wDOOM (Base Mainnet ERC-20) payment receipt for a merchant address and amount.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "txid": {"type": "string", "description": "Base Mainnet 0x... tx hash or Doomsday L1 64-hex txid"},
                        "to": {"type": "string", "description": "Merchant 0x... or doom1... recipient address"},
                        "amount": {"type": "number", "description": "Minimum expected DOOM / wDOOM amount"},
                    },
                },
                "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True},
            },
        ]
        if request.method == "GET":
            return {
                "name": "doomsday-escrow-mcp",
                "version": "1.1.0",
                "protocolVersion": "2025-03-26",
                "endpoint": "https://doomsday.network/mcp",
                "transport": "streamable-http",
                "auth": "none (public read-only)",
                "tools": mcp_tools,
            }
        try:
            msg = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON-RPC payload")
        req_id = msg.get("id")
        method = msg.get("method", "")
        params = msg.get("params") or {}
        if method == "initialize":
            res = {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "doomsday-escrow-mcp", "version": "1.1.0"},
            }
        elif method == "tools/list":
            res = {"tools": mcp_tools}
        elif method == "tools/call":
            tname = params.get("name")
            targs = params.get("arguments") or {}
            if tname == "list_escrows":
                payload = escrow_mgr.list_all()
            elif tname == "verify_issue_escrow":
                cleaned = str(targs.get("issue_ref", "")).strip().replace("#", "/")
                parts = [p for p in cleaned.split("/") if p]
                if len(parts) >= 3:
                    payload = escrow_mgr.verify_issue(parts[-3], parts[-2], int(parts[-1]))
                else:
                    payload = {"error": "Expected owner/repo#number"}
            elif tname == "get_pool_leaderboard":
                payload = {"leaders": pool.get_leaderboard()}
            elif tname == "verify_payment":
                payload = _verify_onchain_payment(
                    txid=str(targs.get("txid", "")),
                    to=str(targs.get("to", "")),
                    amount=float(targs.get("amount", 0.0) or 0.0),
                )
            else:
                payload = {"error": f"Unknown tool: {tname}"}
            res = {"content": [{"type": "text", "text": json.dumps(payload, indent=2)}]}
        else:
            res = {}
        return {"jsonrpc": "2.0", "id": req_id, "result": res}

    @app.api_route("/sitemap.xml", methods=["GET", "HEAD"])
    def get_sitemap():
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://doomsday.network/</loc><changefreq>always</changefreq><priority>1.0</priority></url>
  <url><loc>https://doomsday.network/pay</loc><changefreq>daily</changefreq><priority>0.95</priority></url>
  <url><loc>https://doomsday.network/pay.js</loc><changefreq>weekly</changefreq><priority>0.9</priority></url>
  <url><loc>https://doomsday.network/wallet</loc><changefreq>daily</changefreq><priority>0.9</priority></url>
  <url><loc>https://doomsday.network/docs</loc><changefreq>weekly</changefreq><priority>0.9</priority></url>
  <url><loc>https://doomsday.network/bridge/audit</loc><changefreq>always</changefreq><priority>0.8</priority></url>
  <url><loc>https://doomsday.network/escrow/list</loc><changefreq>always</changefreq><priority>0.9</priority></url>
  <url><loc>https://doomsday.network/quickstart.py</loc><changefreq>weekly</changefreq><priority>0.9</priority></url>
  <url><loc>https://doomsday.network/mine_pool.py</loc><changefreq>weekly</changefreq><priority>0.9</priority></url>
  <url><loc>https://doomsday.network/scan_bounties.py</loc><changefreq>weekly</changefreq><priority>0.8</priority></url>
  <url><loc>https://doomsday.network/tokenlist.json</loc><changefreq>weekly</changefreq><priority>0.8</priority></url>
  <url><loc>https://doomsday.network/llms.txt</loc><changefreq>weekly</changefreq><priority>0.9</priority></url>
  <url><loc>https://doomsday.network/.well-known/security.txt</loc><changefreq>weekly</changefreq><priority>0.8</priority></url>
</urlset>"""
        return Response(content=xml, media_type="application/xml")

    @app.api_route("/8f4d2e9a1c3b7e5f8f4d2e9a1c3b7e5f.txt", methods=["GET", "HEAD"])
    def get_indexnow_key():
        return PlainTextResponse("8f4d2e9a1c3b7e5f8f4d2e9a1c3b7e5f")

    @app.api_route("/llms.txt", methods=["GET", "HEAD"])
    def get_llms_txt():
        content = """# Doomsday Network (DOOM / wDOOM)

> Open-source Layer-1 Proof-of-Idle-Work GPU blockchain (DoomHash CUDA: SHA-256 + 8-round 64-bit golden-ratio permutation) with zero-fee PPLNS mining pool, On-Chain Proof-of-Escrow Bounty Registry, and 1:1 Base Mainnet DeFi bridge (wDOOM).

## Key Facts
- **Native L1 Ticker:** DOOM (Max Supply: 21,000,000 DOOM; Block Reward: 50 DOOM; Halving: 210,000 blocks; Target Block Time: 20s ASERT)
- **Wrapped Base L2 Token:** Wrapped DOOM (`wDOOM`) on Base Mainnet (Chain ID 8453)
- **Verified BaseScan Contract:** `0x623c84A5E04bF715018203334b0eFE41696eBC3E` (https://basescan.org/address/0x623c84A5E04bF715018203334b0eFE41696eBC3E#code)
- **Uniswap v3 Pool (Base Mainnet):** `0xf7217329574249d7b389404aECF2C582662F3659` (LP NFT #6311322 permanently burned to `0x000000000000000000000000000000000000dEaD`)
- **Live Explorer, Faucet & Mining Pool:** https://doomsday.network
- **1-Command Terminal Quickstart:** `curl -sL https://doomsday.network/quickstart.py | python3`
- **1-Command Pool Share Miner:** `curl -sL https://doomsday.network/mine_pool.py | python3 - --wallet YOUR_DOOM1_ADDRESS --shares 1`
- **1-Command GitHub Bounty Scanner:** `curl -sL https://doomsday.network/scan_bounties.py | python3`
- **Remote MCP Server (Streamable HTTP):** https://doomsday.network/mcp
- **On-Chain Escrow Registry API:** https://doomsday.network/escrow/list
- **Proof-of-Reserve Audit API:** https://doomsday.network/bridge/audit

## Official Repositories & Active Bounties
- **Core L1 Node & GPU Miner:** https://github.com/doomsday-network/doomsday
- **BountyGuard Security & Escrow Scanner:** https://github.com/doomsday-network/bounty-guard
- **Standalone CUDA & Python Pool Miner:** https://github.com/doomsday-network/cuda-gpu-miner
- **Live GitHub Bounty Scanner CLI:** https://github.com/doomsday-network/github-bounty-scanner
- **Windows Desktop Client (v1.0.3):** https://doomsday.network/download/desktop
- **DexScreener Chart:** https://dexscreener.com/base/0xf7217329574249d7b389404aECF2C582662F3659
- **GeckoTerminal Chart:** https://www.geckoterminal.com/base/pools/0xf7217329574249d7b389404aecf2c582662f3659
"""
        return PlainTextResponse(content)

    @app.api_route("/tokenlist.json", methods=["GET", "HEAD"])
    def get_tokenlist():
        return {
            "name": "Doomsday Network Official Token List",
            "timestamp": "2026-10-20T00:00:00.000Z",
            "version": {"major": 1, "minor": 0, "patch": 3},
            "logoURI": "https://doomsday.network/static/doom-logo.svg",
            "keywords": ["doomsday", "doom", "wdoom", "base", "pow", "gpu"],
            "tokens": [
                {
                    "chainId": 8453,
                    "address": "0x623c84A5E04bF715018203334b0eFE41696eBC3E",
                    "name": "Wrapped DOOM",
                    "symbol": "wDOOM",
                    "decimals": 18,
                    "logoURI": "https://doomsday.network/static/doom-logo.svg"
                }
            ]
        }


@app.on_event("startup")
async def on_startup():
    p2p.start()


def start_server(host: str = "0.0.0.0", port: int = 8334, peers: Optional[List[str]] = None, exchange_key: Optional[str] = None):
    global EXCHANGE_API_KEY
    if exchange_key:
        EXCHANGE_API_KEY = exchange_key
    import uvicorn
    p2p.listen_port = port
    if peers:
        for p_addr in peers:
            p2p.register_peer(p_addr)
    print(f"\n=======================================================")
    print(f"[*] DOOMSDAY NODE ACTIVE: http://{host}:{port}")
    print(f"P2P Wire Protocol: Node ID [{p2p.node_id}] | Port {port}")
    print(f"Explorer Dashboard: http://localhost:{port}")
    if EXCHANGE_API_KEY:
        print(f"Exchange RPC Auth: ENFORCED (Key: {EXCHANGE_API_KEY[:4]}***)")
    else:
        print(f"Exchange RPC Auth: DISABLED (Set DOOMSDAY_EXCHANGE_KEY or --exchange-key to enable)")
    print(f"=======================================================\n")
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Doomsday Network Node Server")
    parser.add_argument("--host", default="0.0.0.0", help="Binding host")
    parser.add_argument("--web-port", type=int, default=8334, help="HTTP/Explorer port")
    parser.add_argument("--peer", action="append", default=[], help="Connect to specific P2P peer(s)")
    parser.add_argument("--exchange-key", default=None, help="Set API key for /rpc/exchange endpoints")
    args = parser.parse_args()
    start_server(host=args.host, port=args.web_port, peers=args.peer, exchange_key=args.exchange_key)
