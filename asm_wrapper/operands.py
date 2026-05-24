"""MN-Core 2 の命令オペランドを表す型付きラッパ。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final, Literal, Protocol, Sequence, TypeAlias


class Renderable(Protocol):
    """VSM 文字列へ変換できる最小 protocol。"""

    def render(self) -> str:
        ...


class WordWidth(str, Enum):
    """PE 側オペランドの語長指定。`l` は長語、`ll` は 2 長語。"""

    LONG = "l"
    DOUBLE_LONG = "ll"


class MatrixBank(str, Enum):
    """行列レジスタ面。`x` / `y` に対応する。"""

    X = "x"
    Y = "y"


class ForwardingKind(str, Enum):
    MAU = "mauf"
    ALU = "aluf"
    L1BM = "lbf"
    MREAD = "mreadf"


class FixedInputKind(str, Enum):
    L2BID = "l2bid"
    L1BID = "l1bid"
    MABID = "mabid"
    PEID = "peid"
    SUBPEID = "subpeid"
    MSB1 = "msb1"


RRNOpcode: TypeAlias = Literal[
    "dfadd",
    "ffadd",
    "hfadd",
    "dmax",
    "fmax",
    "hmax",
    "dmin",
    "fmin",
    "hmin",
    "liadd",
    "iiadd",
    "siadd",
    "lband",
    "iband",
    "sband",
    "land",
    "iand",
    "sand",
    "lbor",
    "ibor",
    "sbor",
    "lor",
    "ior",
    "sor",
]

ALUIntPrecision: TypeAlias = Literal["l", "i", "s"]
ALUFloatPrecision: TypeAlias = Literal["d", "f", "h"]
ALUBfnPrecision: TypeAlias = Literal["d", "f", "g", "h"]
ALUAnyPrecision: TypeAlias = Literal["d", "f", "h", "l", "i", "s"]

MAUHalfSelect: TypeAlias = Literal["u", "d"]


@dataclass(frozen=True)
class Operand:
    """通常命令で使うオペランドの基底型。"""

    def render(self) -> str:
        raise NotImplementedError


def _format_flat_addrs(addresses: Sequence[int]) -> str:
    """MNCore2.md 3.3 の `[a0,a1,a2,a3]` 形式へ整形する。"""

    if len(addresses) != 4:
        raise ValueError("Flat mode requires exactly 4 cycle addresses")
    return "[" + ",".join(str(addr) for addr in addresses) + "]"


def _append_cycle_mask(suffix: str, cycle_mask: str | None) -> str:
    """チュートリアルに現れる `/1000` のようなサイクル指定を付ける。"""

    if cycle_mask is None:
        return suffix
    if len(cycle_mask) != 4 or any(ch not in "01" for ch in cycle_mask):
        raise ValueError("cycle_mask must be a 4-character bit string such as '1000'")
    return f"{suffix}/{cycle_mask}"


@dataclass(frozen=True)
class PDM(Operand):
    """PDM オペランド。`$p<addr>[@<group>]` を表す。"""

    addr: int
    group: int | None = None

    def render(self) -> str:
        suffix = f"@{self.group}" if self.group is not None else ""
        return f"$p{self.addr}{suffix}"


@dataclass(frozen=True)
class DRAM(Operand):
    """DRAM オペランド。直接アドレスと DAR 間接参照の両方を扱う。"""

    addr: int | None = None
    dar_addr: int | None = None
    group: int | None = None

    def render(self) -> str:
        if (self.addr is None) == (self.dar_addr is None):
            raise ValueError("DRAM requires exactly one of addr or dar_addr")
        prefix = f"di{self.dar_addr}" if self.dar_addr is not None else f"d{self.addr}"
        suffix = f"@{self.group}" if self.group is not None else ""
        return f"${prefix}{suffix}"


@dataclass(frozen=True)
class DAR(Operand):
    """DAR エントリ参照。`$dar<addr>`。"""

    addr: int

    def render(self) -> str:
        return f"$dar{self.addr}"


@dataclass(frozen=True)
class L2BM(Operand):
    """L2BM オペランド。MV 用の group/l2b 修飾も保持する。"""

    addr: int
    group: int | None = None
    l2b: int | None = None

    def render(self) -> str:
        if self.group is None and self.l2b is None:
            return f"$lc{self.addr}"
        if self.group is None:
            return f"$lc{self.addr}@.{self.l2b}"
        if self.l2b is None:
            raise ValueError("L2BM group-qualified operands also require l2b")
        return f"$lc{self.addr}@{self.group}.{self.l2b}"


@dataclass(frozen=True)
class L1BM(Operand):
    """L1BM オペランド。`$lb...` と `$llb...`、`i` 折り返しを表す。"""

    addr: int | None = None
    width: WordWidth = WordWidth.LONG
    indirect: bool = False

    def render(self) -> str:
        if self.indirect:
            return f"${self.width.value}bi"
        if self.addr is None:
            raise ValueError("L1BM direct operands require addr")
        return f"${self.width.value}b{self.addr}"


@dataclass(frozen=True)
class LM0(Operand):
    """LM0 オペランド。

    `auto()` は SDM 3.3 の auto-stride mode、`flat()` は flat mode を表す。
    """

    suffix: str
    width: WordWidth = WordWidth.LONG

    @classmethod
    def auto(
        cls,
        addr: int,
        *,
        width: WordWidth = WordWidth.LONG,
        vector: bool = False,
        adri: int | None = None,
        madpe: int | None = None,
        cycle_mask: str | None = None,
    ) -> LM0:
        suffix = str(addr)
        if vector:
            suffix += "v"
            if adri is not None:
                suffix += str(adri)
        if madpe is not None:
            suffix += f"j{madpe}"
        suffix = _append_cycle_mask(suffix, cycle_mask)
        return cls(suffix=suffix, width=width)

    @classmethod
    def flat(
        cls,
        addresses: Sequence[int],
        *,
        width: WordWidth = WordWidth.LONG,
        madpe: int | None = None,
        cycle_mask: str | None = None,
    ) -> LM0:
        """Flat mode の LM0 を生成する。形式は `[a0,a1,a2,a3]`。"""

        suffix = _format_flat_addrs(addresses)
        if madpe is not None:
            suffix += f"j{madpe}"
        suffix = _append_cycle_mask(suffix, cycle_mask)
        return cls(suffix=suffix, width=width)

    @classmethod
    def t_indirect(
        cls,
        addr: int = 0,
        *,
        width: WordWidth = WordWidth.LONG,
        vector: bool = False,
        adri: int | None = None,
        cycle_mask: str | None = None,
    ) -> LM0:
        suffix = f"t{addr}"
        if vector:
            suffix += "v"
            if adri is not None:
                suffix += str(adri)
        suffix = _append_cycle_mask(suffix, cycle_mask)
        return cls(suffix=suffix, width=width)

    @classmethod
    def t_indirect_flat(
        cls,
        addresses: Sequence[int],
        *,
        width: WordWidth = WordWidth.LONG,
        cycle_mask: str | None = None,
    ) -> LM0:
        """T レジスタ間接参照つき flat mode LM0 を生成する。"""

        suffix = f"t{_format_flat_addrs(addresses)}"
        suffix = _append_cycle_mask(suffix, cycle_mask)
        return cls(suffix=suffix, width=width)

    @classmethod
    def raw(
        cls,
        suffix: str,
        *,
        width: WordWidth = WordWidth.LONG,
        cycle_mask: str | None = None,
    ) -> LM0:
        """仕様未確定の派生記法をそのまま保持したいときに使う。"""

        return cls(suffix=_append_cycle_mask(suffix, cycle_mask), width=width)

    def render(self) -> str:
        return f"${self.width.value}m{self.suffix}"


@dataclass(frozen=True)
class LM1(Operand):
    """LM1 オペランド。`auto()` と `flat()` を持つ。"""

    suffix: str
    width: WordWidth = WordWidth.LONG

    @classmethod
    def auto(
        cls,
        addr: int,
        *,
        width: WordWidth = WordWidth.LONG,
        vector: bool = False,
        adri: int | None = None,
        madpe: int | None = None,
        cycle_mask: str | None = None,
    ) -> LM1:
        suffix = str(addr)
        if vector:
            suffix += "v"
            if adri is not None:
                suffix += str(adri)
        if madpe is not None:
            suffix += f"j{madpe}"
        suffix = _append_cycle_mask(suffix, cycle_mask)
        return cls(suffix=suffix, width=width)

    @classmethod
    def flat(
        cls,
        addresses: Sequence[int],
        *,
        width: WordWidth = WordWidth.LONG,
        madpe: int | None = None,
        cycle_mask: str | None = None,
    ) -> LM1:
        """Flat mode の LM1 を生成する。"""

        suffix = _format_flat_addrs(addresses)
        if madpe is not None:
            suffix += f"j{madpe}"
        suffix = _append_cycle_mask(suffix, cycle_mask)
        return cls(suffix=suffix, width=width)

    @classmethod
    def raw(
        cls,
        suffix: str,
        *,
        width: WordWidth = WordWidth.LONG,
        cycle_mask: str | None = None,
    ) -> LM1:
        return cls(suffix=_append_cycle_mask(suffix, cycle_mask), width=width)

    def render(self) -> str:
        return f"${self.width.value}n{self.suffix}"


@dataclass(frozen=True)
class GRF0(Operand):
    """GRF0 オペランド。flat mode と `/1000` 派生表記を補助する。"""

    suffix: str
    width: WordWidth = WordWidth.LONG

    @classmethod
    def auto(
        cls,
        addr: int,
        *,
        width: WordWidth = WordWidth.LONG,
        vector: bool = False,
        adri: int | None = None,
        cycle_mask: str | None = None,
    ) -> GRF0:
        suffix = str(addr)
        if vector:
            suffix += "v"
            if adri is not None:
                suffix += str(adri)
        suffix = _append_cycle_mask(suffix, cycle_mask)
        return cls(suffix=suffix, width=width)

    @classmethod
    def flat(
        cls,
        addresses: Sequence[int],
        *,
        width: WordWidth = WordWidth.LONG,
        cycle_mask: str | None = None,
    ) -> GRF0:
        """Flat mode の GRF0 を生成する。"""

        return cls(suffix=_append_cycle_mask(_format_flat_addrs(addresses), cycle_mask), width=width)

    @classmethod
    def raw(
        cls,
        suffix: str,
        *,
        width: WordWidth = WordWidth.LONG,
        cycle_mask: str | None = None,
    ) -> GRF0:
        return cls(suffix=_append_cycle_mask(suffix, cycle_mask), width=width)

    def render(self) -> str:
        return f"${self.width.value}r{self.suffix}"


@dataclass(frozen=True)
class GRF1(Operand):
    """GRF1 オペランド。flat mode と `/1000` 派生表記を補助する。"""

    suffix: str
    width: WordWidth = WordWidth.LONG

    @classmethod
    def auto(
        cls,
        addr: int,
        *,
        width: WordWidth = WordWidth.LONG,
        vector: bool = False,
        adri: int | None = None,
        cycle_mask: str | None = None,
    ) -> GRF1:
        suffix = str(addr)
        if vector:
            suffix += "v"
            if adri is not None:
                suffix += str(adri)
        suffix = _append_cycle_mask(suffix, cycle_mask)
        return cls(suffix=suffix, width=width)

    @classmethod
    def flat(
        cls,
        addresses: Sequence[int],
        *,
        width: WordWidth = WordWidth.LONG,
        cycle_mask: str | None = None,
    ) -> GRF1:
        """Flat mode の GRF1 を生成する。"""

        return cls(suffix=_append_cycle_mask(_format_flat_addrs(addresses), cycle_mask), width=width)

    @classmethod
    def raw(
        cls,
        suffix: str,
        *,
        width: WordWidth = WordWidth.LONG,
        cycle_mask: str | None = None,
    ) -> GRF1:
        return cls(suffix=_append_cycle_mask(suffix, cycle_mask), width=width)

    def render(self) -> str:
        return f"${self.width.value}s{self.suffix}"


@dataclass(frozen=True)
class TReg(Operand):
    """T レジスタ。命令上は現在サイクルに対応する 2 長語を表す。"""

    width: WordWidth = WordWidth.LONG

    def render(self) -> str:
        return f"${self.width.value}t"


@dataclass(frozen=True)
class MaskRegister(Operand):
    """マスクレジスタ参照。`$omr<addr>`。"""

    addr: int

    def render(self) -> str:
        return f"$omr{self.addr}"


@dataclass(frozen=True)
class Matrix(Operand):
    """行列レジスタの行または列。`$lx0`, `$lly2` などを表す。"""

    bank: MatrixBank
    addr: int
    width: WordWidth = WordWidth.LONG

    def render(self) -> str:
        return f"${self.width.value}{self.bank.value}{self.addr}"


@dataclass(frozen=True)
class MatrixVector(Operand):
    """MAU の `$lx` / `$ly` ベクトル入力側を表す。"""

    bank: MatrixBank

    def render(self) -> str:
        return f"$l{self.bank.value}"


@dataclass(frozen=True)
class Forwarding(Operand):
    """フォワーディングパス入力。`$mauf`, `$aluf` など。"""

    kind: ForwardingKind

    def render(self) -> str:
        return f"${self.kind.value}"


@dataclass(frozen=True)
class FixedInput(Operand):
    """固定値入力。`$peid`, `$l2bid` など。"""

    kind: FixedInputKind

    def render(self) -> str:
        return f"${self.kind.value}"


@dataclass(frozen=True)
class LM0Base(Operand):
    """LM0 ベースアドレスレジスタ書き込みオペランド。"""

    long_word: bool = True

    def render(self) -> str:
        return "$lmb" if self.long_word else "$mb"


@dataclass(frozen=True)
class LM1Base(Operand):
    """LM1 ベースアドレスレジスタ書き込みオペランド。"""

    long_word: bool = True

    def render(self) -> str:
        return "$lnb" if self.long_word else "$nb"


@dataclass(frozen=True)
class Nowrite(Operand):
    """結果を破棄する `nowrite`。"""

    def render(self) -> str:
        return "$nowrite"


MAUF: Final[Forwarding] = Forwarding(ForwardingKind.MAU)
ALUF: Final[Forwarding] = Forwarding(ForwardingKind.ALU)
LBF: Final[Forwarding] = Forwarding(ForwardingKind.L1BM)
MREADF: Final[Forwarding] = Forwarding(ForwardingKind.MREAD)

L2BID: Final[FixedInput] = FixedInput(FixedInputKind.L2BID)
L1BID: Final[FixedInput] = FixedInput(FixedInputKind.L1BID)
MABID: Final[FixedInput] = FixedInput(FixedInputKind.MABID)
PEID: Final[FixedInput] = FixedInput(FixedInputKind.PEID)
SUBPEID: Final[FixedInput] = FixedInput(FixedInputKind.SUBPEID)
MSB1: Final[FixedInput] = FixedInput(FixedInputKind.MSB1)


PeReadOperand: TypeAlias = LM0 | LM1 | GRF0 | GRF1 | TReg | Forwarding | FixedInput
PeWriteOperand: TypeAlias = LM0 | LM1 | GRF0 | GRF1 | TReg | MaskRegister | LM0Base | LM1Base | Nowrite
MvOperand: TypeAlias = PDM | DRAM | L2BM
MatrixOperand: TypeAlias = Matrix | MatrixVector
