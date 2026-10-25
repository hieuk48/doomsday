import hashlib
import json
import struct
import time
from typing import List, Dict, Any, Optional
from core.crypto import doom_hash, INITIAL_BITS, bits_to_target
from core.transaction import Transaction, create_coinbase_tx, COIN


def calculate_merkle_root(transactions: List[Transaction]) -> str:
    """Calculate standard binary Merkle Root hash from list of transactions."""
    if not transactions:
        return "0" * 64

    hashes = [bytes.fromhex(tx.txid) for tx in transactions]

    while len(hashes) > 1:
        if len(hashes) % 2 != 0:
            hashes.append(hashes[-1])  # Duplicate last element if odd

        next_level = []
        for i in range(0, len(hashes), 2):
            combined = hashes[i] + hashes[i + 1]
            next_level.append(hashlib.sha256(combined).digest())
        hashes = next_level

    return hashes[0].hex()


class BlockHeader:
    def __init__(
        self,
        version: int,
        prev_hash: str,
        merkle_root: str,
        timestamp: int,
        bits: int,
        nonce: int = 0,
        miner_address: str = ""
    ):
        self.version = version
        self.prev_hash = prev_hash
        self.merkle_root = merkle_root
        self.timestamp = timestamp
        self.bits = bits
        self.nonce = nonce
        self.miner_address = miner_address

    def get_prefix_bytes(self) -> bytes:
        """
        Serialize header metadata (excluding nonce) into consistent byte format for DoomHash seed.
        """
        prev_b = bytes.fromhex(self.prev_hash) if self.prev_hash else b'\x00' * 32
        merkle_b = bytes.fromhex(self.merkle_root) if self.merkle_root else b'\x00' * 32
        addr_b = self.miner_address.encode('utf-8').ljust(48, b'\x00')[:48]

        prefix = struct.pack(
            '<I32s32sQII48s',
            self.version,
            prev_b,
            merkle_b,
            self.timestamp,
            self.bits,
            0,  # Reserved padding
            addr_b
        )
        return prefix

    def calculate_hash(self) -> str:
        """Execute DoomHash on this block header with its current nonce."""
        prefix = self.get_prefix_bytes()
        digest = doom_hash(prefix, self.nonce)
        return digest.hex()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "prev_hash": self.prev_hash,
            "merkle_root": self.merkle_root,
            "timestamp": self.timestamp,
            "bits": self.bits,
            "nonce": self.nonce,
            "miner_address": self.miner_address
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'BlockHeader':
        return cls(
            version=data["version"],
            prev_hash=data["prev_hash"],
            merkle_root=data["merkle_root"],
            timestamp=data["timestamp"],
            bits=data["bits"],
            nonce=data.get("nonce", 0),
            miner_address=data.get("miner_address", "")
        )


class Block:
    def __init__(self, header: BlockHeader, transactions: List[Transaction], height: int = 0, block_hash: Optional[str] = None):
        self.header = header
        self.transactions = transactions
        self.height = height
        self.hash = block_hash if block_hash is not None else self.header.calculate_hash()

    def update_hash(self):
        self.hash = self.header.calculate_hash()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "height": self.height,
            "hash": self.hash,
            "header": self.header.to_dict(),
            "transactions": [tx.to_dict() for tx in self.transactions]
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Block':
        header = BlockHeader.from_dict(data["header"])
        txs = [Transaction.from_dict(t) for t in data["transactions"]]
        block = cls(header=header, transactions=txs, height=data.get("height", 0))
        block.hash = data.get("hash", block.header.calculate_hash())
        return block


GENESIS_QUOTE = "Doomsday Clock: 90 seconds to midnight. When the world goes dark, the silent silicon awakens."
GENESIS_TIMESTAMP = 1760000000  # Fixed deterministic timestamp for Block #0
GENESIS_COINBASE_TIMESTAMP = 1791423992
GENESIS_NONCE = 1111
GENESIS_HASH = "00000d07471c6ac9087230a51565953a31560592fd591cbd5c4a5fe0a3f1585f"
GENESIS_MERKLE_ROOT = "5ae234b936d16a41a8f7132ca54b53e0ac0d558438d667c8b31087d0ee1f8282"


def create_genesis_block(miner_address: str = "doom1genesis000000000000000000000000000000") -> Block:
    """
    Construct the immutable Genesis Block (#0) of the Doomsday Network.
    Hardcoded with canonical network Genesis parameters for instant, zero-CPU bootstrap.
    """
    coinbase = create_coinbase_tx(
        recipient=miner_address,
        amount_sparks=50 * COIN,
        block_height=0,
        message=GENESIS_QUOTE,
        timestamp=GENESIS_COINBASE_TIMESTAMP
    )
    merkle_root = calculate_merkle_root([coinbase])
    
    header = BlockHeader(
        version=1,
        prev_hash="0" * 64,
        merkle_root=merkle_root,
        timestamp=GENESIS_TIMESTAMP,
        bits=INITIAL_BITS,
        nonce=GENESIS_NONCE,
        miner_address=miner_address
    )
    
    return Block(header=header, transactions=[coinbase], height=0)
