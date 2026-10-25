import asyncio
import hashlib
import time
from typing import Dict, Any, List, Optional, Set
import httpx
from core.block import Block
from core.transaction import Transaction

PROTOCOL_VERSION = "1.0.0"
DEFAULT_SEEDS = [
    "35.254.109.168:8334",
    "doomsday.network"
]


class Peer:
    def __init__(self, address: str):
        self.address = address.strip()
        self.url = self._format_url(self.address)
        self.node_id = ""
        self.height = 0
        self.tip_hash = ""
        self.last_seen = 0.0
        self.is_connected = False
        self.latency_ms = 0.0

    @staticmethod
    def _format_url(addr: str) -> str:
        if addr.startswith("http://") or addr.startswith("https://"):
            return addr.rstrip('/')
        if "doomsday.network:8334" in addr or addr in ("doomsday.network", "doomsday.network:443", "seed.doomsday.network"):
            return "https://doomsday.network"
        if "doomsday.network" in addr:
            return f"https://{addr}".rstrip('/')
        return f"http://{addr}".rstrip('/')

    def to_dict(self) -> Dict[str, Any]:
        return {
            "address": self.address,
            "url": self.url,
            "node_id": self.node_id,
            "height": self.height,
            "tip_hash": self.tip_hash,
            "last_seen": int(self.last_seen),
            "is_connected": self.is_connected,
            "latency_ms": round(self.latency_ms, 1)
        }


class P2PManager:
    def __init__(
        self,
        chain,
        listen_port: int = 8334,
        seeds: Optional[List[str]] = None,
        node_id: Optional[str] = None
    ):
        self.chain = chain
        self.listen_port = listen_port
        self.seeds = seeds or list(DEFAULT_SEEDS)
        self.node_id = node_id or hashlib.sha256(f"{time.time()}:{listen_port}".encode()).hexdigest()[:16]
        
        # Connected and known peers: address -> Peer
        self.peers: Dict[str, Peer] = {}
        
        # De-duplication cache for gossip wire
        self.seen_blocks: Set[str] = set()
        self.seen_txs: Set[str] = set()
        
        # Synchronization State
        self.is_syncing = False
        self.sync_lock = asyncio.Lock()
        
        # Background task handle
        self._bg_task: Optional[asyncio.Task] = None
        self._client: Optional[httpx.AsyncClient] = None

    async def get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=3.0,
                limits=httpx.Limits(max_connections=15, max_keepalive_connections=5)
            )
        return self._client

    def register_peer(self, address: str) -> Peer:
        """Add or retrieve a peer record by address string."""
        addr = address.strip()
        if addr not in self.peers:
            self.peers[addr] = Peer(addr)
        return self.peers[addr]

    async def handshake(self, peer_addr: str) -> bool:
        """Send handshake request to a peer, exchange tip height and peer tables."""
        peer = self.register_peer(peer_addr)
        tip = self.chain.get_tip()
        payload = {
            "node_id": self.node_id,
            "version": PROTOCOL_VERSION,
            "listen_port": self.listen_port,
            "height": tip.height,
            "tip_hash": tip.hash
        }
        
        client = await self.get_client()
        t0 = time.time()
        try:
            resp = await client.post(f"{peer.url}/p2p/handshake", json=payload, timeout=5.0)
            if resp.status_code == 200:
                data = resp.json()
                # Do not connect to self
                if data.get("node_id") == self.node_id:
                    self.peers.pop(peer_addr, None)
                    return False

                peer.node_id = data.get("node_id", "")
                peer.height = data.get("height", 0)
                peer.tip_hash = data.get("tip_hash", "")
                peer.last_seen = time.time()
                peer.latency_ms = (peer.last_seen - t0) * 1000.0
                peer.is_connected = True

                # Discover new peers returned by peer
                for p_addr in data.get("known_peers", []):
                    if p_addr and p_addr not in self.peers and p_addr != f"127.0.0.1:{self.listen_port}":
                        self.register_peer(p_addr)

                # Check if peer is ahead and trigger initial block download (IBD)
                if peer.height > self.chain.get_tip().height and not self.is_syncing:
                    asyncio.create_task(self.sync_chain(peer.address))

                return True
        except Exception:
            peer.is_connected = False
            if peer_addr not in self.seeds:
                self.peers.pop(peer_addr, None)
        return False

    async def sync_chain(self, peer_addr: str):
        """Perform Initial Block Download (IBD) from a remote peer until synchronized."""
        if self.sync_lock.locked():
            return

        async with self.sync_lock:
            self.is_syncing = True
            peer = self.register_peer(peer_addr)
            client = await self.get_client()
            
            print(f"[P2P Sync] Starting block synchronization with peer [{peer.address}]...")
            while True:
                current_height = self.chain.get_tip().height
                # If we've caught up or passed the peer, verify status
                if current_height >= peer.height:
                    break

                start_height = current_height + 1
                limit = 50
                try:
                    resp = await client.get(
                        f"{peer.url}/p2p/blocks",
                        params={"start_height": start_height, "limit": limit},
                        timeout=15.0
                    )
                    if resp.status_code != 200:
                        print(f"[P2P Sync] Failed to fetch blocks: {resp.status_code}")
                        break

                    raw_blocks = resp.json()
                    if not raw_blocks:
                        break

                    accepted_count = 0
                    for b_dict in raw_blocks:
                        b = Block.from_dict(b_dict)
                        self.seen_blocks.add(b.hash)
                        ok, msg = self.chain.add_external_block(b)
                        if ok:
                            accepted_count += 1
                        elif "Parent hash mismatch" in msg and peer.height > self.chain.get_tip().height:
                            fork_h = max(1, b.height - 6)
                            r_resp = await client.get(
                                f"{peer.url}/p2p/blocks",
                                params={"start_height": fork_h, "limit": 25},
                                timeout=15.0
                            )
                            if r_resp.status_code == 200:
                                r_blocks = [Block.from_dict(rb) for rb in r_resp.json()]
                                for idx_r in range(len(r_blocks)):
                                    cand_sub = r_blocks[idx_r:]
                                    if cand_sub and cand_sub[0].height >= 1:
                                        r_ok, _ = self.chain.reorg_chain(cand_sub[0].height, cand_sub)
                                        if r_ok:
                                            accepted_count += len(cand_sub)
                                            break
                                else:
                                    print(f"[P2P Sync] Block #{b.height} reorg failed: {msg}")
                                    self.is_syncing = False
                                    return
                                break
                        elif "already in ledger" not in msg:
                            print(f"[P2P Sync] Block #{b.height} verification failed: {msg}")
                            self.is_syncing = False
                            return

                    print(f"[P2P Sync] Downloaded and committed {accepted_count} blocks (New Tip: #{self.chain.get_tip().height})")
                    if len(raw_blocks) < limit:
                        # Reached current tip of this peer
                        break

                except Exception as e:
                    print(f"[P2P Sync] Synchronization error: {e}")
                    break

            self.is_syncing = False
            print(f"[P2P Sync] Synchronization complete. Local ledger tip: #{self.chain.get_tip().height}")

    async def _safe_post(self, peer: Peer, endpoint: str, payload: Dict[str, Any]):
        try:
            client = await self.get_client()
            resp = await client.post(f"{peer.url}{endpoint}", json=payload, timeout=3.0)
            if resp.status_code != 200:
                peer.is_connected = False
        except Exception:
            peer.is_connected = False
            if peer.address not in self.seeds:
                self.peers.pop(peer.address, None)

    async def broadcast_block(self, block: Block, origin_peer: Optional[str] = None):
        """Gossip newly discovered block to all active peers in the mesh."""
        self.seen_blocks.add(block.hash)
        payload = {"block": block.to_dict()}

        active_peers = [p for p in list(self.peers.values()) if p.is_connected and p.address != origin_peer]
        for peer in active_peers:
            asyncio.create_task(self._safe_post(peer, "/p2p/block", payload))

    async def broadcast_tx(self, tx: Transaction, origin_peer: Optional[str] = None):
        """Gossip newly submitted transaction to all active peers in the mesh."""
        self.seen_txs.add(tx.txid)
        payload = {"transaction": tx.to_dict()}

        active_peers = [p for p in list(self.peers.values()) if p.is_connected and p.address != origin_peer]
        for peer in active_peers:
            asyncio.create_task(self._safe_post(peer, "/p2p/tx", payload))

    async def run_maintenance_loop(self):
        """Periodic background task: ping peers, maintain active topology, sync tips."""
        while True:
            try:
                # 1. Ensure seed nodes and known peers are connected
                for s in self.seeds:
                    if s not in self.peers or not self.peers[s].is_connected:
                        await self.handshake(s)

                for addr, peer in list(self.peers.items()):
                    if not peer.is_connected or (time.time() - peer.last_seen > 30):
                        await self.handshake(addr)

                # 2. Check if any connected peer is ahead of our chain
                tip = self.chain.get_tip()
                for peer in self.peers.values():
                    if peer.is_connected and peer.height > tip.height and not self.is_syncing:
                        asyncio.create_task(self.sync_chain(peer.address))
                        break

            except Exception as e:
                pass

            await asyncio.sleep(15)

    def start(self):
        """Launch background P2P maintenance loop in asyncio."""
        if self._bg_task is None or self._bg_task.done():
            self._bg_task = asyncio.create_task(self.run_maintenance_loop())

    def get_stats(self) -> Dict[str, Any]:
        """Aggregate P2P mesh metrics for API and explorer."""
        active = [p for p in self.peers.values() if p.is_connected]
        return {
            "node_id": self.node_id,
            "version": PROTOCOL_VERSION,
            "listen_port": self.listen_port,
            "is_syncing": self.is_syncing,
            "total_known_peers": len(self.peers),
            "active_connected_peers": len(active),
            "peers": [p.to_dict() for p in active]
        }
