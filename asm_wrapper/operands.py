"""MN-Core 2 の命令オペランドを表す型付きラッパ。

`MNCore2.md` 2.4 / 4 章に合わせて、PDM・DRAM・DAR・L2BM・L1BM・
LM0/LM1・GRF0/GRF1・行列レジスタなどの空間を別 class に分けている。
この層は主にオペランド文字列の整形を担い、アラインメントやハザード、
精度縮減の合法性までは検証しない。
"""

from __future__ import annotations

from dataclasses import dataclass, replace, field
from enum import Enum
import re
from typing import Final, Literal, Protocol, Self, Sequence, TypeAlias


class Renderable(Protocol):
    """VSM 文字列へ変換できる最小 protocol。"""

    def render(self) -> str: ...


class WordWidth(str, Enum):
    """PE 側オペランドの語長指定。`l` は長語、`ll` は 2 長語。

    LM/GRF は単語アドレス空間だが、文法上の幅接頭辞はアクセス語長を表す。
    """

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
WriteMaskGuardSuffix: TypeAlias = Literal["t", "p"]


@dataclass(frozen=True)
class Operand:
    """通常命令で使うオペランドの基底型。"""

    def __add__(self, delta: object) -> Self:
        if not isinstance(delta, int):
            return NotImplemented
        return self._offset_by(delta)

    def __radd__(self, delta: object) -> Self:
        return self.__add__(delta)

    def _offset_by(self, delta: int) -> Self:
        raise TypeError(f"{type(self).__name__} does not support address arithmetic")

    def render(self) -> str:
        raise NotImplementedError


@dataclass(frozen=True)
class PeVirtualMemory(Operand):
    """LM0/LM1/GRF0/GRF1 のいずれかへ後段で割り付ける仮想 PE メモリ。"""

    root_id: int
    size: int
    align: int
    offset: int = 0
    width: WordWidth = WordWidth.LONG
    vector: bool = False

    def __post_init__(self) -> None:
        if self.size <= 0:
            raise ValueError("size must be positive")
        if self.align <= 0:
            raise ValueError("align must be positive")

    def as_width(self, width: WordWidth) -> Self:
        return replace(self, width=width)

    def as_vector(self, vector: bool = True) -> Self:
        return replace(self, vector=vector)

    def _offset_by(self, delta: int) -> Self:
        return replace(self, offset=self.offset + delta)

    def render(self) -> str:
        vector_bit = 1 if self.vector else 0
        return (
            f"__pevr{self.root_id}_s{self.size}_a{self.align}"
            f"_o{self.offset}_w{self.width.value}_v{vector_bit}__"
        )


@dataclass(frozen=True)
class PeVirtualFlatMemory(Operand):
    """複数の仮想 PE メモリを flat モード 1 オペランドとして束ねる。"""

    operands: tuple[PeVirtualMemory, PeVirtualMemory, PeVirtualMemory, PeVirtualMemory]
    width: WordWidth = WordWidth.LONG
    cycle_mask: str | None = None

    def as_width(self, width: WordWidth) -> Self:
        return replace(self, width=width)

    def render(self) -> str:
        encoded_operands = "_".join(
            f"r{operand.root_id}s{operand.size}a{operand.align}o{operand.offset}"
            for operand in self.operands
        )
        mask_suffix = "" if self.cycle_mask is None else f"_m{self.cycle_mask}"
        return f"__pevrf_w{self.width.value}{mask_suffix}_{encoded_operands}__"


_SUFFIX_WITH_MASK_RE = re.compile(r"^(?P<body>.*?)(?:/(?P<mask>[01]{4}))?$")
_SUFFIX_ADDR_RE = re.compile(
    r"^(?P<t_prefix>t?)(?P<base>\[[0-9,]+\]|[0-9]+)(?P<vector>v[0-9]*)?(?P<madpe>j[0-9]+)?$"
)


def _offset_flat_addr_text(flat_addr_text: str, delta: int) -> str:
    inner = flat_addr_text[1:-1]
    return "[" + ",".join(str(int(addr) + delta) for addr in inner.split(",")) + "]"


def _offset_suffix_addresses(suffix: str, delta: int) -> str:
    mask_match = _SUFFIX_WITH_MASK_RE.fullmatch(suffix)
    if mask_match is None:
        raise ValueError(
            f"unsupported operand suffix for address arithmetic: {suffix!r}"
        )

    body = mask_match.group("body")
    cycle_mask = mask_match.group("mask")
    addr_match = _SUFFIX_ADDR_RE.fullmatch(body)
    if addr_match is None:
        raise ValueError(
            f"unsupported operand suffix for address arithmetic: {suffix!r}"
        )

    base = addr_match.group("base")
    if base.startswith("["):
        offset_base = _offset_flat_addr_text(base, delta)
    else:
        offset_base = str(int(base) + delta)

    offset_body = "".join(
        part or ""
        for part in (
            addr_match.group("t_prefix"),
            offset_base,
            addr_match.group("vector"),
            addr_match.group("madpe"),
        )
    )
    return offset_body if cycle_mask is None else f"{offset_body}/{cycle_mask}"


def _replace_suffix_vector(suffix: str, vector: bool) -> str:
    mask_match = _SUFFIX_WITH_MASK_RE.fullmatch(suffix)
    if mask_match is None:
        raise ValueError(f"unsupported operand suffix for vector rewrite: {suffix!r}")

    body = mask_match.group("body")
    cycle_mask = mask_match.group("mask")
    addr_match = _SUFFIX_ADDR_RE.fullmatch(body)
    if addr_match is None:
        raise ValueError(f"unsupported operand suffix for vector rewrite: {suffix!r}")

    vector_suffix = addr_match.group("vector") if vector else ""
    if vector and vector_suffix is None:
        vector_suffix = "v"

    rewritten_body = "".join(
        part or ""
        for part in (
            addr_match.group("t_prefix"),
            addr_match.group("base"),
            vector_suffix,
            addr_match.group("madpe"),
        )
    )
    return rewritten_body if cycle_mask is None else f"{rewritten_body}/{cycle_mask}"


def _format_flat_addrs(addresses: Sequence[int]) -> str:
    """MNCore2.md 3.3 の `[a0,a1,a2,a3]` 形式へ整形する。"""

    if len(addresses) != 4:
        raise ValueError("Flat mode requires exactly 4 cycle addresses")
    return "[" + ",".join(str(addr) for addr in addresses) + "]"


def _append_cycle_mask(suffix: str, cycle_mask: str | None) -> str:
    """`/1000` のような 4 bit 固定マスク suffix を付ける。

    manual 3.6.2.1 の単一行書き込みマスク固定値指定に対応する。既存 API では
    `cycle_mask` という名前を残しているが、実際には 4 サイクルぶんの固定マスク値
    を文字列で保持する用途である。
    """

    if cycle_mask is None:
        return suffix
    if len(cycle_mask) != 4 or any(ch not in "01" for ch in cycle_mask):
        raise ValueError("cycle_mask must be a 4-character bit string such as '1000'")
    return f"{suffix}/{cycle_mask}"


def _validate_write_mask_pattern(mask_pattern: str) -> None:
    if len(mask_pattern) != 4 or any(ch not in "01" for ch in mask_pattern):
        raise ValueError("mask_pattern must be a 4-character bit string such as '1000'")


def _render_write_mask_suffix(
    *,
    mask_pattern: str | None,
    register_addr: int | None,
    double_long: bool,
    guard_suffix: WriteMaskGuardSuffix | None,
) -> str:
    if (mask_pattern is None) == (register_addr is None):
        raise ValueError("Specify exactly one of mask_pattern or register_addr")

    prefix = "ll" if double_long else ""
    if mask_pattern is not None:
        _validate_write_mask_pattern(mask_pattern)
        body = f"{prefix}{mask_pattern}"
    else:
        assert register_addr is not None
        if not 1 <= register_addr <= 15:
            raise ValueError("register_addr must be an integer from 1 to 15")
        body = f"${prefix}imr{register_addr}"

    return body if guard_suffix is None else f"{body}{guard_suffix}"


def _validate_vector_args(*, vector: bool, adri: int | None) -> None:
    if adri is not None and not vector:
        raise ValueError("adri requires vector=True")


@dataclass(frozen=True)
class PDM(Operand):
    """PDM オペランド。`$p<addr>[@<group>]` を表す。

    PDM はグループごとの上位メモリで、主に DRAM / L2BM との MV 転送に使う。
    `group` を省略した表記は manual 上「全グループの同一アドレス」を意味する。

    アドレスは長語単位。
    """

    addr: int
    group: int | None = None

    def _offset_by(self, delta: int) -> Self:
        return replace(self, addr=self.addr + delta)

    def render(self) -> str:
        suffix = f"@{self.group}" if self.group is not None else ""
        return f"$p{self.addr}{suffix}"


@dataclass(frozen=True)
class DRAM(Operand):
    """DRAM オペランド。直接アドレスと DAR 間接参照の両方を扱う。

    `$d...` は長語単位の直接参照、`$di...` は DAR を介した間接参照であり、
    間接側は 16 長語単位で次の DAR エントリへ進む前提を持つ。

    アドレスは長語単位。
    """

    addr: int
    dar_addr: int | None = None
    group: int | None = None

    def _offset_by(self, delta: int) -> Self:
        return replace(self, addr=self.addr + delta)

    def render(self) -> str:
        prefix = f"di{self.dar_addr}" if self.dar_addr is not None else f"d{self.addr}"
        suffix = f"@{self.group}" if self.group is not None else ""
        return f"${prefix}{suffix}"


@dataclass(frozen=True)
class DAR(Operand):
    """DAR エントリ参照。`$dar<addr>`。

    DAR は DRAM 間接参照のベースアドレス表で、各エントリは
    32 bit の「16 長語単位アドレス」を表す。
    """

    addr: int

    def _offset_by(self, delta: int) -> Self:
        return replace(self, addr=self.addr + delta)

    def render(self) -> str:
        return f"$dar{self.addr}"


@dataclass(frozen=True)
class L2BM(Operand):
    """L2BM オペランド。MV 用の group/l2b 修飾も保持する。

    L2BM はグループ内外の放送・分配・縮約の中継点になる中間メモリで、
    MV 側では `@<group>.<l2b>` や `@.<l2b>` を伴う表記を使う。
    PE の L2BM 命令では通常 `$lc<addr>` のみを使う。

    アドレスは長語単位。
    """

    addr: int
    group: int | None = None
    l2b: int | None = None

    def _offset_by(self, delta: int) -> Self:
        return replace(self, addr=self.addr + delta)

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
    """L1BM オペランド。`$lb...` と `$llb...`、`i` 折り返しを表す。

    L1BM は PE 群への放送・MAB 単位転送・縮約に使うローカルブロードキャスト
    メモリで、`indirect=True` は折り返しレジスタ `lbi` を表す。

    アドレスは長語単位。
    """

    addr: int | None = None
    width: WordWidth = WordWidth.LONG
    indirect: bool = False

    def as_width(self, width: WordWidth) -> Self:
        return replace(self, width=width)

    def _offset_by(self, delta: int) -> Self:
        if self.indirect or self.addr is None:
            raise ValueError("L1BM address arithmetic requires a direct addr")
        return replace(self, addr=self.addr + delta)

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
    LM0 は PE の主作業メモリで、T レジスタ間接参照を持てるのはこの空間だけ。
    `j<madpe>` による MAB 内アドレス修飾と `t...` は manual 上同時使用できない。
    """

    suffix: str
    addr: int
    flat_addrs: list[int] = field(default_factory=list)
    width: WordWidth = WordWidth.LONG

    def as_width(self, width: WordWidth) -> Self:
        return replace(self, width=width)

    def as_vector(self, vector: bool = True) -> Self:
        return replace(self, suffix=_replace_suffix_vector(self.suffix, vector))

    def _offset_by(self, delta: int) -> Self:
        flat_addrs = [addr + delta for addr in self.flat_addrs]
        return replace(
            self,
            suffix=_offset_suffix_addresses(self.suffix, delta),
            addr=self.addr + delta,
            flat_addrs=flat_addrs,
        )

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
        """Auto-stride mode の LM0 を生成する。

        `vector=True` は `v[adri]` を、`madpe` は `j<madpe>` を表す。
        """

        _validate_vector_args(vector=vector, adri=adri)
        suffix = str(addr)
        if vector:
            suffix += "v"
            if adri is not None:
                suffix += str(adri)
        if madpe is not None:
            suffix += f"j{madpe}"
        suffix = _append_cycle_mask(suffix, cycle_mask)
        return cls(suffix=suffix, addr=addr, width=width)

    @classmethod
    def flat(
        cls,
        addresses: Sequence[int],
        *,
        width: WordWidth = WordWidth.LONG,
        madpe: int | None = None,
        cycle_mask: str | None = None,
    ) -> LM0:
        """Flat mode の LM0 を生成する。形式は `[a0,a1,a2,a3]`。

        manual の flat mode と同じく、4 サイクルぶんのアドレスを直接固定する。
        """

        suffix = _format_flat_addrs(addresses)
        if madpe is not None:
            suffix += f"j{madpe}"
        suffix = _append_cycle_mask(suffix, cycle_mask)
        return cls(
            suffix=suffix,
            addr=addresses[0],
            flat_addrs=list(addresses),
            width=width,
        )

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
        """T レジスタ間接参照つき auto-stride LM0 を生成する。"""

        _validate_vector_args(vector=vector, adri=adri)
        suffix = f"t{addr}"
        if vector:
            suffix += "v"
            if adri is not None:
                suffix += str(adri)
        suffix = _append_cycle_mask(suffix, cycle_mask)
        return cls(suffix=suffix, addr=addr, width=width)

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
        return cls(
            suffix=suffix,
            addr=addresses[0],
            flat_addrs=list(addresses),
            width=width,
        )

    @classmethod
    def raw(
        cls,
        suffix: str,
        *,
        width: WordWidth = WordWidth.LONG,
        cycle_mask: str | None = None,
    ) -> LM0:
        """仕様未確定の派生記法をそのまま保持したいときに使う。"""

        return cls(
            suffix=_append_cycle_mask(suffix, cycle_mask),
            addr=0,
            width=width,
        )

    def render(self) -> str:
        return f"${self.width.value}m{self.suffix}"


@dataclass(frozen=True)
class LM1(Operand):
    """LM1 オペランド。`auto()` と `flat()` を持つ。

    LM1 は LM0 と同系統のローカルメモリだが、T レジスタ間接参照は持たない。
    """

    suffix: str
    addr: int
    flat_addrs: list[int] = field(default_factory=list)
    width: WordWidth = WordWidth.LONG

    def as_width(self, width: WordWidth) -> Self:
        return replace(self, width=width)

    def as_vector(self, vector: bool = True) -> Self:
        return replace(self, suffix=_replace_suffix_vector(self.suffix, vector))

    def _offset_by(self, delta: int) -> Self:
        flat_addrs = [addr + delta for addr in self.flat_addrs]
        return replace(
            self,
            suffix=_offset_suffix_addresses(self.suffix, delta),
            addr=self.addr + delta,
            flat_addrs=flat_addrs,
        )

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
        """Auto-stride mode の LM1 を生成する。"""

        _validate_vector_args(vector=vector, adri=adri)
        suffix = str(addr)
        if vector:
            suffix += "v"
            if adri is not None:
                suffix += str(adri)
        if madpe is not None:
            suffix += f"j{madpe}"
        suffix = _append_cycle_mask(suffix, cycle_mask)
        return cls(suffix=suffix, addr=addr, width=width)

    @classmethod
    def flat(
        cls,
        addresses: Sequence[int],
        *,
        width: WordWidth = WordWidth.LONG,
        madpe: int | None = None,
        cycle_mask: str | None = None,
    ) -> LM1:
        """Flat mode の LM1 を生成する。

        4 サイクルぶんのアドレスを `[a0,a1,a2,a3]` で固定する。
        """

        suffix = _format_flat_addrs(addresses)
        if madpe is not None:
            suffix += f"j{madpe}"
        suffix = _append_cycle_mask(suffix, cycle_mask)
        return cls(
            suffix=suffix,
            addr=addresses[0],
            flat_addrs=list(addresses),
            width=width,
        )

    @classmethod
    def raw(
        cls,
        suffix: str,
        *,
        width: WordWidth = WordWidth.LONG,
        cycle_mask: str | None = None,
    ) -> LM1:
        return cls(suffix=_append_cycle_mask(suffix, cycle_mask), addr=0, width=width)

    def render(self) -> str:
        return f"${self.width.value}n{self.suffix}"


@dataclass(frozen=True)
class GRF0(Operand):
    """GRF0 オペランド。flat mode と `/1000` 派生表記を補助する。

    GRF0 は ALU / MAU の主要な入出力先で、アドレス空間は 512 単語である。
    長語アクセスでは 2 の倍数、2 長語アクセスでは 4 の倍数アラインが必要だが、
    その検証は builder 側ではなく呼び出し側責務としている。
    """

    suffix: str
    addr: int
    flat_addrs: list[int] = field(default_factory=list)
    width: WordWidth = WordWidth.LONG

    def as_width(self, width: WordWidth) -> Self:
        return replace(self, width=width)

    def as_vector(self, vector: bool = True) -> Self:
        return replace(self, suffix=_replace_suffix_vector(self.suffix, vector))

    def _offset_by(self, delta: int) -> Self:
        flat_addrs = [addr + delta for addr in self.flat_addrs]
        return replace(
            self,
            suffix=_offset_suffix_addresses(self.suffix, delta),
            addr=self.addr + delta,
            flat_addrs=flat_addrs,
        )

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
        """Auto-stride mode の GRF0 を生成する。"""

        _validate_vector_args(vector=vector, adri=adri)
        suffix = str(addr)
        if vector:
            suffix += "v"
            if adri is not None:
                suffix += str(adri)
        suffix = _append_cycle_mask(suffix, cycle_mask)
        return cls(suffix=suffix, addr=addr, width=width)

    @classmethod
    def flat(
        cls,
        addresses: Sequence[int],
        *,
        width: WordWidth = WordWidth.LONG,
        cycle_mask: str | None = None,
    ) -> GRF0:
        """Flat mode の GRF0 を生成する。"""

        return cls(
            suffix=_append_cycle_mask(_format_flat_addrs(addresses), cycle_mask),
            addr=addresses[0],
            flat_addrs=list(addresses),
            width=width,
        )

    @classmethod
    def raw(
        cls,
        suffix: str,
        *,
        width: WordWidth = WordWidth.LONG,
        cycle_mask: str | None = None,
    ) -> GRF0:
        return cls(
            suffix=_append_cycle_mask(suffix, cycle_mask),
            addr=0,
            flat_addrs=[],
            width=width,
        )

    def render(self) -> str:
        return f"${self.width.value}r{self.suffix}"


@dataclass(frozen=True)
class GRF1(Operand):
    """GRF1 オペランド。flat mode と `/1000` 派生表記を補助する。

    制約と役割は GRF0 と同じで、主に第 2 系統の汎用レジスタファイルとして使う。
    """

    suffix: str
    addr: int
    flat_addrs: list[int] = field(default_factory=list)
    width: WordWidth = WordWidth.LONG

    def as_width(self, width: WordWidth) -> Self:
        return replace(self, width=width)

    def as_vector(self, vector: bool = True) -> Self:
        return replace(self, suffix=_replace_suffix_vector(self.suffix, vector))

    def _offset_by(self, delta: int) -> Self:
        flat_addrs = [addr + delta for addr in self.flat_addrs]
        return replace(
            self,
            suffix=_offset_suffix_addresses(self.suffix, delta),
            addr=self.addr + delta,
            flat_addrs=flat_addrs,
        )

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
        """Auto-stride mode の GRF1 を生成する。"""

        _validate_vector_args(vector=vector, adri=adri)
        suffix = str(addr)
        if vector:
            suffix += "v"
            if adri is not None:
                suffix += str(adri)
        suffix = _append_cycle_mask(suffix, cycle_mask)
        return cls(suffix=suffix, addr=addr, flat_addrs=[], width=width)

    @classmethod
    def flat(
        cls,
        addresses: Sequence[int],
        *,
        width: WordWidth = WordWidth.LONG,
        cycle_mask: str | None = None,
    ) -> GRF1:
        """Flat mode の GRF1 を生成する。"""

        return cls(
            suffix=_append_cycle_mask(_format_flat_addrs(addresses), cycle_mask),
            addr=addresses[0],
            flat_addrs=list(addresses),
            width=width,
        )

    @classmethod
    def raw(
        cls,
        suffix: str,
        *,
        width: WordWidth = WordWidth.LONG,
        cycle_mask: str | None = None,
    ) -> GRF1:
        return cls(suffix=_append_cycle_mask(suffix, cycle_mask), addr=0, width=width)

    def render(self) -> str:
        return f"${self.width.value}s{self.suffix}"


@dataclass(frozen=True)
class TReg(Operand):
    """T レジスタ。命令上は現在サイクルに対応する 2 長語を表す。

    文法上 `l` / `ll` は書けるが、manual では常に 2 長語アクセスとして扱われる。
    """

    width: WordWidth = WordWidth.LONG

    def as_width(self, width: WordWidth) -> Self:
        return replace(self, width=width)

    def render(self) -> str:
        return f"${self.width.value}t"


@dataclass(frozen=True)
class MaskRegister(Operand):
    """マスクレジスタ参照。`$omr<addr>`。

    1 エントリは 4 サイクル x 4 bit を持ち、書き込み抑止とゼロフラッシュに使う。
    """

    addr: int

    def _offset_by(self, delta: int) -> Self:
        return replace(self, addr=self.addr + delta)

    def render(self) -> str:
        return f"$omr{self.addr}"


@dataclass(frozen=True)
class Matrix(Operand):
    """行列レジスタの行または列。`$lx0`, `$lly2` などを表す。

    物理的には各面 16 行を持ち、論理サイズは MAU 精度に応じて 4x4 / 8x8 / 16x16
    として解釈される。
    """

    bank: MatrixBank
    addr: int
    width: WordWidth = WordWidth.LONG

    def as_width(self, width: WordWidth) -> Self:
        return replace(self, width=width)

    def _offset_by(self, delta: int) -> Self:
        return replace(self, addr=self.addr + delta)

    @classmethod
    def half(cls, bank: MatrixBank, addr: int, *, double_long: bool = False) -> Matrix:
        """半精度行列アクセス向けの行列オペランドを生成する。"""

        width = WordWidth.DOUBLE_LONG if double_long else WordWidth.LONG
        if width is WordWidth.DOUBLE_LONG and addr % 2 != 0:
            raise ValueError("double-long half matrix access requires an even addr")
        return cls(bank=bank, addr=addr, width=width)

    @classmethod
    def half_read(cls, bank: MatrixBank, addr: int) -> Matrix:
        """`hmread` 用の合法な半精度行列オペランドを生成する。"""

        return cls.half(bank, addr, double_long=True)

    def render(self) -> str:
        return f"${self.width.value}{self.bank.value}{self.addr}"


@dataclass(frozen=True)
class MatrixVector(Operand):
    """MAU の `$lx` / `$ly` ベクトル入力側を表す。

    行列ベクトル積和命令で、面全体を入力ベクトル側として参照するときに使う。
    """

    bank: MatrixBank

    def render(self) -> str:
        return f"$l{self.bank.value}"


@dataclass(frozen=True)
class MauNegatedOperand(Operand):
    """MAU の非行列入力に付く `-<src>` を表す。"""

    operand: PeReadOperand

    def render(self) -> str:
        return f"-{self.operand.render()}"


def negate_mau_input(operand: PeReadOperand) -> MauNegatedOperand:
    """MAU 入力オペランドへ符号反転指定を付ける。"""

    return MauNegatedOperand(operand)


@dataclass(frozen=True)
class Forwarding(Operand):
    """フォワーディングパス入力。`$mauf`, `$aluf` など。

    いずれも直前 step の出力ラッチを読む。manual では `nop` / `noforward` の step
    では更新されない。
    """

    kind: ForwardingKind

    def render(self) -> str:
        return f"${self.kind.value}"


@dataclass(frozen=True)
class FixedInput(Operand):
    """固定値入力。`$peid`, `$l2bid` など。

    manual 上は ALU 第 1 入力専用で、実行位置や固定ビットパターンを供給する。
    """

    kind: FixedInputKind

    def render(self) -> str:
        return f"${self.kind.value}"


@dataclass(frozen=True)
class LM0Base(Operand):
    """LM0 ベースアドレスレジスタ書き込みオペランド。

    書き込み時は MSB 側 1 語の LSB 12 bit が有効値として使われる。
    """

    long_word: bool = True

    def render(self) -> str:
        return "$lmb" if self.long_word else "$mb"


@dataclass(frozen=True)
class LM1Base(Operand):
    """LM1 ベースアドレスレジスタ書き込みオペランド。

    動作は LM0 BAR と同様で、LM1 の最終アドレスへ暗黙加算される。
    """

    long_word: bool = True

    def render(self) -> str:
        return "$lnb" if self.long_word else "$nb"


@dataclass(frozen=True)
class Nowrite(Operand):
    """結果を破棄する `nowrite`。

    結果をフォワーディングだけに残し、他の出力オペランドとの同時指定は許されない。
    """

    def render(self) -> str:
        return "$nowrite"


@dataclass(frozen=True)
class WriteMaskedOperand(Operand):
    """書き込み先 PE メモリオペランドへの単一行書き込みマスク適用。"""

    operand: MaskablePeWriteOperand
    mask_suffix: str

    @classmethod
    def fixed(
        cls,
        operand: MaskablePeWriteOperand,
        mask_pattern: str,
        *,
        double_long: bool = False,
        guard_suffix: WriteMaskGuardSuffix | None = None,
    ) -> WriteMaskedOperand:
        return cls(
            operand=operand,
            mask_suffix=_render_write_mask_suffix(
                mask_pattern=mask_pattern,
                register_addr=None,
                double_long=double_long,
                guard_suffix=guard_suffix,
            ),
        )

    @classmethod
    def register(
        cls,
        operand: MaskablePeWriteOperand,
        register_addr: int,
        *,
        double_long: bool = False,
        guard_suffix: WriteMaskGuardSuffix | None = None,
    ) -> WriteMaskedOperand:
        return cls(
            operand=operand,
            mask_suffix=_render_write_mask_suffix(
                mask_pattern=None,
                register_addr=register_addr,
                double_long=double_long,
                guard_suffix=guard_suffix,
            ),
        )

    def render(self) -> str:
        return f"{self.operand.render()}/{self.mask_suffix}"


def with_write_mask_pattern(
    operand: MaskablePeWriteOperand,
    mask_pattern: str,
    *,
    double_long: bool = False,
    guard_suffix: WriteMaskGuardSuffix | None = None,
) -> WriteMaskedOperand:
    """出力オペランドへ固定値の単一行書き込みマスクを付ける。"""

    return WriteMaskedOperand.fixed(
        operand,
        mask_pattern,
        double_long=double_long,
        guard_suffix=guard_suffix,
    )


def with_write_mask_register(
    operand: MaskablePeWriteOperand,
    register_addr: int | MaskRegister,
    *,
    double_long: bool = False,
    guard_suffix: WriteMaskGuardSuffix | None = None,
) -> WriteMaskedOperand:
    """出力オペランドへ `$imr<addr>` 形式の単一行書き込みマスクを付ける。"""

    return WriteMaskedOperand.register(
        operand,
        register_addr.addr
        if isinstance(register_addr, MaskRegister)
        else register_addr,
        double_long=double_long,
        guard_suffix=guard_suffix,
    )


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


PeReadOperand: TypeAlias = (
    LM0 | LM1 | GRF0 | GRF1 | PeVirtualMemory | PeVirtualFlatMemory | TReg | Forwarding
)
AluReadOperand: TypeAlias = PeReadOperand | FixedInput
MauReadOperand: TypeAlias = PeReadOperand | MauNegatedOperand
MaskablePeWriteOperand: TypeAlias = (
    LM0
    | LM1
    | GRF0
    | GRF1
    | PeVirtualMemory
    | PeVirtualFlatMemory
    | TReg
    | MaskRegister
    | LM0Base
    | LM1Base
)
PeWriteOperand: TypeAlias = MaskablePeWriteOperand | Nowrite | WriteMaskedOperand
MvOperand: TypeAlias = PDM | DRAM | L2BM
MatrixOperand: TypeAlias = Matrix | MatrixVector
