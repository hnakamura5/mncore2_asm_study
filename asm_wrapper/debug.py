"""MN-Core 2 の `d get` / `d set` 向け型付き target 群。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TypeAlias

from .operands import MatrixBank, WordWidth


class DebugDataType(str, Enum):
    """`d get[<dtype>]` の `<dtype>` を表す列挙。"""

    DEFAULT = ""
    DOUBLE = "d"
    BLOCK_DOUBLE = "bd"
    FLOAT = "f"
    BLOCK_FLOAT = "bf"
    BLOCK_GFLOAT = "bg"
    HALF = "h"
    BLOCK_HALF = "bh"


@dataclass(frozen=True)
class DebugScope:
    """`[n<group>][c<l2b>][b<l1b>][m<mab>][p<pe>]` 修飾子を表す。"""

    group: int | None = None
    l2b: int | None = None
    l1b: int | None = None
    mab: int | None = None
    pe: int | None = None

    def render(self) -> str:
        suffix = ""
        if self.group is not None:
            suffix += f"n{self.group}"
        if self.l2b is not None:
            suffix += f"c{self.l2b}"
        if self.l1b is not None:
            suffix += f"b{self.l1b}"
        if self.mab is not None:
            suffix += f"m{self.mab}"
        if self.pe is not None:
            suffix += f"p{self.pe}"
        return suffix


@dataclass(frozen=True)
class DebugMemoryRef:
    """資料に未整理の target を直接表したいときの汎用 debug target。"""

    token: str
    scope: DebugScope | None = None

    def render(self) -> str:
        scope = self.scope.render() if self.scope is not None else ""
        return f"${self.token}{scope}"


@dataclass(frozen=True)
class DebugLM0Ref:
    """LM0 の debug target。例: `$lm0n0c0b0m0p0`。"""

    addr: int
    scope: DebugScope | None = None

    def render(self) -> str:
        return DebugMemoryRef(f"lm{self.addr}", self.scope).render()


@dataclass(frozen=True)
class DebugLM1Ref:
    """LM1 の debug target。例: `$ln0n0c0b0m0p0`。"""

    addr: int
    scope: DebugScope | None = None

    def render(self) -> str:
        return DebugMemoryRef(f"ln{self.addr}", self.scope).render()


@dataclass(frozen=True)
class DebugGRF0Ref:
    """GRF0 の debug target。例: `$lr0...`。"""

    addr: int
    scope: DebugScope | None = None

    def render(self) -> str:
        return DebugMemoryRef(f"lr{self.addr}", self.scope).render()


@dataclass(frozen=True)
class DebugGRF1Ref:
    """GRF1 の debug target。例: `$ls0...`。"""

    addr: int
    scope: DebugScope | None = None

    def render(self) -> str:
        return DebugMemoryRef(f"ls{self.addr}", self.scope).render()


@dataclass(frozen=True)
class DebugTRegRef:
    """T レジスタの debug target。`$tn...` と `$ltn...` を切り替える。"""

    long_word: bool = True
    scope: DebugScope | None = None

    def render(self) -> str:
        token = "lt" if self.long_word else "t"
        return DebugMemoryRef(token, self.scope).render()


@dataclass(frozen=True)
class DebugMaskRef:
    """マスクレジスタの debug target。例: `$omr1...`。"""

    addr: int
    scope: DebugScope | None = None

    def render(self) -> str:
        return DebugMemoryRef(f"omr{self.addr}", self.scope).render()


@dataclass(frozen=True)
class DebugL1BMRef:
    """L1BM の debug target。例: `$lb0...`。"""

    addr: int
    scope: DebugScope | None = None

    def render(self) -> str:
        return DebugMemoryRef(f"lb{self.addr}", self.scope).render()


@dataclass(frozen=True)
class DebugL2BMRef:
    """L2BM の debug target。例: `$lc0...`。"""

    addr: int
    scope: DebugScope | None = None

    def render(self) -> str:
        return DebugMemoryRef(f"lc{self.addr}", self.scope).render()


@dataclass(frozen=True)
class DebugMatrixRef:
    """行列レジスタの debug target。

    直接の実例は手元資料に見当たらないため、`dmread` / `hmread` などの
    行列オペランド表記から `$lx0`, `$lly2` のような token を推定している。
    """

    bank: MatrixBank
    addr: int
    width: WordWidth = WordWidth.LONG
    scope: DebugScope | None = None

    def render(self) -> str:
        return DebugMemoryRef(f"{self.width.value}{self.bank.value}{self.addr}", self.scope).render()


DebugMemoryOperand: TypeAlias = (
    DebugMemoryRef
    | DebugLM0Ref
    | DebugLM1Ref
    | DebugGRF0Ref
    | DebugGRF1Ref
    | DebugTRegRef
    | DebugMaskRef
    | DebugL1BMRef
    | DebugL2BMRef
    | DebugMatrixRef
)
