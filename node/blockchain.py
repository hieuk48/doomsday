from contextlib import closing
import hashlib
import json
import os
import sqlite3
import struct
import time
from typing import Dict, List, Optional, Tuple, Any
from core.crypto import bits_to_target, target_to_bits, INITIAL_BITS
from core.transaction import Transaction, TxInput, TxOutput, create_coinbase_tx, COIN
from core.block import Block, BlockHeader, calculate_merkle_root, create_genesis_block
from core.consensus import validate_block, calculate_next_bits, get_block_reward, validate_transaction


class Blockchain:
    def __init__(self, db_path: str = "data/doomsday.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        self.blocks: List[Block] = []
        self.utxo_set: Dict[str, Tuple[str, int]] = {}  # f"{txid}:{vout}" -> (recipient, amount)
        self.mempool: List[Transaction] = []
        self.active_templates: Dict[Tuple[str, int, int], Dict[str, Any]] = {}
        self._init_db()
        self._load_or_genesis()

    def _init_db(self):
        with closing(sqlite3.connect(self.db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS blocks (
                    height INTEGER PRIMARY KEY,
                    hash TEXT UNIQUE,
                    header_json TEXT,
                    txs_json TEXT,
                    timestamp INTEGER
                )
            """)
            conn.commit()

    def _load_or_genesis(self):
        with closing(sqlite3.connect(self.db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT height, hash, header_json, txs_json FROM blocks ORDER BY height ASC")
            rows = cursor.fetchall()

            if not rows:
                print("[Blockchain] Initializing Genesis Block...")
                genesis = create_genesis_block()
                self._save_block_to_db(genesis, conn)
                self.blocks.append(genesis)
                self._apply_block_utxos(genesis)
                print(f"[Blockchain] Genesis Block created at height 0 (Hash: {genesis.hash[:16]}...)")
            else:
                for row in rows:
                    height, b_hash, h_json, t_json = row
                    header = BlockHeader.from_dict(json.loads(h_json))
                    txs = [Transaction.from_dict(t, trust_cached=True) for t in json.loads(t_json)]
                    b = Block(header=header, transactions=txs, height=height, block_hash=b_hash)
                    self.blocks.append(b)
                    self._apply_block_utxos(b)
                print(f"[Blockchain] Loaded {len(self.blocks)} blocks from database. Tip height: {self.get_tip().height}")

    def _save_block_to_db(self, block: Block, conn: sqlite3.Connection):
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO blocks (height, hash, header_json, txs_json, timestamp) VALUES (?, ?, ?, ?, ?)",
            (
                block.height,
                block.hash,
                json.dumps(block.header.to_dict()),
                json.dumps([tx.to_dict() for tx in block.transactions]),
                block.header.timestamp
            )
        )
        conn.commit()

    def _apply_block_utxos(self, block: Block):
        for tx in block.transactions:
            if not tx.is_coinbase:
                for inp in tx.inputs:
                    key = f"{inp.txid}:{inp.vout}"
                    self.utxo_set.pop(key, None)
            for vout, out in enumerate(tx.outputs):
                key = f"{tx.txid}:{vout}"
                self.utxo_set[key] = (out.recipient, out.amount)

    def get_tip(self) -> Block:
        return self.blocks[-1]

    def get_anchor_block(self) -> Block:
        """Anchor for ASERT retargeting (looks back 10 blocks or to genesis)."""
        idx = max(0, len(self.blocks) - 10)
        return self.blocks[idx]

    def get_next_bits(self, current_timestamp: Optional[int] = None) -> int:
        if len(self.blocks) <= 1:
            return INITIAL_BITS
        now_ts = current_timestamp if current_timestamp is not None else int(time.time())
        return calculate_next_bits(self.get_tip(), self.get_anchor_block(), current_timestamp=now_ts)

    def create_block_template(
        self,
        miner_address: str,
        timestamp: Optional[int] = None,
        cache: bool = True
    ) -> Dict[str, Any]:
        """Generate a complete mining job template for worker rigs."""
        tip = self.get_tip()
        height = tip.height + 1
        if timestamp is not None and timestamp > tip.header.timestamp:
            now_ts = int(timestamp)
        else:
            now_ts = max(tip.header.timestamp + 1, int(time.time()))
        if cache and not self.mempool and (miner_address, height, now_ts) in self.active_templates:
            return self.active_templates[(miner_address, height, now_ts)]

        bits = self.get_next_bits(current_timestamp=now_ts)
        target = bits_to_target(bits)
        reward = get_block_reward(height)

        # Include valid transactions from mempool
        txs_to_include = list(self.mempool)
        tx_fees = 0
        valid_txs = []
        if txs_to_include:
            temp_utxos = dict(self.utxo_set)
            stale_txids = set()
            for tx in txs_to_include:
                total_in = 0
                valid = True
                for inp in tx.inputs:
                    key = f"{inp.txid}:{inp.vout}"
                    if key not in temp_utxos:
                        valid = False
                        stale_txids.add(tx.txid)
                        break
                    total_in += temp_utxos[key][1]
                if valid:
                    total_out = sum(o.amount for o in tx.outputs)
                    if total_in >= total_out:
                        tx_fees += (total_in - total_out)
                        for inp in tx.inputs:
                            del temp_utxos[f"{inp.txid}:{inp.vout}"]
                        valid_txs.append(tx)
            if stale_txids:
                self.mempool = [t for t in self.mempool if t.txid not in stale_txids]

        coinbase = create_coinbase_tx(
            recipient=miner_address,
            amount_sparks=reward + tx_fees,
            block_height=height
        )

        all_txs = [coinbase] + valid_txs
        merkle = calculate_merkle_root(all_txs)

        header = BlockHeader(
            version=1,
            prev_hash=tip.hash,
            merkle_root=merkle,
            timestamp=now_ts,
            bits=bits,
            nonce=0,
            miner_address=miner_address
        )

        prefix = header.get_prefix_bytes()
        seed = hashlib.sha256(prefix).digest()
        seed_u64 = list(struct.unpack('<4Q', seed))

        # Upper 64 bits of target for GPU filter
        target_high = (target >> 192) & 0xFFFFFFFFFFFFFFFF

        template = {
            "height": height,
            "prev_hash": tip.hash,
            "merkle_root": merkle,
            "timestamp": now_ts,
            "bits": bits,
            "target_hex": hex(target),
            "target_high": target_high,
            "header_prefix_hex": prefix.hex(),
            "seed_u64": seed_u64,
            "miner_address": miner_address,
            "transactions": [tx.to_dict() for tx in all_txs]
        }
        if cache:
            self.active_templates[(miner_address, height, now_ts)] = template
            if len(self.active_templates) > 500:
                stale_keys = [k for k in self.active_templates if k[1] < height]
                for k in stale_keys:
                    self.active_templates.pop(k, None)
                while len(self.active_templates) > 500:
                    oldest_key = next(iter(self.active_templates))
                    self.active_templates.pop(oldest_key, None)
        return template

    def add_block_candidate(
        self,
        height: int,
        nonce: int,
        miner_address: str,
        miner_name: str = "Rig-Default",
        timestamp: Optional[int] = None
    ) -> Tuple[bool, str]:
        """Validate and commit a mined block candidate from a worker."""
        tip = self.get_tip()
        if height != tip.height + 1:
            return False, f"Stale block height: expected {tip.height + 1}, got {height}"

        # Reconstruct block from template (using cached template if available)
        template = None
        if timestamp is not None and (miner_address, height, timestamp) in self.active_templates:
            template = self.active_templates[(miner_address, height, timestamp)]
        
        if template is None:
            template = self.create_block_template(miner_address, timestamp=timestamp)
        block_time = timestamp if timestamp is not None else template["timestamp"]

        header = BlockHeader(
            version=1,
            prev_hash=template["prev_hash"],
            merkle_root=template["merkle_root"],
            timestamp=block_time,
            bits=template["bits"],
            nonce=nonce,
            miner_address=miner_address
        )
        txs = [Transaction.from_dict(t) for t in template["transactions"]]
        block = Block(header=header, transactions=txs, height=height)

        # Validate with consensus engine
        ok, reason = validate_block(block, tip, self.utxo_set, expected_bits=template["bits"])
        if not ok:
            return False, f"Consensus check failed: {reason}"

        # Commit to ledger
        with closing(sqlite3.connect(self.db_path)) as conn:
            self._save_block_to_db(block, conn)

        self.blocks.append(block)
        self._apply_block_utxos(block)

        # Remove committed transactions from mempool
        committed_ids = {tx.txid for tx in block.transactions}
        self.mempool = [t for t in self.mempool if t.txid not in committed_ids]

        print(f"\n[Blockchain] [*] Block #{block.height} minted by [{miner_name}] ({miner_address[:12]}...) | Nonce: {nonce} | Hash: {block.hash[:16]}...")
        return True, "Accepted"

    def add_external_block(self, block: Block) -> Tuple[bool, str]:
        """Validate and commit a block received over P2P wire from a network peer."""
        tip = self.get_tip()
        if block.height <= tip.height:
            for b in self.blocks:
                if b.hash == block.hash:
                    return False, "Block already in ledger"
            return False, f"Stale block height: received {block.height}, tip is {tip.height}"

        if block.height != tip.height + 1:
            return False, f"Block height gap: expected {tip.height + 1}, got {block.height}"

        if block.header.prev_hash != tip.hash:
            return False, f"Parent hash mismatch: expected {tip.hash[:16]}..., got {block.header.prev_hash[:16]}..."

        expected_bits = self.get_next_bits(current_timestamp=block.header.timestamp)
        ok, reason = validate_block(block, tip, self.utxo_set, expected_bits=expected_bits)
        if not ok:
            return False, f"Consensus check failed: {reason}"

        with closing(sqlite3.connect(self.db_path)) as conn:
            self._save_block_to_db(block, conn)

        self.blocks.append(block)
        self._apply_block_utxos(block)

        committed_ids = {tx.txid for tx in block.transactions}
        self.mempool = [t for t in self.mempool if t.txid not in committed_ids]

        print(f"\n[Blockchain] [P2P] Block #{block.height} accepted via Wire Gossip | Hash: {block.hash[:16]}...")
        return True, "Accepted"

    def reorg_chain(self, fork_height: int, candidate_blocks: List[Block], max_reorg_depth: int = 12) -> Tuple[bool, str]:
        """
        Safely reorganize the tip of the ledger onto a longer valid peer branch
        when a shallow 1-to-N block orphan split occurs.
        """
        tip = self.get_tip()
        if not candidate_blocks:
            return False, "Empty candidate branch"
        if fork_height < 1 or fork_height > tip.height:
            return False, f"Invalid fork height {fork_height}"
        if (tip.height - fork_height + 1) > max_reorg_depth:
            return False, f"Reorg depth exceeds finality guard ({max_reorg_depth} blocks)"
        if candidate_blocks[-1].height <= tip.height:
            return False, "Candidate branch is not longer than local chain"
        if candidate_blocks[0].header.prev_hash != self.blocks[fork_height - 1].hash:
            return False, f"Reorg parent mismatch at #{fork_height}"

        temp_blocks = list(self.blocks[:fork_height])
        temp_utxos: Dict[str, Tuple[str, int]] = {}
        for b in temp_blocks:
            for tx in b.transactions:
                if not tx.is_coinbase:
                    for inp in tx.inputs:
                        temp_utxos.pop(f"{inp.txid}:{inp.vout}", None)
                for vout, out in enumerate(tx.outputs):
                    temp_utxos[f"{tx.txid}:{vout}"] = (out.recipient, out.amount)

        for cand in candidate_blocks:
            if cand.height < fork_height:
                continue
            prev_b = temp_blocks[-1]
            if cand.height != prev_b.height + 1:
                return False, f"Reorg height gap at #{cand.height}"
            if cand.header.prev_hash != prev_b.hash:
                return False, f"Reorg parent mismatch at #{cand.height}"
            anchor_b = temp_blocks[max(0, len(temp_blocks) - 10)]
            exp_bits = calculate_next_bits(prev_b, anchor_b, current_timestamp=cand.header.timestamp) if len(temp_blocks) > 1 else INITIAL_BITS
            ok, reason = validate_block(cand, prev_b, temp_utxos, expected_bits=exp_bits)
            if not ok:
                return False, f"Invalid candidate block #{cand.height}: {reason}"

            temp_blocks.append(cand)
            for tx in cand.transactions:
                if not tx.is_coinbase:
                    for inp in tx.inputs:
                        temp_utxos.pop(f"{inp.txid}:{inp.vout}", None)
                for vout, out in enumerate(tx.outputs):
                    temp_utxos[f"{tx.txid}:{vout}"] = (out.recipient, out.amount)

        with closing(sqlite3.connect(self.db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM blocks WHERE height >= ?", (fork_height,))
            for cand in temp_blocks[fork_height:]:
                cursor.execute(
                    "INSERT INTO blocks (height, hash, header_json, txs_json, timestamp) VALUES (?, ?, ?, ?, ?)",
                    (
                        cand.height,
                        cand.hash,
                        json.dumps(cand.header.to_dict()),
                        json.dumps([tx.to_dict() for tx in cand.transactions]),
                        cand.header.timestamp
                    )
                )
            conn.commit()

        self.blocks = temp_blocks
        self.utxo_set = temp_utxos
        print(f"\n[Blockchain] [Reorg] Switched from orphan fork at #{fork_height} to canonical tip #{self.get_tip().height}")
        return True, "Reorg complete"

    def get_mempool_spent_outpoints(self) -> set:
        """Return set of outpoints currently spent by pending transactions in mempool."""
        spent = set()
        for tx in self.mempool:
            for inp in tx.inputs:
                spent.add(f"{inp.txid}:{inp.vout}")
        return spent

    def get_balance(self, address: str) -> int:
        """Return spendable balance in Sparks for a given address."""
        spent_in_mempool = self.get_mempool_spent_outpoints()
        total = 0
        for outpoint, (recipient, amount) in self.utxo_set.items():
            if recipient == address and outpoint not in spent_in_mempool:
                total += amount
        return total

    def get_address_utxos(self, address: str) -> List[Dict[str, Any]]:
        """Return list of active unspent outputs for an address (excluding mempool-locked inputs)."""
        spent_in_mempool = self.get_mempool_spent_outpoints()
        results = []
        for outpoint, (recipient, amount_sparks) in self.utxo_set.items():
            if recipient == address and outpoint not in spent_in_mempool:
                txid, vout = outpoint.split(':')
                results.append({
                    "txid": txid,
                    "vout": int(vout),
                    "amount": amount_sparks,
                    "amount_sparks": amount_sparks,
                    "amount_doom": amount_sparks / COIN
                })
        return results

    def get_block(self, identifier: Any) -> Optional[Block]:
        """Lookup block by height (int) or block hash (str)."""
        if isinstance(identifier, int):
            if 0 <= identifier < len(self.blocks):
                return self.blocks[identifier]
            return None
        if isinstance(identifier, str):
            if identifier.isdigit():
                h = int(identifier)
                if 0 <= h < len(self.blocks):
                    return self.blocks[h]
            for b in reversed(self.blocks):
                if b.hash == identifier or b.hash.startswith(identifier):
                    return b
        return None

    def get_transaction(self, txid: str) -> Tuple[Optional[Transaction], Optional[Block], int]:
        """
        Lookup transaction by txid.
        Returns: (transaction, block_found_in, confirmations)
        If in mempool: (transaction, None, 0)
        If not found: (None, None, 0)
        """
        for tx in self.mempool:
            if tx.txid == txid:
                return tx, None, 0

        tip_height = self.get_tip().height
        for b in reversed(self.blocks):
            for tx in b.transactions:
                if tx.txid == txid:
                    confirmations = tip_height - b.height + 1
                    return tx, b, confirmations

        return None, None, 0

    def add_transaction_to_mempool(self, tx: Transaction) -> Tuple[bool, str]:
        """Validate and admit a standard user transaction to mempool."""
        for existing in self.mempool:
            if existing.txid == tx.txid:
                return False, "Duplicate transaction already in mempool"
        mempool_spent = self.get_mempool_spent_outpoints()
        for inp in tx.inputs:
            if f"{inp.txid}:{inp.vout}" in mempool_spent:
                return False, "Input UTXO already spent by pending mempool transaction"
        if not validate_transaction(tx, self.utxo_set):
            return False, "Invalid transaction signatures or double spend"
        self.mempool.append(tx)
        return True, "Added to mempool"
