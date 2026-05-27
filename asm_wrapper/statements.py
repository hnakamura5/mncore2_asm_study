from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Literal, TypeAlias


StatementKind: TypeAlias = Literal["instruction", "debug", "pseudo", "cycle"]


@dataclass(frozen=True)
class Statement:
    """レンダリング可能な行単位 statement の基底型。"""

    def render(self) -> str:
        raise NotImplementedError


@dataclass(frozen=True)
class SimpleStatement(Statement):
    """単一テキスト行と任意コメントを持つ statement。"""

    text: str
    comment: str | None = None

    def render(self) -> str:
        if not self.comment:
            return self.text
        return f"{self.text}  # {self.comment}"


@dataclass(frozen=True)
class InstructionStatement(SimpleStatement):
    """通常命令または制約上単独行に置く命令。"""

    kind: ClassVar[StatementKind] = "instruction"


@dataclass(frozen=True)
class DebugStatement(SimpleStatement):
    """エミュレータ専用の debug 文。"""

    kind: ClassVar[StatementKind] = "debug"


@dataclass(frozen=True)
class PseudoStatement(SimpleStatement):
    """アセンブラ補助用の疑似構文。"""

    kind: ClassVar[StatementKind] = "pseudo"


@dataclass(frozen=True)
class CycleStatement(Statement):
    """同一 cycle に同時発行する複数命令を束ねた statement。

    想定しているのは 1 step 内の PE 命令束ねだけで、MV / debug / pseudo 文は入らない。
    並列実行条件そのものは builder では検証しない。
    """

    items: tuple[InstructionStatement, ...]
    kind: ClassVar[StatementKind] = "cycle"

    def render(self) -> str:
        return "; ".join(item.render() for item in self.items)
