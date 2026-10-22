"""Independent pure-Python XDR codec for StellarValue, ContractExecutable and
TransactionEnvelope (F-083, F-089).

Transcribed strictly according to RFC 4506 from the authoritative XDR
definitions in ``stellar/stellar-xdr`` at tag ``v28.0`` (commit
``9c9c145953e80990d6ff1ae3a6a973a0ce6d0694``):

- ``Stellar-ledger.x``:
  - ``enum StellarValueType`` (lines 14-19)
  - ``struct LedgerCloseValueSignature`` (lines 20-24)
  - ``struct StellarValue`` (lines 26-57)
  - ``union switch (StellarValueType v)`` (lines 41-56)
- ``Stellar-types.x``:
  - ``typedef opaque Hash[32]`` (line 10)
  - ``typedef uint64 TimePoint`` (line 14)
  - ``enum CryptoKeyType`` (lines 29-38)
  - ``union PublicKey switch (PublicKeyType type)`` (lines 53-57)
  - ``typedef opaque Signature<64>`` (line 80)
  - ``typedef opaque SignatureHint[4]`` (line 82)
  - ``typedef PublicKey NodeID`` (line 84)
  - ``typedef opaque UpgradeType<128>`` (line 94)
  - ``typedef Hash PoolID`` (line 140)
  - ``enum ClaimableBalanceIDType`` (lines 142-146)
  - ``union ClaimableBalanceID switch (ClaimableBalanceIDType type)`` (lines 148-152)
- ``Stellar-contract.x``:
  - ``const SCSYMBOL_LIMIT = 32`` (line 11)
  - ``typedef string SCSymbol<SCSYMBOL_LIMIT>`` (line 12)
  - ``union SCAddress switch (SCAddressType type)`` (lines 85-95)
  - ``typedef string SCString<>`` (line 104)
  - ``enum ContractExecutableType`` (lines 172-177)
  - ``struct ContractExecutableExternalRef`` (lines 182-185)
  - ``union ContractExecutable switch (ContractExecutableType type)`` (lines 229-237)
- ``Stellar-ledger-entries.x``:
  - ``typedef opaque AssetCode4[4]`` (line 19)
  - ``typedef opaque AssetCode12[12]`` (line 22)
  - ``enum AssetType`` (lines 24-30)
  - ``union Asset switch (AssetType type)`` (lines 55-68)
  - ``enum EnvelopeType`` (lines 656-669)
- ``Stellar-transaction.x``:
  - ``const MAX_OPS_PER_TX = 100`` (line 12)
  - ``union MuxedAccount switch (CryptoKeyType type)`` (lines 21-31)
  - ``struct DecoratedSignature`` (lines 33-37)
  - ``enum OperationType`` (lines 39-68)
  - ``struct PaymentOp`` (lines 92-98)
  - ``enum HostFunctionType`` (lines 475-481)
  - ``struct InvokeContractArgs`` (lines 515-519)
  - ``union HostFunction switch (HostFunctionType type)`` (lines 521-531)
  - ``struct InvokeHostFunctionOp`` (lines 623-629)
  - ``struct Operation`` (lines 654-652)
  - ``enum MemoType`` (lines 764-771)
  - ``struct TimeBounds`` (lines 787-791)
  - ``enum PreconditionType`` (lines 832-837)
  - ``union Preconditions switch (PreconditionType type)`` (lines 839-847)
  - ``struct LedgerFootprint`` (lines 850-854)
  - ``struct SorobanResources`` (lines 858-869)
  - ``struct SorobanResourcesExtV0`` (lines 871-877)
  - ``struct SorobanTransactionData`` (lines 880-900)
  - ``struct TransactionV0`` (lines 908-922)
  - ``struct TransactionV0Envelope`` (lines 924-930)
  - ``struct Transaction`` (lines 939-965)
  - ``struct TransactionV1Envelope`` (lines 967-973)
  - ``struct FeeBumpTransaction`` (lines 975-991)
  - ``struct FeeBumpTransactionEnvelope`` (lines 993-999)
  - ``union TransactionEnvelope switch (EnvelopeType type)`` (lines 1002-1010)

Strict RFC 4506 rules implemented:
- All integer and length values are 4-byte or 8-byte big-endian.
- Variable-length opaque and string data must be padded to a 4-byte boundary
  with zero bytes (non-zero padding is rejected).
- Trailing bytes after the top-level structure are rejected.
- Truncated inputs and length prefixes exceeding the remaining buffer are rejected.
- Unknown union discriminants are rejected.

Coverage boundary
-----------------
The codec implements the XDR arms that the pack's fixtures exercise. An arm
the pack does not exercise yet raises an explicit ``XdrCodecError`` that names
the unsupported arm, so a future fixture that needs a wider codec fails loudly
instead of being silently accepted:

- ``OperationType``: ``PAYMENT`` and ``INVOKE_HOST_FUNCTION``.
- ``HostFunctionType``: ``INVOKE_CONTRACT`` and ``UPLOAD_CONTRACT_WASM``.
- ``PreconditionType``: ``PRECOND_NONE`` and ``PRECOND_TIME``.
- ``SCVal`` vectors (contract call arguments), ``LedgerKey`` footprint vectors
  and ``SorobanAuthorizationEntry`` vectors: empty vectors only.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Any, Union


class XdrCodecError(ValueError):
    """Raised when XDR input violates RFC 4506 encoding or type definition rules."""


# ---------------------------------------------------------------- Data Models

# PublicKeyType
PUBLIC_KEY_TYPE_ED25519 = 0


@dataclass(frozen=True)
class PublicKey:
    key_type: int
    ed25519: bytes  # 32 bytes


@dataclass(frozen=True)
class LedgerCloseValueSignature:
    node_id: PublicKey
    signature: bytes  # max 64 bytes


# StellarValueType
STELLAR_VALUE_BASIC = 0
STELLAR_VALUE_SIGNED = 1
STELLAR_VALUE_EMPTY_TX_SET = 2


@dataclass(frozen=True)
class EmptyTxSetProposedValue:
    tx_set_hash: bytes  # 32 bytes
    previous_ledger_hash: bytes  # 32 bytes
    previous_ledger_version: int  # uint32
    lc_value_signature: LedgerCloseValueSignature


@dataclass(frozen=True)
class StellarValueExt:
    ext_type: int  # StellarValueType
    signature: LedgerCloseValueSignature | None = None  # SIGNED
    proposed_value: EmptyTxSetProposedValue | None = None  # EMPTY_TX_SET


@dataclass(frozen=True)
class StellarValue:
    tx_set_hash: bytes  # 32 bytes
    close_time: int  # uint64
    upgrades: list[bytes]  # list of UpgradeType (opaque<128>)
    ext: StellarValueExt


# ContractExecutableType
CONTRACT_EXECUTABLE_WASM = 0
CONTRACT_EXECUTABLE_STELLAR_ASSET = 1
CONTRACT_EXECUTABLE_EXTERNAL_REF = 2

# SCAddressType
SC_ADDRESS_TYPE_ACCOUNT = 0
SC_ADDRESS_TYPE_CONTRACT = 1
SC_ADDRESS_TYPE_MUXED_ACCOUNT = 2
SC_ADDRESS_TYPE_CLAIMABLE_BALANCE = 3
SC_ADDRESS_TYPE_LIQUIDITY_POOL = 4
SC_ADDRESS_TYPE_MUXED_CONTRACT = 5


@dataclass(frozen=True)
class MuxedEd25519Account:
    id: int  # uint64
    ed25519: bytes  # 32 bytes


@dataclass(frozen=True)
class MuxedContract:
    id: int  # uint64
    contract_id: bytes  # 32 bytes


@dataclass(frozen=True)
class ClaimableBalanceID:
    id_type: int  # ClaimableBalanceIDType
    v0: bytes  # 32 bytes


@dataclass(frozen=True)
class SCAddress:
    address_type: int
    account_id: PublicKey | None = None  # for SC_ADDRESS_TYPE_ACCOUNT
    contract_id: bytes | None = None  # 32 bytes for SC_ADDRESS_TYPE_CONTRACT
    muxed_account: MuxedEd25519Account | None = None  # for SC_ADDRESS_TYPE_MUXED_ACCOUNT
    claimable_balance_id: ClaimableBalanceID | None = None  # for SC_ADDRESS_TYPE_CLAIMABLE_BALANCE
    liquidity_pool_id: bytes | None = None  # 32 bytes for SC_ADDRESS_TYPE_LIQUIDITY_POOL
    muxed_contract: MuxedContract | None = None  # for SC_ADDRESS_TYPE_MUXED_CONTRACT


@dataclass(frozen=True)
class ContractExecutableExternalRef:
    executable_owner: SCAddress
    tag: str


@dataclass(frozen=True)
class ContractExecutable:
    executable_type: int
    wasm_hash: bytes | None = None  # for CONTRACT_EXECUTABLE_WASM (32 bytes)
    external_ref: ContractExecutableExternalRef | None = None  # for CONTRACT_EXECUTABLE_EXTERNAL_REF


# ------------------------------------------- TransactionEnvelope data models

# EnvelopeType
ENVELOPE_TYPE_TX_V0 = 0
ENVELOPE_TYPE_TX = 2
ENVELOPE_TYPE_TX_FEE_BUMP = 5

# CryptoKeyType
KEY_TYPE_ED25519 = 0
KEY_TYPE_MUXED_ED25519 = 0x100

# MemoType
MEMO_NONE = 0
MEMO_TEXT = 1
MEMO_ID = 2
MEMO_HASH = 3
MEMO_RETURN = 4

# PreconditionType
PRECOND_NONE = 0
PRECOND_TIME = 1
PRECOND_V2 = 2

# OperationType
OPERATION_TYPE_PAYMENT = 1
OPERATION_TYPE_INVOKE_HOST_FUNCTION = 24

# AssetType
ASSET_TYPE_NATIVE = 0
ASSET_TYPE_CREDIT_ALPHANUM4 = 1
ASSET_TYPE_CREDIT_ALPHANUM12 = 2

# HostFunctionType
HOST_FUNCTION_TYPE_INVOKE_CONTRACT = 0
HOST_FUNCTION_TYPE_CREATE_CONTRACT = 1
HOST_FUNCTION_TYPE_UPLOAD_CONTRACT_WASM = 2
HOST_FUNCTION_TYPE_CREATE_CONTRACT_V2 = 3

# ClaimableBalanceIDType
CLAIMABLE_BALANCE_ID_TYPE_V0 = 0

# Vector bounds
MAX_OPS_PER_TX = 100
MAX_SIGNATURES = 20
MAX_MEMO_TEXT = 28
SCSYMBOL_LIMIT = 32


@dataclass(frozen=True)
class MuxedAccount:
    key_type: int  # CryptoKeyType
    ed25519: bytes | None = None  # 32 bytes for KEY_TYPE_ED25519
    muxed: MuxedEd25519Account | None = None  # for KEY_TYPE_MUXED_ED25519


@dataclass(frozen=True)
class Memo:
    memo_type: int  # MemoType
    text: str | None = None  # for MEMO_TEXT
    id: int | None = None  # for MEMO_ID
    hash: bytes | None = None  # 32 bytes for MEMO_HASH / MEMO_RETURN


@dataclass(frozen=True)
class TimeBounds:
    min_time: int  # TimePoint (uint64)
    max_time: int  # TimePoint (uint64)


@dataclass(frozen=True)
class Preconditions:
    precond_type: int  # PreconditionType
    time_bounds: TimeBounds | None = None  # for PRECOND_TIME


@dataclass(frozen=True)
class AlphaNum4:
    asset_code: bytes  # 4 bytes
    issuer: PublicKey


@dataclass(frozen=True)
class AlphaNum12:
    asset_code: bytes  # 12 bytes
    issuer: PublicKey


@dataclass(frozen=True)
class Asset:
    asset_type: int  # AssetType
    alpha_num4: AlphaNum4 | None = None  # for ASSET_TYPE_CREDIT_ALPHANUM4
    alpha_num12: AlphaNum12 | None = None  # for ASSET_TYPE_CREDIT_ALPHANUM12


@dataclass(frozen=True)
class DecoratedSignature:
    hint: bytes  # 4 bytes
    signature: bytes  # max 64 bytes


@dataclass(frozen=True)
class PaymentOp:
    destination: MuxedAccount
    asset: Asset
    amount: int  # int64


@dataclass(frozen=True)
class InvokeContractArgs:
    contract_address: SCAddress
    function_name: str  # SCSymbol
    args: list  # SCVal vector; empty only


@dataclass(frozen=True)
class HostFunction:
    host_function_type: int  # HostFunctionType
    invoke_contract: InvokeContractArgs | None = None  # for HOST_FUNCTION_TYPE_INVOKE_CONTRACT
    wasm: bytes | None = None  # for HOST_FUNCTION_TYPE_UPLOAD_CONTRACT_WASM


@dataclass(frozen=True)
class InvokeHostFunctionOp:
    host_function: HostFunction
    auth: list  # SorobanAuthorizationEntry vector; empty only


@dataclass(frozen=True)
class OperationBody:
    op_type: int  # OperationType
    payment: PaymentOp | None = None  # for OPERATION_TYPE_PAYMENT
    invoke_host_function: InvokeHostFunctionOp | None = None  # for OPERATION_TYPE_INVOKE_HOST_FUNCTION


@dataclass(frozen=True)
class Operation:
    source_account: MuxedAccount | None
    body: OperationBody


@dataclass(frozen=True)
class SorobanResourcesExtV0:
    archived_soroban_entries: list  # uint32 vector


@dataclass(frozen=True)
class SorobanTransactionDataExt:
    ext_type: int
    resource_ext: SorobanResourcesExtV0 | None = None  # for ext type 1


@dataclass(frozen=True)
class LedgerFootprint:
    read_only: list  # LedgerKey vector; empty only
    read_write: list  # LedgerKey vector; empty only


@dataclass(frozen=True)
class SorobanResources:
    footprint: LedgerFootprint
    instructions: int  # uint32
    disk_read_bytes: int  # uint32
    write_bytes: int  # uint32


@dataclass(frozen=True)
class SorobanTransactionData:
    ext: SorobanTransactionDataExt
    resources: SorobanResources
    resource_fee: int  # int64


@dataclass(frozen=True)
class TransactionExt:
    ext_type: int
    soroban_data: SorobanTransactionData | None = None  # for ext type 1


@dataclass(frozen=True)
class TransactionV0:
    source_account_ed25519: bytes  # 32 bytes
    fee: int  # uint32
    seq_num: int  # SequenceNumber (int64)
    time_bounds: TimeBounds | None
    memo: Memo
    operations: list  # Operation vector
    ext_type: int  # 0 only


@dataclass(frozen=True)
class Transaction:
    source_account: MuxedAccount
    fee: int  # uint32
    seq_num: int  # SequenceNumber (int64)
    cond: Preconditions
    memo: Memo
    operations: list  # Operation vector
    ext: TransactionExt


@dataclass(frozen=True)
class TransactionV0Envelope:
    tx: TransactionV0
    signatures: list  # DecoratedSignature vector


@dataclass(frozen=True)
class TransactionV1Envelope:
    tx: Transaction
    signatures: list  # DecoratedSignature vector


@dataclass(frozen=True)
class FeeBumpTransaction:
    fee_source: MuxedAccount
    fee: int  # int64
    inner_tx: TransactionV1Envelope
    ext_type: int  # 0 only


@dataclass(frozen=True)
class FeeBumpTransactionEnvelope:
    tx: FeeBumpTransaction
    signatures: list  # DecoratedSignature vector


@dataclass(frozen=True)
class TransactionEnvelope:
    envelope_type: int  # EnvelopeType
    v0: TransactionV0Envelope | None = None  # for ENVELOPE_TYPE_TX_V0
    v1: TransactionV1Envelope | None = None  # for ENVELOPE_TYPE_TX
    fee_bump: FeeBumpTransactionEnvelope | None = None  # for ENVELOPE_TYPE_TX_FEE_BUMP


# ---------------------------------------------------------------- Wire Buffer

class XdrReader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    def remaining(self) -> int:
        return len(self.data) - self.pos

    def _require(self, n: int, field_name: str = "data") -> None:
        if self.pos + n > len(self.data):
            needed = self.pos + n
            have = len(self.data)
            raise XdrCodecError(
                f"truncated input reading {field_name}: need {needed} bytes, have {have}"
            )

    def read_int32(self) -> int:
        self._require(4, "int32")
        val = struct.unpack(">i", self.data[self.pos:self.pos + 4])[0]
        self.pos += 4
        return val

    def read_int64(self) -> int:
        self._require(8, "int64")
        val = struct.unpack(">q", self.data[self.pos:self.pos + 8])[0]
        self.pos += 8
        return val

    def read_uint32(self) -> int:
        self._require(4, "uint32")
        val = struct.unpack(">I", self.data[self.pos:self.pos + 4])[0]
        self.pos += 4
        return val

    def read_uint64(self) -> int:
        self._require(8, "uint64")
        val = struct.unpack(">Q", self.data[self.pos:self.pos + 8])[0]
        self.pos += 8
        return val

    def read_fixed_opaque(self, n: int) -> bytes:
        self._require(n, f"fixed opaque ({n} bytes)")
        raw = self.data[self.pos:self.pos + n]
        self.pos += n
        padding = (4 - (n % 4)) % 4
        if padding > 0:
            self._require(padding, "padding")
            pad_bytes = self.data[self.pos:self.pos + padding]
            if pad_bytes != b"\x00" * padding:
                raise XdrCodecError(
                    f"non-zero padding in fixed opaque: expected zeros, got {pad_bytes!r}"
                )
            self.pos += padding
        return raw

    def read_var_opaque(self, max_length: int | None = None) -> bytes:
        length = self.read_uint32()
        if max_length is not None and length > max_length:
            raise XdrCodecError(
                f"length prefix {length} exceeds maximum allowed {max_length}"
            )
        self._require(length, f"var opaque payload ({length} bytes)")
        raw = self.data[self.pos:self.pos + length]
        self.pos += length
        padding = (4 - (length % 4)) % 4
        if padding > 0:
            self._require(padding, "var opaque padding")
            pad_bytes = self.data[self.pos:self.pos + padding]
            if pad_bytes != b"\x00" * padding:
                raise XdrCodecError(
                    f"non-zero padding in variable-length opaque: got {pad_bytes!r}"
                )
            self.pos += padding
        return raw

    def read_string(self, max_length: int | None = None) -> str:
        raw_bytes = self.read_var_opaque(max_length)
        try:
            return raw_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise XdrCodecError(f"invalid UTF-8 in string: {exc}") from None

    def assert_eof(self) -> None:
        if self.pos < len(self.data):
            trailing = len(self.data) - self.pos
            raise XdrCodecError(
                f"trailing bytes after XDR structure: {trailing} unconsumed byte(s)"
            )


class XdrWriter:
    def __init__(self) -> None:
        self.buf = bytearray()

    def write_int32(self, val: int) -> None:
        self.buf.extend(struct.pack(">i", val))

    def write_int64(self, val: int) -> None:
        self.buf.extend(struct.pack(">q", val))

    def write_uint32(self, val: int) -> None:
        self.buf.extend(struct.pack(">I", val))

    def write_uint64(self, val: int) -> None:
        self.buf.extend(struct.pack(">Q", val))

    def write_fixed_opaque(self, data: bytes) -> None:
        self.buf.extend(data)
        padding = (4 - (len(data) % 4)) % 4
        if padding > 0:
            self.buf.extend(b"\x00" * padding)

    def write_var_opaque(self, data: bytes, max_length: int | None = None) -> None:
        if max_length is not None and len(data) > max_length:
            raise XdrCodecError(
                f"length {len(data)} exceeds maximum allowed {max_length}"
            )
        self.write_uint32(len(data))
        self.write_fixed_opaque(data)

    def write_string(self, text: str, max_length: int | None = None) -> None:
        raw = text.encode("utf-8")
        self.write_var_opaque(raw, max_length)

    def to_bytes(self) -> bytes:
        return bytes(self.buf)


# ------------------------------------------------------------ Helpers

def _decode_public_key(reader: XdrReader) -> PublicKey:
    pk_type = reader.read_int32()
    if pk_type != PUBLIC_KEY_TYPE_ED25519:
        raise XdrCodecError(f"unknown PublicKeyType discriminant: {pk_type}")
    ed25519 = reader.read_fixed_opaque(32)
    return PublicKey(key_type=pk_type, ed25519=ed25519)


def _encode_public_key(writer: XdrWriter, pk: PublicKey) -> None:
    if pk.key_type != PUBLIC_KEY_TYPE_ED25519:
        raise XdrCodecError(f"unknown PublicKeyType discriminant: {pk.key_type}")
    writer.write_int32(pk.key_type)
    if len(pk.ed25519) != 32:
        raise XdrCodecError(f"ed25519 key must be 32 bytes, got {len(pk.ed25519)}")
    writer.write_fixed_opaque(pk.ed25519)


def _decode_lc_value_signature(reader: XdrReader) -> LedgerCloseValueSignature:
    node_id = _decode_public_key(reader)
    sig = reader.read_var_opaque(max_length=64)
    return LedgerCloseValueSignature(node_id=node_id, signature=sig)


def _encode_lc_value_signature(writer: XdrWriter, lcs: LedgerCloseValueSignature) -> None:
    _encode_public_key(writer, lcs.node_id)
    writer.write_var_opaque(lcs.signature, max_length=64)


def _decode_sc_address(reader: XdrReader) -> SCAddress:
    addr_type = reader.read_int32()
    if addr_type == SC_ADDRESS_TYPE_ACCOUNT:
        account_id = _decode_public_key(reader)
        return SCAddress(address_type=addr_type, account_id=account_id)
    elif addr_type == SC_ADDRESS_TYPE_CONTRACT:
        contract_id = reader.read_fixed_opaque(32)
        return SCAddress(address_type=addr_type, contract_id=contract_id)
    elif addr_type == SC_ADDRESS_TYPE_MUXED_ACCOUNT:
        muxed_id = reader.read_uint64()
        ed25519 = reader.read_fixed_opaque(32)
        return SCAddress(
            address_type=addr_type,
            muxed_account=MuxedEd25519Account(id=muxed_id, ed25519=ed25519),
        )
    elif addr_type == SC_ADDRESS_TYPE_CLAIMABLE_BALANCE:
        id_type = reader.read_int32()
        if id_type != CLAIMABLE_BALANCE_ID_TYPE_V0:
            raise XdrCodecError(f"unknown ClaimableBalanceIDType discriminant: {id_type}")
        v0 = reader.read_fixed_opaque(32)
        return SCAddress(
            address_type=addr_type,
            claimable_balance_id=ClaimableBalanceID(id_type=id_type, v0=v0),
        )
    elif addr_type == SC_ADDRESS_TYPE_LIQUIDITY_POOL:
        pool_id = reader.read_fixed_opaque(32)
        return SCAddress(address_type=addr_type, liquidity_pool_id=pool_id)
    elif addr_type == SC_ADDRESS_TYPE_MUXED_CONTRACT:
        muxed_id = reader.read_uint64()
        contract_id = reader.read_fixed_opaque(32)
        return SCAddress(
            address_type=addr_type,
            muxed_contract=MuxedContract(id=muxed_id, contract_id=contract_id),
        )
    else:
        raise XdrCodecError(f"unknown SCAddressType discriminant: {addr_type}")


def _encode_sc_address(writer: XdrWriter, addr: SCAddress) -> None:
    writer.write_int32(addr.address_type)
    if addr.address_type == SC_ADDRESS_TYPE_ACCOUNT:
        if addr.account_id is None:
            raise XdrCodecError("account_id required for SC_ADDRESS_TYPE_ACCOUNT")
        _encode_public_key(writer, addr.account_id)
    elif addr.address_type == SC_ADDRESS_TYPE_CONTRACT:
        if addr.contract_id is None or len(addr.contract_id) != 32:
            raise XdrCodecError("contract_id (32 bytes) required for SC_ADDRESS_TYPE_CONTRACT")
        writer.write_fixed_opaque(addr.contract_id)
    elif addr.address_type == SC_ADDRESS_TYPE_MUXED_ACCOUNT:
        muxed = addr.muxed_account
        if muxed is None:
            raise XdrCodecError("muxed_account required for SC_ADDRESS_TYPE_MUXED_ACCOUNT")
        writer.write_uint64(muxed.id)
        if len(muxed.ed25519) != 32:
            raise XdrCodecError("muxed_account ed25519 key must be 32 bytes")
        writer.write_fixed_opaque(muxed.ed25519)
    elif addr.address_type == SC_ADDRESS_TYPE_CLAIMABLE_BALANCE:
        balance_id = addr.claimable_balance_id
        if balance_id is None:
            raise XdrCodecError(
                "claimable_balance_id required for SC_ADDRESS_TYPE_CLAIMABLE_BALANCE"
            )
        writer.write_int32(balance_id.id_type)
        if len(balance_id.v0) != 32:
            raise XdrCodecError("claimable_balance_id v0 hash must be 32 bytes")
        writer.write_fixed_opaque(balance_id.v0)
    elif addr.address_type == SC_ADDRESS_TYPE_LIQUIDITY_POOL:
        if addr.liquidity_pool_id is None or len(addr.liquidity_pool_id) != 32:
            raise XdrCodecError(
                "liquidity_pool_id (32 bytes) required for SC_ADDRESS_TYPE_LIQUIDITY_POOL"
            )
        writer.write_fixed_opaque(addr.liquidity_pool_id)
    elif addr.address_type == SC_ADDRESS_TYPE_MUXED_CONTRACT:
        muxed = addr.muxed_contract
        if muxed is None:
            raise XdrCodecError("muxed_contract required for SC_ADDRESS_TYPE_MUXED_CONTRACT")
        writer.write_uint64(muxed.id)
        if len(muxed.contract_id) != 32:
            raise XdrCodecError("muxed_contract contract id must be 32 bytes")
        writer.write_fixed_opaque(muxed.contract_id)
    else:
        raise XdrCodecError(f"unknown SCAddressType discriminant: {addr.address_type}")


# ------------------------------------------- TransactionEnvelope helpers

def _read_optional_flag(reader: XdrReader, field_name: str) -> bool:
    flag = reader.read_int32()
    if flag not in (0, 1):
        raise XdrCodecError(f"invalid optional presence flag for {field_name}: {flag}")
    return flag == 1


def _write_optional_flag(writer: XdrWriter, present: bool) -> None:
    writer.write_int32(1 if present else 0)


def _read_vector_length(reader: XdrReader, max_length: int, field_name: str) -> int:
    count = reader.read_uint32()
    if count > max_length:
        raise XdrCodecError(
            f"{field_name} length prefix {count} exceeds maximum {max_length}"
        )
    return count


def _decode_muxed_account(reader: XdrReader) -> MuxedAccount:
    key_type = reader.read_int32()
    if key_type == KEY_TYPE_ED25519:
        return MuxedAccount(key_type=key_type, ed25519=reader.read_fixed_opaque(32))
    elif key_type == KEY_TYPE_MUXED_ED25519:
        muxed_id = reader.read_uint64()
        ed25519 = reader.read_fixed_opaque(32)
        return MuxedAccount(
            key_type=key_type,
            muxed=MuxedEd25519Account(id=muxed_id, ed25519=ed25519),
        )
    else:
        raise XdrCodecError(f"unknown CryptoKeyType discriminant: {key_type}")


def _encode_muxed_account(writer: XdrWriter, account: MuxedAccount) -> None:
    writer.write_int32(account.key_type)
    if account.key_type == KEY_TYPE_ED25519:
        if account.ed25519 is None or len(account.ed25519) != 32:
            raise XdrCodecError("ed25519 key (32 bytes) required for KEY_TYPE_ED25519")
        writer.write_fixed_opaque(account.ed25519)
    elif account.key_type == KEY_TYPE_MUXED_ED25519:
        muxed = account.muxed
        if muxed is None:
            raise XdrCodecError("muxed account required for KEY_TYPE_MUXED_ED25519")
        writer.write_uint64(muxed.id)
        if len(muxed.ed25519) != 32:
            raise XdrCodecError("muxed account ed25519 key must be 32 bytes")
        writer.write_fixed_opaque(muxed.ed25519)
    else:
        raise XdrCodecError(f"unknown CryptoKeyType discriminant: {account.key_type}")


def _decode_memo(reader: XdrReader) -> Memo:
    memo_type = reader.read_int32()
    if memo_type == MEMO_NONE:
        return Memo(memo_type=memo_type)
    elif memo_type == MEMO_TEXT:
        return Memo(memo_type=memo_type, text=reader.read_string(max_length=MAX_MEMO_TEXT))
    elif memo_type == MEMO_ID:
        return Memo(memo_type=memo_type, id=reader.read_uint64())
    elif memo_type == MEMO_HASH:
        return Memo(memo_type=memo_type, hash=reader.read_fixed_opaque(32))
    elif memo_type == MEMO_RETURN:
        return Memo(memo_type=memo_type, hash=reader.read_fixed_opaque(32))
    else:
        raise XdrCodecError(f"unknown MemoType discriminant: {memo_type}")


def _encode_memo(writer: XdrWriter, memo: Memo) -> None:
    writer.write_int32(memo.memo_type)
    if memo.memo_type == MEMO_NONE:
        pass
    elif memo.memo_type == MEMO_TEXT:
        if memo.text is None:
            raise XdrCodecError("text required for MEMO_TEXT")
        writer.write_string(memo.text, max_length=MAX_MEMO_TEXT)
    elif memo.memo_type == MEMO_ID:
        if memo.id is None:
            raise XdrCodecError("id required for MEMO_ID")
        writer.write_uint64(memo.id)
    elif memo.memo_type in (MEMO_HASH, MEMO_RETURN):
        if memo.hash is None or len(memo.hash) != 32:
            raise XdrCodecError("hash (32 bytes) required for MEMO_HASH / MEMO_RETURN")
        writer.write_fixed_opaque(memo.hash)
    else:
        raise XdrCodecError(f"unknown MemoType discriminant: {memo.memo_type}")


def _decode_time_bounds(reader: XdrReader) -> TimeBounds:
    return TimeBounds(min_time=reader.read_uint64(), max_time=reader.read_uint64())


def _encode_time_bounds(writer: XdrWriter, bounds: TimeBounds) -> None:
    writer.write_uint64(bounds.min_time)
    writer.write_uint64(bounds.max_time)


def _decode_preconditions(reader: XdrReader) -> Preconditions:
    precond_type = reader.read_int32()
    if precond_type == PRECOND_NONE:
        return Preconditions(precond_type=precond_type)
    elif precond_type == PRECOND_TIME:
        return Preconditions(precond_type=precond_type, time_bounds=_decode_time_bounds(reader))
    elif precond_type == PRECOND_V2:
        raise XdrCodecError(
            "unsupported Preconditions arm: PRECOND_V2 is not implemented by the "
            "independent codec"
        )
    else:
        raise XdrCodecError(f"unknown PreconditionType discriminant: {precond_type}")


def _encode_preconditions(writer: XdrWriter, cond: Preconditions) -> None:
    writer.write_int32(cond.precond_type)
    if cond.precond_type == PRECOND_NONE:
        pass
    elif cond.precond_type == PRECOND_TIME:
        if cond.time_bounds is None:
            raise XdrCodecError("time_bounds required for PRECOND_TIME")
        _encode_time_bounds(writer, cond.time_bounds)
    elif cond.precond_type == PRECOND_V2:
        raise XdrCodecError(
            "unsupported Preconditions arm: PRECOND_V2 is not implemented by the "
            "independent codec"
        )
    else:
        raise XdrCodecError(f"unknown PreconditionType discriminant: {cond.precond_type}")


def _decode_asset(reader: XdrReader) -> Asset:
    asset_type = reader.read_int32()
    if asset_type == ASSET_TYPE_NATIVE:
        return Asset(asset_type=asset_type)
    elif asset_type == ASSET_TYPE_CREDIT_ALPHANUM4:
        asset_code = reader.read_fixed_opaque(4)
        issuer = _decode_public_key(reader)
        return Asset(asset_type=asset_type, alpha_num4=AlphaNum4(asset_code=asset_code, issuer=issuer))
    elif asset_type == ASSET_TYPE_CREDIT_ALPHANUM12:
        asset_code = reader.read_fixed_opaque(12)
        issuer = _decode_public_key(reader)
        return Asset(
            asset_type=asset_type, alpha_num12=AlphaNum12(asset_code=asset_code, issuer=issuer)
        )
    else:
        raise XdrCodecError(f"unknown AssetType discriminant: {asset_type}")


def _encode_asset(writer: XdrWriter, asset: Asset) -> None:
    writer.write_int32(asset.asset_type)
    if asset.asset_type == ASSET_TYPE_NATIVE:
        pass
    elif asset.asset_type == ASSET_TYPE_CREDIT_ALPHANUM4:
        alpha = asset.alpha_num4
        if alpha is None:
            raise XdrCodecError("alpha_num4 required for ASSET_TYPE_CREDIT_ALPHANUM4")
        if len(alpha.asset_code) != 4:
            raise XdrCodecError("asset code must be 4 bytes")
        writer.write_fixed_opaque(alpha.asset_code)
        _encode_public_key(writer, alpha.issuer)
    elif asset.asset_type == ASSET_TYPE_CREDIT_ALPHANUM12:
        alpha = asset.alpha_num12
        if alpha is None:
            raise XdrCodecError("alpha_num12 required for ASSET_TYPE_CREDIT_ALPHANUM12")
        if len(alpha.asset_code) != 12:
            raise XdrCodecError("asset code must be 12 bytes")
        writer.write_fixed_opaque(alpha.asset_code)
        _encode_public_key(writer, alpha.issuer)
    else:
        raise XdrCodecError(f"unknown AssetType discriminant: {asset.asset_type}")


def _decode_decorated_signature(reader: XdrReader) -> DecoratedSignature:
    hint = reader.read_fixed_opaque(4)
    signature = reader.read_var_opaque(max_length=64)
    return DecoratedSignature(hint=hint, signature=signature)


def _encode_decorated_signature(writer: XdrWriter, sig: DecoratedSignature) -> None:
    if len(sig.hint) != 4:
        raise XdrCodecError("signature hint must be 4 bytes")
    writer.write_fixed_opaque(sig.hint)
    writer.write_var_opaque(sig.signature, max_length=64)


def _decode_host_function(reader: XdrReader) -> HostFunction:
    host_type = reader.read_int32()
    if host_type == HOST_FUNCTION_TYPE_INVOKE_CONTRACT:
        contract_address = _decode_sc_address(reader)
        function_name = reader.read_string(max_length=SCSYMBOL_LIMIT)
        arg_count = reader.read_uint32()
        if arg_count != 0:
            raise XdrCodecError(
                "unsupported non-empty SCVal argument vector: the independent codec "
                f"decodes {arg_count} contract call argument(s) but implements none"
            )
        return HostFunction(
            host_function_type=host_type,
            invoke_contract=InvokeContractArgs(
                contract_address=contract_address, function_name=function_name, args=[]
            ),
        )
    elif host_type == HOST_FUNCTION_TYPE_UPLOAD_CONTRACT_WASM:
        return HostFunction(host_function_type=host_type, wasm=reader.read_var_opaque())
    elif host_type in (HOST_FUNCTION_TYPE_CREATE_CONTRACT, HOST_FUNCTION_TYPE_CREATE_CONTRACT_V2):
        raise XdrCodecError(
            f"unsupported HostFunctionType arm: {host_type} is not implemented by the "
            "independent codec"
        )
    else:
        raise XdrCodecError(f"unknown HostFunctionType discriminant: {host_type}")


def _encode_host_function(writer: XdrWriter, host_function: HostFunction) -> None:
    writer.write_int32(host_function.host_function_type)
    if host_function.host_function_type == HOST_FUNCTION_TYPE_INVOKE_CONTRACT:
        args = host_function.invoke_contract
        if args is None:
            raise XdrCodecError("invoke_contract required for HOST_FUNCTION_TYPE_INVOKE_CONTRACT")
        _encode_sc_address(writer, args.contract_address)
        writer.write_string(args.function_name, max_length=SCSYMBOL_LIMIT)
        if args.args:
            raise XdrCodecError(
                "unsupported non-empty SCVal argument vector: the independent codec "
                "encodes contract call arguments but implements none"
            )
        writer.write_uint32(0)
    elif host_function.host_function_type == HOST_FUNCTION_TYPE_UPLOAD_CONTRACT_WASM:
        if host_function.wasm is None:
            raise XdrCodecError("wasm required for HOST_FUNCTION_TYPE_UPLOAD_CONTRACT_WASM")
        writer.write_var_opaque(host_function.wasm)
    elif host_function.host_function_type in (
        HOST_FUNCTION_TYPE_CREATE_CONTRACT,
        HOST_FUNCTION_TYPE_CREATE_CONTRACT_V2,
    ):
        raise XdrCodecError(
            f"unsupported HostFunctionType arm: {host_function.host_function_type} is not "
            "implemented by the independent codec"
        )
    else:
        raise XdrCodecError(
            f"unknown HostFunctionType discriminant: {host_function.host_function_type}"
        )


def _decode_operation(reader: XdrReader) -> Operation:
    source_account = (
        _decode_muxed_account(reader)
        if _read_optional_flag(reader, "Operation.sourceAccount")
        else None
    )
    op_type = reader.read_int32()
    if op_type == OPERATION_TYPE_PAYMENT:
        body = OperationBody(
            op_type=op_type,
            payment=PaymentOp(
                destination=_decode_muxed_account(reader),
                asset=_decode_asset(reader),
                amount=reader.read_int64(),
            ),
        )
    elif op_type == OPERATION_TYPE_INVOKE_HOST_FUNCTION:
        host_function = _decode_host_function(reader)
        auth_count = reader.read_uint32()
        if auth_count != 0:
            raise XdrCodecError(
                "unsupported non-empty Soroban authorization entry vector: the "
                f"independent codec sees {auth_count} entry/entries but implements none"
            )
        body = OperationBody(
            op_type=op_type,
            invoke_host_function=InvokeHostFunctionOp(host_function=host_function, auth=[]),
        )
    else:
        raise XdrCodecError(
            f"unsupported OperationType arm: {op_type} is not implemented by the "
            "independent codec"
        )
    return Operation(source_account=source_account, body=body)


def _encode_operation(writer: XdrWriter, op: Operation) -> None:
    _write_optional_flag(writer, op.source_account is not None)
    if op.source_account is not None:
        _encode_muxed_account(writer, op.source_account)
    writer.write_int32(op.body.op_type)
    if op.body.op_type == OPERATION_TYPE_PAYMENT:
        payment = op.body.payment
        if payment is None:
            raise XdrCodecError("payment required for OPERATION_TYPE_PAYMENT")
        _encode_muxed_account(writer, payment.destination)
        _encode_asset(writer, payment.asset)
        writer.write_int64(payment.amount)
    elif op.body.op_type == OPERATION_TYPE_INVOKE_HOST_FUNCTION:
        invoke = op.body.invoke_host_function
        if invoke is None:
            raise XdrCodecError("invoke_host_function required for OPERATION_TYPE_INVOKE_HOST_FUNCTION")
        _encode_host_function(writer, invoke.host_function)
        if invoke.auth:
            raise XdrCodecError(
                "unsupported non-empty Soroban authorization entry vector: the "
                "independent codec encodes authorization entries but implements none"
            )
        writer.write_uint32(0)
    else:
        raise XdrCodecError(
            f"unsupported OperationType arm: {op.body.op_type} is not implemented by the "
            "independent codec"
        )


def _decode_operations(reader: XdrReader) -> list:
    count = _read_vector_length(reader, MAX_OPS_PER_TX, "operations")
    return [_decode_operation(reader) for _ in range(count)]


def _encode_operations(writer: XdrWriter, operations: list) -> None:
    if len(operations) > MAX_OPS_PER_TX:
        raise XdrCodecError(
            f"operations count {len(operations)} exceeds maximum {MAX_OPS_PER_TX}"
        )
    writer.write_uint32(len(operations))
    for op in operations:
        _encode_operation(writer, op)


def _decode_signatures(reader: XdrReader) -> list:
    count = _read_vector_length(reader, MAX_SIGNATURES, "signatures")
    return [_decode_decorated_signature(reader) for _ in range(count)]


def _encode_signatures(writer: XdrWriter, signatures: list) -> None:
    if len(signatures) > MAX_SIGNATURES:
        raise XdrCodecError(
            f"signatures count {len(signatures)} exceeds maximum {MAX_SIGNATURES}"
        )
    writer.write_uint32(len(signatures))
    for sig in signatures:
        _encode_decorated_signature(writer, sig)


def _decode_soroban_transaction_data(reader: XdrReader) -> SorobanTransactionData:
    ext_type = reader.read_int32()
    if ext_type == 0:
        data_ext = SorobanTransactionDataExt(ext_type=ext_type)
    elif ext_type == 1:
        entry_count = _read_vector_length(
            reader, MAX_OPS_PER_TX, "archivedSorobanEntries"
        )
        entries = [reader.read_uint32() for _ in range(entry_count)]
        data_ext = SorobanTransactionDataExt(
            ext_type=ext_type, resource_ext=SorobanResourcesExtV0(archived_soroban_entries=entries)
        )
    else:
        raise XdrCodecError(
            f"unsupported SorobanTransactionData ext arm: {ext_type} is not implemented "
            "by the independent codec"
        )

    read_only_count = reader.read_uint32()
    if read_only_count != 0:
        raise XdrCodecError(
            "unsupported non-empty LedgerKey read-only footprint: the independent "
            f"codec sees {read_only_count} key(s) but implements none"
        )
    read_write_count = reader.read_uint32()
    if read_write_count != 0:
        raise XdrCodecError(
            "unsupported non-empty LedgerKey read-write footprint: the independent "
            f"codec sees {read_write_count} key(s) but implements none"
        )
    resources = SorobanResources(
        footprint=LedgerFootprint(read_only=[], read_write=[]),
        instructions=reader.read_uint32(),
        disk_read_bytes=reader.read_uint32(),
        write_bytes=reader.read_uint32(),
    )
    return SorobanTransactionData(
        ext=data_ext, resources=resources, resource_fee=reader.read_int64()
    )


def _encode_soroban_transaction_data(writer: XdrWriter, data: SorobanTransactionData) -> None:
    writer.write_int32(data.ext.ext_type)
    if data.ext.ext_type == 0:
        pass
    elif data.ext.ext_type == 1:
        resource_ext = data.ext.resource_ext
        if resource_ext is None:
            raise XdrCodecError("resource_ext required for SorobanTransactionData ext 1")
        entries = resource_ext.archived_soroban_entries
        writer.write_uint32(len(entries))
        for entry in entries:
            writer.write_uint32(entry)
    else:
        raise XdrCodecError(
            f"unsupported SorobanTransactionData ext arm: {data.ext.ext_type} is not "
            "implemented by the independent codec"
        )

    if data.resources.footprint.read_only or data.resources.footprint.read_write:
        raise XdrCodecError(
            "unsupported non-empty LedgerKey footprint: the independent codec encodes "
            "footprint keys but implements none"
        )
    writer.write_uint32(0)
    writer.write_uint32(0)
    writer.write_uint32(data.resources.instructions)
    writer.write_uint32(data.resources.disk_read_bytes)
    writer.write_uint32(data.resources.write_bytes)
    writer.write_int64(data.resource_fee)


def _decode_transaction_v0(reader: XdrReader) -> TransactionV0:
    source_account_ed25519 = reader.read_fixed_opaque(32)
    fee = reader.read_uint32()
    seq_num = reader.read_int64()
    time_bounds = (
        _decode_time_bounds(reader)
        if _read_optional_flag(reader, "TransactionV0.timeBounds")
        else None
    )
    memo = _decode_memo(reader)
    operations = _decode_operations(reader)
    ext_type = reader.read_int32()
    if ext_type != 0:
        raise XdrCodecError(
            f"unsupported TransactionV0 ext arm: {ext_type} is not implemented by the "
            "independent codec"
        )
    return TransactionV0(
        source_account_ed25519=source_account_ed25519,
        fee=fee,
        seq_num=seq_num,
        time_bounds=time_bounds,
        memo=memo,
        operations=operations,
        ext_type=ext_type,
    )


def _encode_transaction_v0(writer: XdrWriter, tx: TransactionV0) -> None:
    if len(tx.source_account_ed25519) != 32:
        raise XdrCodecError("source account ed25519 key must be 32 bytes")
    writer.write_fixed_opaque(tx.source_account_ed25519)
    writer.write_uint32(tx.fee)
    writer.write_int64(tx.seq_num)
    _write_optional_flag(writer, tx.time_bounds is not None)
    if tx.time_bounds is not None:
        _encode_time_bounds(writer, tx.time_bounds)
    _encode_memo(writer, tx.memo)
    _encode_operations(writer, tx.operations)
    if tx.ext_type != 0:
        raise XdrCodecError(
            f"unsupported TransactionV0 ext arm: {tx.ext_type} is not implemented by the "
            "independent codec"
        )
    writer.write_int32(tx.ext_type)


def _decode_transaction(reader: XdrReader) -> Transaction:
    source_account = _decode_muxed_account(reader)
    fee = reader.read_uint32()
    seq_num = reader.read_int64()
    cond = _decode_preconditions(reader)
    memo = _decode_memo(reader)
    operations = _decode_operations(reader)
    ext_type = reader.read_int32()
    if ext_type == 0:
        ext = TransactionExt(ext_type=ext_type)
    elif ext_type == 1:
        ext = TransactionExt(ext_type=ext_type, soroban_data=_decode_soroban_transaction_data(reader))
    else:
        raise XdrCodecError(
            f"unsupported Transaction ext arm: {ext_type} is not implemented by the "
            "independent codec"
        )
    return Transaction(
        source_account=source_account,
        fee=fee,
        seq_num=seq_num,
        cond=cond,
        memo=memo,
        operations=operations,
        ext=ext,
    )


def _encode_transaction(writer: XdrWriter, tx: Transaction) -> None:
    _encode_muxed_account(writer, tx.source_account)
    writer.write_uint32(tx.fee)
    writer.write_int64(tx.seq_num)
    _encode_preconditions(writer, tx.cond)
    _encode_memo(writer, tx.memo)
    _encode_operations(writer, tx.operations)
    writer.write_int32(tx.ext.ext_type)
    if tx.ext.ext_type == 0:
        pass
    elif tx.ext.ext_type == 1:
        if tx.ext.soroban_data is None:
            raise XdrCodecError("soroban_data required for Transaction ext 1")
        _encode_soroban_transaction_data(writer, tx.ext.soroban_data)
    else:
        raise XdrCodecError(
            f"unsupported Transaction ext arm: {tx.ext.ext_type} is not implemented by "
            "the independent codec"
        )


def _decode_transaction_v0_envelope(reader: XdrReader) -> TransactionV0Envelope:
    tx = _decode_transaction_v0(reader)
    signatures = _decode_signatures(reader)
    return TransactionV0Envelope(tx=tx, signatures=signatures)


def _encode_transaction_v0_envelope(writer: XdrWriter, envelope: TransactionV0Envelope) -> None:
    _encode_transaction_v0(writer, envelope.tx)
    _encode_signatures(writer, envelope.signatures)


def _decode_transaction_v1_envelope(reader: XdrReader) -> TransactionV1Envelope:
    tx = _decode_transaction(reader)
    signatures = _decode_signatures(reader)
    return TransactionV1Envelope(tx=tx, signatures=signatures)


def _encode_transaction_v1_envelope(writer: XdrWriter, envelope: TransactionV1Envelope) -> None:
    _encode_transaction(writer, envelope.tx)
    _encode_signatures(writer, envelope.signatures)


def _decode_fee_bump_transaction(reader: XdrReader) -> FeeBumpTransaction:
    fee_source = _decode_muxed_account(reader)
    fee = reader.read_int64()
    inner_type = reader.read_int32()
    if inner_type != ENVELOPE_TYPE_TX:
        raise XdrCodecError(
            f"unsupported FeeBumpTransaction inner transaction arm: {inner_type} is not "
            "implemented by the independent codec"
        )
    inner_tx = _decode_transaction_v1_envelope(reader)
    ext_type = reader.read_int32()
    if ext_type != 0:
        raise XdrCodecError(
            f"unsupported FeeBumpTransaction ext arm: {ext_type} is not implemented by "
            "the independent codec"
        )
    return FeeBumpTransaction(
        fee_source=fee_source, fee=fee, inner_tx=inner_tx, ext_type=ext_type
    )


def _encode_fee_bump_transaction(writer: XdrWriter, tx: FeeBumpTransaction) -> None:
    _encode_muxed_account(writer, tx.fee_source)
    writer.write_int64(tx.fee)
    writer.write_int32(ENVELOPE_TYPE_TX)
    _encode_transaction_v1_envelope(writer, tx.inner_tx)
    if tx.ext_type != 0:
        raise XdrCodecError(
            f"unsupported FeeBumpTransaction ext arm: {tx.ext_type} is not implemented by "
            "the independent codec"
        )
    writer.write_int32(tx.ext_type)


def _decode_fee_bump_transaction_envelope(reader: XdrReader) -> FeeBumpTransactionEnvelope:
    tx = _decode_fee_bump_transaction(reader)
    signatures = _decode_signatures(reader)
    return FeeBumpTransactionEnvelope(tx=tx, signatures=signatures)


def _encode_fee_bump_transaction_envelope(
    writer: XdrWriter, envelope: FeeBumpTransactionEnvelope
) -> None:
    _encode_fee_bump_transaction(writer, envelope.tx)
    _encode_signatures(writer, envelope.signatures)


# ------------------------------------------------- StellarValue Codec

def decode_stellar_value(raw: bytes) -> StellarValue:
    reader = XdrReader(raw)
    tx_set_hash = reader.read_fixed_opaque(32)
    close_time = reader.read_uint64()

    upgrade_count = reader.read_uint32()
    if upgrade_count > 6:
        raise XdrCodecError(f"upgrades count {upgrade_count} exceeds maximum 6")
    upgrades: list[bytes] = []
    for _ in range(upgrade_count):
        upgrades.append(reader.read_var_opaque(max_length=128))

    ext_type = reader.read_int32()
    if ext_type == STELLAR_VALUE_BASIC:
        ext = StellarValueExt(ext_type=ext_type)
    elif ext_type == STELLAR_VALUE_SIGNED:
        sig = _decode_lc_value_signature(reader)
        ext = StellarValueExt(ext_type=ext_type, signature=sig)
    elif ext_type == STELLAR_VALUE_EMPTY_TX_SET:
        proposed_tx_set_hash = reader.read_fixed_opaque(32)
        prev_ledger_hash = reader.read_fixed_opaque(32)
        prev_ledger_ver = reader.read_uint32()
        lc_sig = _decode_lc_value_signature(reader)
        proposed = EmptyTxSetProposedValue(
            tx_set_hash=proposed_tx_set_hash,
            previous_ledger_hash=prev_ledger_hash,
            previous_ledger_version=prev_ledger_ver,
            lc_value_signature=lc_sig,
        )
        ext = StellarValueExt(ext_type=ext_type, proposed_value=proposed)
    else:
        raise XdrCodecError(f"unknown StellarValueType discriminant: {ext_type}")

    reader.assert_eof()
    return StellarValue(
        tx_set_hash=tx_set_hash,
        close_time=close_time,
        upgrades=upgrades,
        ext=ext,
    )


def encode_stellar_value(val: StellarValue) -> bytes:
    writer = XdrWriter()
    if len(val.tx_set_hash) != 32:
        raise XdrCodecError(f"txSetHash must be 32 bytes, got {len(val.tx_set_hash)}")
    writer.write_fixed_opaque(val.tx_set_hash)
    writer.write_uint64(val.close_time)

    if len(val.upgrades) > 6:
        raise XdrCodecError(f"upgrades count {len(val.upgrades)} exceeds maximum 6")
    writer.write_uint32(len(val.upgrades))
    for u in val.upgrades:
        writer.write_var_opaque(u, max_length=128)

    writer.write_int32(val.ext.ext_type)
    if val.ext.ext_type == STELLAR_VALUE_BASIC:
        pass
    elif val.ext.ext_type == STELLAR_VALUE_SIGNED:
        if val.ext.signature is None:
            raise XdrCodecError("signature required for STELLAR_VALUE_SIGNED")
        _encode_lc_value_signature(writer, val.ext.signature)
    elif val.ext.ext_type == STELLAR_VALUE_EMPTY_TX_SET:
        pv = val.ext.proposed_value
        if pv is None:
            raise XdrCodecError("proposed_value required for STELLAR_VALUE_EMPTY_TX_SET")
        if len(pv.tx_set_hash) != 32:
            raise XdrCodecError("proposed txSetHash must be 32 bytes")
        writer.write_fixed_opaque(pv.tx_set_hash)
        if len(pv.previous_ledger_hash) != 32:
            raise XdrCodecError("previousLedgerHash must be 32 bytes")
        writer.write_fixed_opaque(pv.previous_ledger_hash)
        writer.write_uint32(pv.previous_ledger_version)
        _encode_lc_value_signature(writer, pv.lc_value_signature)
    else:
        raise XdrCodecError(f"unknown StellarValueType discriminant: {val.ext.ext_type}")

    return writer.to_bytes()


# --------------------------------------------- ContractExecutable Codec

def decode_contract_executable(raw: bytes) -> ContractExecutable:
    reader = XdrReader(raw)
    exec_type = reader.read_int32()
    if exec_type == CONTRACT_EXECUTABLE_WASM:
        wasm_hash = reader.read_fixed_opaque(32)
        exec_val = ContractExecutable(executable_type=exec_type, wasm_hash=wasm_hash)
    elif exec_type == CONTRACT_EXECUTABLE_STELLAR_ASSET:
        exec_val = ContractExecutable(executable_type=exec_type)
    elif exec_type == CONTRACT_EXECUTABLE_EXTERNAL_REF:
        owner = _decode_sc_address(reader)
        tag = reader.read_string()
        ref = ContractExecutableExternalRef(executable_owner=owner, tag=tag)
        exec_val = ContractExecutable(executable_type=exec_type, external_ref=ref)
    else:
        raise XdrCodecError(f"unknown ContractExecutableType discriminant: {exec_type}")

    reader.assert_eof()
    return exec_val


def encode_contract_executable(val: ContractExecutable) -> bytes:
    writer = XdrWriter()
    writer.write_int32(val.executable_type)
    if val.executable_type == CONTRACT_EXECUTABLE_WASM:
        if val.wasm_hash is None or len(val.wasm_hash) != 32:
            raise XdrCodecError("wasm_hash (32 bytes) required for CONTRACT_EXECUTABLE_WASM")
        writer.write_fixed_opaque(val.wasm_hash)
    elif val.executable_type == CONTRACT_EXECUTABLE_STELLAR_ASSET:
        pass
    elif val.executable_type == CONTRACT_EXECUTABLE_EXTERNAL_REF:
        if val.external_ref is None:
            raise XdrCodecError("external_ref required for CONTRACT_EXECUTABLE_EXTERNAL_REF")
        _encode_sc_address(writer, val.external_ref.executable_owner)
        writer.write_string(val.external_ref.tag)
    else:
        raise XdrCodecError(f"unknown ContractExecutableType discriminant: {val.executable_type}")

    return writer.to_bytes()


# ------------------------------------------- TransactionEnvelope Codec

def decode_transaction_envelope(raw: bytes) -> TransactionEnvelope:
    reader = XdrReader(raw)
    envelope_type = reader.read_int32()
    if envelope_type == ENVELOPE_TYPE_TX_V0:
        envelope = TransactionEnvelope(
            envelope_type=envelope_type, v0=_decode_transaction_v0_envelope(reader)
        )
    elif envelope_type == ENVELOPE_TYPE_TX:
        envelope = TransactionEnvelope(
            envelope_type=envelope_type, v1=_decode_transaction_v1_envelope(reader)
        )
    elif envelope_type == ENVELOPE_TYPE_TX_FEE_BUMP:
        envelope = TransactionEnvelope(
            envelope_type=envelope_type, fee_bump=_decode_fee_bump_transaction_envelope(reader)
        )
    else:
        raise XdrCodecError(f"unknown EnvelopeType discriminant: {envelope_type}")

    reader.assert_eof()
    return envelope


def encode_transaction_envelope(val: TransactionEnvelope) -> bytes:
    writer = XdrWriter()
    writer.write_int32(val.envelope_type)
    if val.envelope_type == ENVELOPE_TYPE_TX_V0:
        if val.v0 is None:
            raise XdrCodecError("v0 envelope required for ENVELOPE_TYPE_TX_V0")
        _encode_transaction_v0_envelope(writer, val.v0)
    elif val.envelope_type == ENVELOPE_TYPE_TX:
        if val.v1 is None:
            raise XdrCodecError("v1 envelope required for ENVELOPE_TYPE_TX")
        _encode_transaction_v1_envelope(writer, val.v1)
    elif val.envelope_type == ENVELOPE_TYPE_TX_FEE_BUMP:
        if val.fee_bump is None:
            raise XdrCodecError("fee_bump envelope required for ENVELOPE_TYPE_TX_FEE_BUMP")
        _encode_fee_bump_transaction_envelope(writer, val.fee_bump)
    else:
        raise XdrCodecError(f"unknown EnvelopeType discriminant: {val.envelope_type}")

    return writer.to_bytes()


# --------------------------------------------------- Generic Interface

def decode_xdr(type_name: str, raw: bytes) -> Any:
    if type_name == "StellarValue":
        return decode_stellar_value(raw)
    elif type_name == "ContractExecutable":
        return decode_contract_executable(raw)
    elif type_name == "TransactionEnvelope":
        return decode_transaction_envelope(raw)
    else:
        raise XdrCodecError(f"unsupported XDR type for independent codec: {type_name}")


def encode_xdr(type_name: str, value: Any) -> bytes:
    if type_name == "StellarValue":
        return encode_stellar_value(value)
    elif type_name == "ContractExecutable":
        return encode_contract_executable(value)
    elif type_name == "TransactionEnvelope":
        return encode_transaction_envelope(value)
    else:
        raise XdrCodecError(f"unsupported XDR type for independent codec: {type_name}")
