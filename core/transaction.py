import hashlib
import json
import time
from typing import List, Dict, Any, Optional
from cryptography.hazmat.primitives import serialization
from core.crypto import sign_message, verify_signature, public_key_to_address

COIN = 100_000_000  # 1 DOOM = 100,000,000 Sparks (atomic units)


class TxInput:
    def __init__(self, txid: str, vout: int, signature: str = "", pubkey_hex: str = ""):
        self.txid = txid
        self.vout = vout
        self.signature = signature
        self.pubkey_hex = pubkey_hex

    def to_dict(self) -> Dict[str, Any]:
        return {
            "txid": self.txid,
            "vout": self.vout,
            "signature": self.signature,
            "pubkey_hex": self.pubkey_hex
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TxInput':
        return cls(
            txid=data["txid"],
            vout=data["vout"],
            signature=data.get("signature", ""),
            pubkey_hex=data.get("pubkey_hex", "")
        )


class TxOutput:
    def __init__(self, recipient: str, amount: int):
        self.recipient = recipient
        self.amount = int(amount)  # Stored in Sparks

    def to_dict(self) -> Dict[str, Any]:
        return {
            "recipient": self.recipient,
            "amount": self.amount
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TxOutput':
        return cls(
            recipient=data["recipient"],
            amount=int(data["amount"])
        )


class Transaction:
    def __init__(
        self,
        inputs: List[TxInput],
        outputs: List[TxOutput],
        timestamp: Optional[int] = None,
        is_coinbase: bool = False,
        extra_data: str = "",
        txid: Optional[str] = None
    ):
        self.inputs = inputs
        self.outputs = outputs
        self.timestamp = timestamp if timestamp is not None else int(time.time())
        self.is_coinbase = is_coinbase
        self.extra_data = extra_data
        self.txid = txid if txid is not None else self.calculate_txid()

    def calculate_txid(self) -> str:
        """Calculate canonical TXID hash."""
        summary = {
            "inputs": [{"txid": i.txid, "vout": i.vout} for i in self.inputs],
            "outputs": [o.to_dict() for o in self.outputs],
            "timestamp": self.timestamp,
            "is_coinbase": self.is_coinbase,
            "extra_data": self.extra_data
        }
        encoded = json.dumps(summary, sort_keys=True).encode()
        return hashlib.sha256(encoded).hexdigest()

    def get_signing_bytes(self, input_index: int) -> bytes:
        """Derive digest bytes to sign for a specific input."""
        summary = {
            "inputs": [{"txid": i.txid, "vout": i.vout} for i in self.inputs],
            "outputs": [o.to_dict() for o in self.outputs],
            "timestamp": self.timestamp,
            "signing_input_index": input_index
        }
        return hashlib.sha256(json.dumps(summary, sort_keys=True).encode()).digest()

    def sign_input(self, input_index: int, private_key):
        """Sign a specific input using the owner's private key."""
        msg = self.get_signing_bytes(input_index)
        sig = sign_message(private_key, msg)
        pub_bytes = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.X962,
            format=serialization.PublicFormat.CompressedPoint
        )
        self.inputs[input_index].signature = sig.hex()
        self.inputs[input_index].pubkey_hex = pub_bytes.hex()
        self.txid = self.calculate_txid()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "txid": self.txid,
            "inputs": [i.to_dict() for i in self.inputs],
            "outputs": [o.to_dict() for o in self.outputs],
            "timestamp": self.timestamp,
            "is_coinbase": self.is_coinbase,
            "extra_data": self.extra_data
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any], trust_cached: bool = False) -> 'Transaction':
        return cls(
            inputs=[TxInput.from_dict(i) for i in data["inputs"]],
            outputs=[TxOutput.from_dict(o) for o in data["outputs"]],
            timestamp=data["timestamp"],
            is_coinbase=data.get("is_coinbase", False),
            extra_data=data.get("extra_data", ""),
            txid=data.get("txid") if trust_cached else None
        )


def create_coinbase_tx(
    recipient: str,
    amount_sparks: int,
    block_height: int,
    message: str = "",
    timestamp: Optional[int] = None
) -> Transaction:
    """Create the subsidy transaction rewarding the miner."""
    extra = f"Height:{block_height} | {message}".strip(" | ")
    tx = Transaction(
        inputs=[TxInput(txid="0" * 64, vout=block_height, signature="", pubkey_hex="")],
        outputs=[TxOutput(recipient=recipient, amount=amount_sparks)],
        timestamp=timestamp,
        is_coinbase=True,
        extra_data=extra
    )
    return tx
