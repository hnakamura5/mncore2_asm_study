"""MN-Core 2 の VSM 命令列を組み立てる builder。"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator, Sequence, Self, overload

from .debug import DebugDataType, DebugMemoryOperand
from .operands import (
    AluReadOperand,
    ALUAnyPrecision,
    ALUBfnPrecision,
    ALUFloatPrecision,
    ALUIntPrecision,
    DAR,
    DRAM,
    FixedInput,
    Forwarding,
    ForwardingKind,
    L1BM,
    L2BM,
    MauReadOperand,
    MAUHalfSelect,
    Matrix,
    MatrixVector,
    MvOperand,
    Nowrite,
    PDM,
    PeReadOperand,
    PeWriteOperand,
    RRNOpcode,
    WordWidth,
)
from .statements import (
    CycleStatement,
    DebugStatement,
    InstructionStatement,
    PseudoStatement,
    Statement,
)


class InstructionBuilder:
    """
    MN-Core 2 の VSM 命令列を組み立てる行指向 builder。

    このクラスは `MNCore2.md` と `mncore2_dev_manual_ja.pdf` の命令体系を、
    Python から安全に書きやすい形へ寄せた薄いラッパである。各メソッドは 1 つの
    ニーモニック、または 1 つの擬似構文に対応し、呼び出し順に `Statement` を蓄積する。

    読み方:
    - docstring 中の「生成構文」は builder が最終的に出力する VSM 1 行の形を表す。
    - 「入力例」は典型的な命令文字列または tutorial/manual 由来の入力条件を示す。
    - 「結果例」はレジスタやメモリ上で何が起きるかを高レベルに説明する。
    - 実データ付きの例は `mncore2_emuenv_20240826/tutorial.md` や manual の debug 例に合わせている。

    制約:
    - この builder は文法整形を担当し、全てのハザード・待機サイクル・精度制約までは自動検証しない。
    - MV 命令は非同期実行であり、必要に応じて `wait()` や `nop()` を併用する前提で使う。
    - 複数 MV 命令の同時発行制約や、PE 命令の並列実行条件・ハザード待ちは呼び出し側責務である。
    - ALU/MAU の入力精度拡張・縮減、マスクフラグ生成規則、`nowrite` の排他条件も文字列化のみを行う。
    - 一部の結果例は manual の説明を builder 利用者向けに要約した概念図である。
    """

    def __init__(self) -> None:
        """
        builder の内部状態を初期化する。`_lines` は確定済み statement 列、`_active_cycle` は cycle 文脈の一時バッファ。

        役割:
            `InstructionBuilder` を空の状態で作る。

        入力と結果の例:
            入力例: `builder = InstructionBuilder()`
            結果例: まだ命令は 1 行も持たず、`builder.lines()` は空タプルを返す。
        """
        # `_lines` は最終的な出力順を保つ statement 列、`_active_cycle` は
        # `with builder.cycle(): ...` の間だけ有効になる同時発行バッファ。
        self._lines: list[Statement] = []
        self._active_cycle: list[InstructionStatement] | None = None

    @contextmanager
    def cycle(self) -> Generator[InstructionBuilder, None, None]:
        """
        対応: MNCore2.md 7.1 PE 命令の共通仕様

        同一 step で同時発行する PE 命令を 1 行へ束ねる context manager。
        `with builder.cycle(): ...` の内部で追加した PE 命令は `;` 区切りで同一行に出力される。

        注意:
        - MV / debug / pseudo 文は cycle 内へ追加できない。
        - ネストした `cycle()` は未対応で例外になる。
        - 同時発行できる組み合わせかどうかまではここでは検証しない。

        生成構文:
            cycle 内の PE 命令を `;` 区切りの 1 行へ束ねる。

        入力と結果の例:
            入力例:
                with builder.cycle():
                    builder.fvadd(src_x_operand=LM0.auto(0), src_y_operand=LM1.auto(0), dst_operands=[GRF0.auto(0)])
                    builder.wait(tag=1)
            結果例: `fvadd $lm0 $ln0 $lr0 ; wait 1` のような 1 step 分の複合行になる。

        補足:
            PE 命令だけが対象で、MV / debug / pseudo 文を入れると例外になる。
        """
        if self._active_cycle is not None:
            raise RuntimeError("Nested cycles are not supported")
        self._active_cycle = []
        try:
            yield self
        finally:
            cycle = self._active_cycle
            self._active_cycle = None
            if cycle:
                self._lines.append(CycleStatement(items=tuple(cycle)))

    def statements(self) -> tuple[Statement, ...]:
        """
        現在までに追加した statement を型付きのまま返す。

        `InstructionStatement` / `CycleStatement` / `DebugStatement` /
        `PseudoStatement` を区別したいときに使う。

        入力と結果の例:
            入力例: `builder.debug_get(...); builder.nop()` の後で `builder.statements()` を呼ぶ。
            結果例: `DebugStatement` と `InstructionStatement` が型付きで返るため、後段で debug 文だけを除外できる。
        """
        if self._active_cycle is not None:
            raise RuntimeError("Cannot read statements while a cycle context is open")
        return tuple(self._lines)

    def lines(self) -> tuple[str, ...]:
        """
        現在の命令列を 1 行ずつレンダリングして返す。cycle 中は呼べない。

        入力と結果の例:
            入力例: `builder.nop(); builder.quit()` の後で `builder.lines()` を呼ぶ。
            結果例: `("nop", "quit # pseudo: assembler-only, not emitted as machine code")` のようなレンダリング済み行列になる。
        """
        if self._active_cycle is not None:
            raise RuntimeError("Cannot read lines while a cycle context is open")
        return tuple(statement.render() for statement in self._lines)

    def to_source(self) -> str:
        """
        命令列全体を VSM ソース文字列へ変換して返す。

        入力と結果の例:
            入力例: `builder.nop(); builder.noforward()` の後で `builder.to_source()` を呼ぶ。
            結果例: 改行区切りの VSM 文字列 `"nop\nnoforward"` が返る。
        """
        return "\n".join(self.lines())

    def __str__(self) -> str:
        """
        現在の命令列を VSM ソース文字列として返す。
        """
        return self.to_source()

    def _render_operand(self, operand: object) -> str:
        """
        render() を持つオペランドはそれを使い、それ以外は str() で文字列化する。
        """
        render = getattr(operand, "render", None)
        if callable(render):
            return str(render())
        return str(operand)

    def _render_operands(self, operands: Sequence[object]) -> str:
        """
        複数の書き込み先オペランドを空白区切りに整形する。空列は許可しない。
        """
        if not operands:
            raise ValueError("At least one destination operand is required")
        if (
            any(isinstance(operand, Nowrite) for operand in operands)
            and len(operands) != 1
        ):
            raise ValueError("nowrite must be the only destination operand")
        return " ".join(self._render_operand(operand) for operand in operands)

    def _validate_alu_source_operand(
        self, operand: object, *, position: int, opcode: str
    ) -> None:
        if position != 0 and isinstance(operand, FixedInput):
            raise ValueError(
                f"{opcode} allows fixed inputs only in the first ALU source"
            )
        if (
            position != 0
            and isinstance(operand, Forwarding)
            and operand.kind == ForwardingKind.MREAD
        ):
            raise ValueError(f"{opcode} allows mreadf only in the first ALU source")

    def _emit_alu_unary(
        self, opcode: str, src_operand: object, dst_operands: Sequence[object]
    ) -> Self:
        self._validate_alu_source_operand(src_operand, position=0, opcode=opcode)
        return self._emit_pe(
            f"{opcode} {self._render_operand(src_operand)} {self._render_operands(dst_operands)}"
        )

    def _emit_alu_binary(
        self,
        opcode: str,
        src_x_operand: object,
        src_y_operand: object,
        dst_operands: Sequence[object],
    ) -> Self:
        self._validate_alu_source_operand(src_x_operand, position=0, opcode=opcode)
        self._validate_alu_source_operand(src_y_operand, position=1, opcode=opcode)
        return self._emit_pe(
            f"{opcode} {self._render_operand(src_x_operand)} {self._render_operand(src_y_operand)} {self._render_operands(dst_operands)}"
        )

    def _validate_half_matrix(
        self, matrix: Matrix, *, opcode: str, require_double_long: bool
    ) -> None:
        if require_double_long and matrix.width != WordWidth.DOUBLE_LONG:
            raise ValueError(f"{opcode} requires a double-long matrix operand")
        if matrix.width == WordWidth.DOUBLE_LONG and matrix.addr % 2 != 0:
            raise ValueError(
                f"{opcode} requires an even matrix addr for double-long access"
            )

    def _emit_pe(self, text: str) -> Self:
        """
        PE 命令を追加する。cycle 文脈が開いている場合は同一行バッファへ積み、そうでなければ単独行で確定する。
        """
        # PE 命令は cycle コンテキスト内なら同一行へ束ね、外なら単独行で積む。
        statement = InstructionStatement(text=text)
        if self._active_cycle is None:
            self._lines.append(statement)
            return self
        self._active_cycle.append(statement)
        return self

    def _emit_non_pe(self, statement: Statement) -> Self:
        """
        MV / debug / pseudo のような非 PE statement を追加する。cycle 文脈中は構文を壊すため拒否する。
        """
        # MV / debug / pseudo は cycle 内に混ぜると構文上の意味が崩れるため拒否する。
        if self._active_cycle is not None:
            raise RuntimeError(
                "MV/debug/control instructions cannot be emitted inside cycle()"
            )
        self._lines.append(statement)
        return self

    def _mv_suffix(
        self,
        *,
        size: int,
        tag: int | None,
        nd: int | None,
        priority: int | None,
    ) -> str:
        """
        MV 命令共通の `/n<size>[i<tag>][nd<N>][p<priority>]` 接尾辞を組み立てる。
        """
        # MV 系の `/n<size>[i<tag>][nd<N>][p<priority>]` を共通整形する。
        suffix = f"/n{size}"
        if tag is not None:
            suffix += f"i{tag}"
        if nd is not None:
            suffix += f"nd{nd}"
        if priority is not None:
            suffix += f"p{priority}"
        return suffix

    def _emit_mv(
        self,
        opcode: str,
        *,
        size: int,
        src_operand: MvOperand,
        dst_operand: MvOperand,
        tag: int | None = None,
        nd: int | None = None,
        priority: int | None = None,
    ) -> Self:
        """
        MV 命令 1 行を構築して non-PE statement として追加する。

        manual が言及する「複数 MV 命令を同時発行する場合の追加制約」はここでは見ない。
        """
        suffix = self._mv_suffix(size=size, tag=tag, nd=nd, priority=priority)
        return self._emit_non_pe(
            InstructionStatement(
                text=f"{opcode}{suffix} {src_operand.render()} {dst_operand.render()}"
            )
        )

    def quit(self) -> Self:
        """
        対応: MNCore2.md 5.1 `quit`

        以降のアセンブリを無視する擬似命令を追加する。
        実機命令ではなく、`PseudoStatement` として記録される。

        生成構文:
            `quit`

        入力と結果の例:
            入力例: `quit`
            結果例: 以降のアセンブリは無視される。builder 上では `PseudoStatement` として保持され、実機命令は発生しない。
        """
        return self._emit_non_pe(
            PseudoStatement(
                text="quit",
                comment="pseudo: assembler-only, not emitted as machine code",
            )
        )

    # --- 5. 制御文とデバッグ文 ---

    def debug_get(
        self,
        *,
        target_memory: DebugMemoryOperand | str,
        num_words: int,
        dtype: DebugDataType | str | None = None,
    ) -> Self:
        """
        対応: MNCore2.md 5.2 `d get`

        エミュレータ実行時に対象メモリの内容をダンプする debug 文を追加する。

        主な引数:
        - `target_memory`: `DebugLM0Ref` や `DebugMatrixRef` などの型付き target、または raw string。
        - `num_words`: 読み出す長語数。
        - `dtype`: `d`, `f`, `h` などの表示型。不要なら省略できる。

        注意:
        - 実機では使えない。
        - エミュレータはサイクルアキュレートではないため、直前命令完了後の状態を見る。

        生成構文:
            `d get[<dtype>] <memory> <num_of_words>`

        入力と結果の例:
            入力例: `d getd $lm0n0c0b0m0p0 1`
            結果例: tutorial の例では `DEBUG-LM0(...):(1) (0x3ff0000000000000)` のように、LM0 の 1.0 が double 解釈で出力される。

        補足:
            manual では debug 文は「十分待ってから読んだのと同等の結果」を返すと説明される。実機同期そのものを再現する命令ではない。
        """
        dtype_suffix = (
            dtype.value if isinstance(dtype, DebugDataType) else (dtype or "")
        )
        memory = (
            target_memory if isinstance(target_memory, str) else target_memory.render()
        )
        return self._emit_non_pe(
            DebugStatement(
                text=f"d get{dtype_suffix} {memory} {num_words}",
                comment="debug: emulator-only memory dump",
            )
        )

    def debug_set(
        self,
        *,
        target_memory: DebugMemoryOperand | str,
        num_words: int,
        payload: str,
    ) -> Self:
        """
        対応: MNCore2.md 5.3 `d set`

        エミュレータ実行時に対象メモリへ値を書き込む debug 文を追加する。

        主な引数:
        - `target_memory`: 型付き debug target、または raw string。
        - `num_words`: 書き込む長語数。
        - `payload`: debug 文法そのままの 16 進 payload 文字列。

        注意:
        - 実機では使えない。
        - payload の語長解釈は debug 文法に従う。

        生成構文:
            `d set <memory> <num_of_words> <payload>`

        入力と結果の例:
            入力例: `d set $lm0n0c0b0m0p0 1 3FF0000000000000`
            結果例: LM0 の対象 1 長語へ double の 1.0 が書き込まれ、直後の `d getd` で同じ値を確認できる。

        補足:
            payload は 64bit 長語単位で並べる。単語や半語の値を書きたい場合も、manual の表記どおり残りビットを埋めた長語表現を与える。
        """
        memory = (
            target_memory if isinstance(target_memory, str) else target_memory.render()
        )
        return self._emit_non_pe(
            DebugStatement(
                text=f"d set {memory} {num_words} {payload}",
                comment="debug: emulator-only memory write",
            )
        )

    def mask(self, *, mask_index: int) -> Self:
        """
        チュートリアル由来の疑似構文 `mask <idx>` を追加する。現在の書き込みマスク選択を表す補助文。

        生成構文:
            `mask <idx>`

        入力と結果の例:
            入力例: `mask 1`
            結果例: tutorial 由来の疑似構文として「以降の補助命令はマスク 1 を使う」という意図を明示できる。
        """
        return self._emit_non_pe(
            PseudoStatement(
                text=f"mask {mask_index}",
                comment="pseudo: tutorial helper syntax",
            )
        )

    def maskn(self, *, mask_index: int) -> Self:
        """
        チュートリアル由来の疑似構文 `maskn <idx>` を追加する。`mask` の反転系補助文として扱う。

        生成構文:
            `maskn <idx>`

        入力と結果の例:
            入力例: `maskn 1`
            結果例: `mask` の反転系を表す補助行が出力される。実際の意味付けはチュートリアル側のマクロ展開に依存する。
        """
        return self._emit_non_pe(
            PseudoStatement(
                text=f"maskn {mask_index}",
                comment="pseudo: tutorial helper syntax",
            )
        )

    def nop_repeat(self, *, repeat: int) -> Self:
        """
        チュートリアル由来の疑似構文 `nop/<repeat>` を追加する。複数 step の NOP を簡略記法で表したいときに使う。

        生成構文:
            `nop/<repeat>`

        入力と結果の例:
            入力例: `nop/2`
            結果例: tutorial では `nop` を 2 step 連続で書いたのと同じ待機意図を簡潔に表せる。
        """
        return self._emit_non_pe(
            PseudoStatement(
                text=f"nop/{repeat}",
                comment="pseudo: assembler repetition shorthand",
            )
        )

    def pseudo_raw(self, *, text: str, comment: str | None = None) -> Self:
        """
        未整理の疑似構文を `PseudoStatement` としてそのまま追加する。仕様未確定の補助構文を退避したいとき向け。

        入力と結果の例:
            入力例: `pseudo_raw(text="mask 3", comment="tutorial helper")`
            結果例: 未整理の疑似構文を、そのままコメント付き 1 行としてソースへ残せる。
        """
        return self._emit_non_pe(
            PseudoStatement(
                text=text,
                comment=comment or "pseudo: raw helper syntax",
            )
        )

    def mvnop(self) -> Self:
        """
        対応: MNCore2.md 6.2 `mvnop`

        何も転送しない MV NOP を追加する。

        主な引数:
        - `size`: `n<size>` に入る転送語数。
        - `src_operand`, `dst_operand`: 命令方向を表すオペランド。
        - `tag`: `wait` と組み合わせるタグ。不要なら省略。
        - `priority`: MV 優先度。必要なときだけ指定する。

        注意:
        - `mvp` / `mvd` / `mvr` では `nd` による DAR 連続使用回数を指定できる。
        - 実際の合法な `size` やアラインメントは呼び出し側で守る前提。

        生成構文:
            `mvnop`

        入力と結果の例:
            入力例: `mvnop`
            結果例: MV パスでは何も転送せず、タグもデータ移動も発生しない。MV キューの空きやタイミングだけを明示したいときに使う。
        """
        return self._emit_non_pe(InstructionStatement(text="mvnop"))

    # --- 6. MV 命令セット ---

    @overload
    def mvp(
        self,
        *,
        size: int,
        src_operand: PDM,
        dst_operand: PDM | DRAM | L2BM,
        tag: int | None = None,
        nd: int | None = None,
        priority: int | None = None,
    ) -> Self: ...

    @overload
    def mvp(
        self,
        *,
        size: int,
        src_operand: DRAM,
        dst_operand: PDM | L2BM,
        tag: int | None = None,
        nd: int | None = None,
        priority: int | None = None,
    ) -> Self: ...

    @overload
    def mvp(
        self,
        *,
        size: int,
        src_operand: L2BM,
        dst_operand: PDM | DRAM,
        tag: int | None = None,
        nd: int | None = None,
        priority: int | None = None,
    ) -> Self: ...

    def mvp(
        self,
        *,
        size: int,
        src_operand: MvOperand,
        dst_operand: MvOperand,
        tag: int | None = None,
        nd: int | None = None,
        priority: int | None = None,
    ) -> Self:
        """
        対応: MNCore2.md 6.3 `mvp`

        個別転送を追加する。PDM/DRAM/L2BM の対応組み合わせは overload で型分けしている。

        主な引数:
        - `size`: `n<size>` に入る転送語数。
        - `src_operand`, `dst_operand`: 命令方向を表すオペランド。
        - `tag`: `wait` と組み合わせるタグ。不要なら省略。
        - `priority`: MV 優先度。必要なときだけ指定する。

        注意:
        - `mvp` / `mvd` / `mvr` では `nd` による DAR 連続使用回数を指定できる。
        - 実際の合法な `size` やアラインメントは呼び出し側で守る前提。

        生成構文:
            `mvp/n<size>[i<tag>][nd<N>][p<priority>] <src> <dst>`

        入力と結果の例:
            入力例: `mvp/n64i1 $p0@0 $lc0@2.1`
            結果例: PDM `$p0@0` から L2BM `$lc0@2.1` へ 64 長語を非同期転送し、完了時に tag 1 を立てる。

        補足:
            manual の例 `mvp/n64i01 $p0@0 $lc0@2.1` と同じ並びを builder で生成できる。
        """
        return self._emit_mv(
            "mvp",
            size=size,
            src_operand=src_operand,
            dst_operand=dst_operand,
            tag=tag,
            nd=nd,
            priority=priority,
        )

    @overload
    def mvb(
        self,
        *,
        size: int,
        src_operand: PDM,
        dst_operand: L2BM,
        tag: int | None = None,
        priority: int | None = None,
    ) -> Self: ...

    @overload
    def mvb(
        self,
        *,
        size: int,
        src_operand: DRAM,
        dst_operand: L2BM,
        tag: int | None = None,
        priority: int | None = None,
    ) -> Self: ...

    def mvb(
        self,
        *,
        size: int,
        src_operand: PDM | DRAM,
        dst_operand: L2BM,
        tag: int | None = None,
        priority: int | None = None,
    ) -> Self:
        """
        対応: MNCore2.md 6.4 `mvb`

        1 ソースを複数 L2BM へ放送する MV 放送命令を追加する。

        主な引数:
        - `size`: `n<size>` に入る転送語数。
        - `src_operand`, `dst_operand`: 命令方向を表すオペランド。
        - `tag`: `wait` と組み合わせるタグ。不要なら省略。
        - `priority`: MV 優先度。必要なときだけ指定する。

        注意:
        - `mvp` / `mvd` / `mvr` では `nd` による DAR 連続使用回数を指定できる。
        - 実際の合法な `size` やアラインメントは呼び出し側で守る前提。

        生成構文:
            `mvb/n<size>[i<tag>][p<priority>] <src> <dst>`

        入力と結果の例:
            入力例: `mvb/n64i2 $d0 $lc0@0.0`
            結果例: DRAM `$d0` の同一データ列を、放送先に含まれる複数の L2BM へ複製しながら配る。完了時は tag 2 を使って待機できる。
        """
        return self._emit_mv(
            "mvb",
            size=size,
            src_operand=src_operand,
            dst_operand=dst_operand,
            tag=tag,
            priority=priority,
        )

    def mvb2(
        self,
        *,
        size: int,
        src_operand: DRAM,
        dst_operand: L2BM,
        tag: int | None = None,
        priority: int | None = None,
    ) -> Self:
        """
        対応: MNCore2.md 6.5 `mvb2`

        グループ内で DRAM から 2 つの L2BM へ放送する命令を追加する。

        主な引数:
        - `size`: `n<size>` に入る転送語数。
        - `src_operand`, `dst_operand`: 命令方向を表すオペランド。
        - `tag`: `wait` と組み合わせるタグ。不要なら省略。
        - `priority`: MV 優先度。必要なときだけ指定する。

        注意:
        - `mvp` / `mvd` / `mvr` では `nd` による DAR 連続使用回数を指定できる。
        - 実際の合法な `size` やアラインメントは呼び出し側で守る前提。

        生成構文:
            `mvb2/n<size>[i<tag>][p<priority>] <src> <dst>`

        入力と結果の例:
            入力例: `mvb2/n64 $d0 $lc0@1.0`
            結果例: DRAM から読んだ 1 本のストリームを、グループ内の 2 系統へ対応付けて放送する。`mvr2` と対で使うと戻し方を揃えやすい。
        """
        return self._emit_mv(
            "mvb2",
            size=size,
            src_operand=src_operand,
            dst_operand=dst_operand,
            tag=tag,
            priority=priority,
        )

    def mvb4(
        self,
        *,
        size: int,
        src_operand: DRAM,
        dst_operand: L2BM,
        tag: int | None = None,
        priority: int | None = None,
    ) -> Self:
        """
        対応: MNCore2.md 6.6 `mvb4`

        DRAM からの分配放送命令を追加する。

        主な引数:
        - `size`: `n<size>` に入る転送語数。
        - `src_operand`, `dst_operand`: 命令方向を表すオペランド。
        - `tag`: `wait` と組み合わせるタグ。不要なら省略。
        - `priority`: MV 優先度。必要なときだけ指定する。

        注意:
        - `mvp` / `mvd` / `mvr` では `nd` による DAR 連続使用回数を指定できる。
        - 実際の合法な `size` やアラインメントは呼び出し側で守る前提。

        生成構文:
            `mvb4/n<size>[i<tag>][p<priority>] <src> <dst>`

        入力と結果の例:
            入力例: `mvb4/n128 $d0 $lc0@0.0`
            結果例: DRAM ストリームを 4 系統へ分配しながら放送する。グループ間へ同じブロックを広く撒きたいときの入口になる。
        """
        return self._emit_mv(
            "mvb4",
            size=size,
            src_operand=src_operand,
            dst_operand=dst_operand,
            tag=tag,
            priority=priority,
        )

    @overload
    def mvr(
        self,
        *,
        rrn_opcode: RRNOpcode,
        size: int,
        src_operand: L2BM,
        dst_operand: PDM,
        tag: int | None = None,
        nd: int | None = None,
        priority: int | None = None,
    ) -> Self: ...

    @overload
    def mvr(
        self,
        *,
        rrn_opcode: RRNOpcode,
        size: int,
        src_operand: L2BM,
        dst_operand: DRAM,
        tag: int | None = None,
        nd: int | None = None,
        priority: int | None = None,
    ) -> Self: ...

    def mvr(
        self,
        *,
        rrn_opcode: RRNOpcode,
        size: int,
        src_operand: L2BM,
        dst_operand: PDM | DRAM,
        tag: int | None = None,
        nd: int | None = None,
        priority: int | None = None,
    ) -> Self:
        """
        対応: MNCore2.md 6.7 `mvr`

        複数 L2BM の値を縮約して PDM または DRAM へ戻す命令を追加する。

        主な引数:
        - `size`: `n<size>` に入る転送語数。
        - `src_operand`, `dst_operand`: 命令方向を表すオペランド。
        - `tag`: `wait` と組み合わせるタグ。不要なら省略。
        - `priority`: MV 優先度。必要なときだけ指定する。

        注意:
        - `mvp` / `mvd` / `mvr` では `nd` による DAR 連続使用回数を指定できる。
        - 実際の合法な `size` やアラインメントは呼び出し側で守る前提。

        生成構文:
            `mvr<rrn_opcode>/n<size>[i<tag>][nd<N>][p<priority>] <src> <dst>`

        入力と結果の例:
            入力例: `mvrdfadd/n64 $lc0@2.1 $p0@0`
            結果例: L2BM 群から 64 長語を読み出し、`dfadd` で縮約した結果を PDM `$p0@0` へ戻す。たとえば各 L2BM が部分和を持っていれば、出力側には総和が現れる。
        """
        return self._emit_mv(
            f"mvr{rrn_opcode}",
            size=size,
            src_operand=src_operand,
            dst_operand=dst_operand,
            tag=tag,
            nd=nd,
            priority=priority,
        )

    def mvr2(
        self,
        *,
        rrn_opcode: RRNOpcode,
        size: int,
        src_operand: L2BM,
        dst_operand: PDM | DRAM,
        tag: int | None = None,
        priority: int | None = None,
    ) -> Self:
        """
        対応: MNCore2.md 6.8 `mvr2`

        同一グループ内 2 L2BM の縮約命令を追加する。

        主な引数:
        - `size`: `n<size>` に入る転送語数。
        - `src_operand`, `dst_operand`: 命令方向を表すオペランド。
        - `tag`: `wait` と組み合わせるタグ。不要なら省略。
        - `priority`: MV 優先度。必要なときだけ指定する。

        注意:
        - `mvp` / `mvd` / `mvr` では `nd` による DAR 連続使用回数を指定できる。
        - 実際の合法な `size` やアラインメントは呼び出し側で守る前提。

        生成構文:
            `mvr2<rrn_opcode>/n<size>[i<tag>][p<priority>] <src> <dst>`

        入力と結果の例:
            入力例: `mvr2ffadd/n64 $lc0@1.0 $d0`
            結果例: `mvb2` で 2 分配した経路を対にして縮約し、単一の DRAM ストリームへ戻す。
        """
        return self._emit_mv(
            f"mvr2{rrn_opcode}",
            size=size,
            src_operand=src_operand,
            dst_operand=dst_operand,
            tag=tag,
            priority=priority,
        )

    def mvr4(
        self,
        *,
        rrn_opcode: RRNOpcode,
        size: int,
        src_operand: L2BM,
        dst_operand: DRAM,
        tag: int | None = None,
        priority: int | None = None,
    ) -> Self:
        """
        対応: MNCore2.md 6.9 `mvr4`

        複数グループ・複数 L2BM の結合縮約命令を追加する。

        主な引数:
        - `size`: `n<size>` に入る転送語数。
        - `src_operand`, `dst_operand`: 命令方向を表すオペランド。
        - `tag`: `wait` と組み合わせるタグ。不要なら省略。
        - `priority`: MV 優先度。必要なときだけ指定する。

        注意:
        - `mvp` / `mvd` / `mvr` では `nd` による DAR 連続使用回数を指定できる。
        - 実際の合法な `size` やアラインメントは呼び出し側で守る前提。

        生成構文:
            `mvr4<rrn_opcode>/n<size>[i<tag>][p<priority>] <src> <dst>`

        入力と結果の例:
            入力例: `mvr4ffadd/n128 $lc0@0.0 $d0`
            結果例: 4 系統へ広げた L2BM データを縮約しながら再配置して DRAM へ戻す。複数グループの部分結果を 1 本へ畳み込みたいときに使う。
        """
        return self._emit_mv(
            f"mvr4{rrn_opcode}",
            size=size,
            src_operand=src_operand,
            dst_operand=dst_operand,
            tag=tag,
            priority=priority,
        )

    @overload
    def mvd(
        self,
        *,
        size: int,
        src_operand: PDM,
        dst_operand: L2BM | DRAM,
        tag: int | None = None,
        nd: int | None = None,
        priority: int | None = None,
    ) -> Self: ...

    @overload
    def mvd(
        self,
        *,
        size: int,
        src_operand: L2BM | DRAM,
        dst_operand: PDM,
        tag: int | None = None,
        nd: int | None = None,
        priority: int | None = None,
    ) -> Self: ...

    def mvd(
        self,
        *,
        size: int,
        src_operand: MvOperand,
        dst_operand: MvOperand,
        tag: int | None = None,
        nd: int | None = None,
        priority: int | None = None,
    ) -> Self:
        """
        対応: MNCore2.md 6.10 `mvd`

        分配または結合を目的とした MV 再レイアウト命令を追加する。

        主な引数:
        - `size`: `n<size>` に入る転送語数。
        - `src_operand`, `dst_operand`: 命令方向を表すオペランド。
        - `tag`: `wait` と組み合わせるタグ。不要なら省略。
        - `priority`: MV 優先度。必要なときだけ指定する。

        注意:
        - `mvp` / `mvd` / `mvr` では `nd` による DAR 連続使用回数を指定できる。
        - 実際の合法な `size` やアラインメントは呼び出し側で守る前提。

        生成構文:
            `mvd/n<size>[i<tag>][nd<N>][p<priority>] <src> <dst>`

        入力と結果の例:
            入力例: `mvd/n64 $p0@0 $d0`
            結果例: PDM 側のデータ配置を、DRAM や L2BM 側で都合のよい並びへ組み替えながら転送する。単純コピーではなく再レイアウトの意味を持つ。
        """
        return self._emit_mv(
            "mvd",
            size=size,
            src_operand=src_operand,
            dst_operand=dst_operand,
            tag=tag,
            nd=nd,
            priority=priority,
        )

    def nop(self) -> Self:
        """
        対応: MNCore2.md 7.2 `nop`

        4 サイクル何もしない PE 命令を追加する。`noforward` を含意する。

        注意:
        - `wait` は単独行ではなく、他の PE 命令と同時発行する前提。
        - `nop` / `noforward` は cycle 内外のどちらでも追加できる。

        生成構文:
            `nop`

        入力と結果の例:
            入力例: `nop`
            結果例: PE 側は 4 サイクル何も実行せず、forwarding 更新も止まる。L1BM 読み出し待ちや依存解消のための空き step として使える。
        """
        return self._emit_pe("nop")

    # --- 7.2 同期系命令 ---

    def noforward(self) -> Self:
        """
        対応: MNCore2.md 7.2 `noforward`

        forwarding path と折り返しレジスタを更新しない。

        注意:
        - `wait` は単独行ではなく、他の PE 命令と同時発行する前提。
        - `nop` / `noforward` は cycle 内外のどちらでも追加できる。

        生成構文:
            `noforward`

        入力と結果の例:
            入力例: `noforward`
            結果例: 同 step の PE 演算自体は可能だが、直後の forwarding 入力からは参照できない状態を明示する。
        """
        return self._emit_pe("noforward")

    def wait(self, *, tag: int) -> Self:
        """
        対応: MNCore2.md 7.2 `wait`

        指定 tag の MV 完了待ちを同時発行する。

        注意:
        - `wait` は単独行ではなく、他の PE 命令と同時発行する前提。
        - 停止対象は後続 PE 命令だけでなく、後続 MV 命令の発行にも及ぶ。
        - `nop` / `noforward` は cycle 内外のどちらでも追加できる。

        生成構文:
            `wait <tag>`

        入力と結果の例:
            入力例: 先に `mvp/n64i1 ...` を発行し、その後の PE step で `wait 1` を同時発行する。
            結果例: tag 1 の MV 完了までその PE step は先へ進まず、以降の PE 命令は転送済みデータを前提に実行できる。

        補足:
            manual では `wait` の単独発行は禁止されており、builder でも他の PE 命令と同じ cycle 行に置く想定で使う。
            また完了待ちの間は MV 側の後続発行も止まるため、タグ設計は命令列全体で考える必要がある。
        """
        if tag == 0:
            raise ValueError("wait tag 0 is invalid")
        return self._emit_pe(f"wait {tag}")

    def l2bmb(
        self, *, src_l2bm: L2BM, dst_l1bm: L1BM, l1bset: str | None = None
    ) -> Self:
        """
        対応: MNCore2.md 7.3 `l2bmb`

        L2BM から L1BM への放送命令を追加する。

        転送速度:
        - L2BM 読み出し: 16 長語/サイクル
        - 各 L1BM 書き込み: 16 長語/サイクル

        主な引数:
        - `src_l2bm`, `dst_l1bm`, `l1bset`

        注意:
        - L1B 部分集合指定や `@<l1badr>` はオペコード埋め込み情報として扱う。
        - `l2bmd` はオペランド方向で意味が変わるので引数名を分けている。

        生成構文:
            `l2bmb[@<l1bset>] <src_l2bm> <dst_l1bm>`

        入力と結果の例:
            入力例: `l2bmb@0-3 $lc0 $lb0`
            結果例: L2BM `$lc0` の内容を、指定した L1B 集合へ同じ形で放送する。後段の `l1bmp` や `l1bmd` で PE へ配る前の共有段として使う。
        """
        opcode = "l2bmb" + (f"@{l1bset}" if l1bset else "")
        return self._emit_pe(f"{opcode} {src_l2bm.render()} {dst_l1bm.render()}")

    # --- 7.3 L2BM 命令 ---

    def l2bmb2(
        self, *, src_l2bm: L2BM, dst_l1bm: L1BM, l1bset: str | None = None
    ) -> Self:
        """
        対応: MNCore2.md 7.3 `l2bmb2`

        L2BM から L1BM への分配放送命令を追加する。

        転送速度:
        - L2BM 読み出し: 64 長語/サイクル
        - 各 L1BM 書き込み: 16 長語/サイクル

        主な引数:
        - `src_l2bm`, `dst_l1bm`, `l1bset`

        注意:
        - L1B 部分集合指定や `@<l1badr>` はオペコード埋め込み情報として扱う。
        - `l2bmd` はオペランド方向で意味が変わるので引数名を分けている。

        生成構文:
            `l2bmb2[@<l1bset>] <src_l2bm> <dst_l1bm>`

        入力と結果の例:
            入力例: `l2bmb2@0-1 $lc0 $lb0`
            結果例: L2BM から L1BM へ 2 系統を意識した放送を行う。後段で 2 分配された PE グループへ対応付けたいときに使う。
        """
        opcode = "l2bmb2" + (f"@{l1bset}" if l1bset else "")
        return self._emit_pe(f"{opcode} {src_l2bm.render()} {dst_l1bm.render()}")

    @overload
    def l2bmd(
        self, *, src_l2bm: L2BM, dst_l1bm: L1BM, l1bset: str | None = None
    ) -> Self: ...

    @overload
    def l2bmd(self, *, src_l1bm: L1BM, dst_l2bm: L2BM) -> Self: ...

    def l2bmd(
        self,
        *,
        src_l2bm: L2BM | None = None,
        dst_l1bm: L1BM | None = None,
        src_l1bm: L1BM | None = None,
        dst_l2bm: L2BM | None = None,
        l1bset: str | None = None,
    ) -> Self:
        """
        対応: MNCore2.md 7.3 `l2bmd`

        L2BM -> L1BM の分配、または L1BM -> L2BM の結合を追加する。

        転送速度:
        - `L2BM -> L1BM` 分配: L2BM 読み出し 64 長語/サイクル、各 L1BM 書き込み 8 長語/サイクル
        - `L1BM -> L2BM` 結合: 各 L1BM 読み出し 8 長語/サイクル、L2BM 書き込み 64 長語/サイクル

        主な引数:
        - `src_l2bm`/`dst_l1bm` または `src_l1bm`/`dst_l2bm`

        注意:
        - L1B 部分集合指定や `@<l1badr>` はオペコード埋め込み情報として扱う。
        - `l2bmd` はオペランド方向で意味が変わるので引数名を分けている。

        生成構文:
            `l2bmd[@<l1bset>] $lc... $lb...`
            `l2bmd $lb... $lc...`

        入力と結果の例:
            入力例 1: `l2bmd@0-3 $lc0 $lb0`
            結果例 1: L2BM `$lc0` の内容を分配して L1BM `$lb0` 側へ展開する。
            入力例 2: `l2bmd $lb0 $lc0`
            結果例 2: 複数 L1BM からのデータを結合し、L2BM `$lc0` へまとめて書き戻す。
        """
        if (
            src_l2bm is not None
            and dst_l1bm is not None
            and src_l1bm is None
            and dst_l2bm is None
        ):
            opcode = "l2bmd" + (f"@{l1bset}" if l1bset else "")
            return self._emit_pe(f"{opcode} {src_l2bm.render()} {dst_l1bm.render()}")
        if (
            src_l1bm is not None
            and dst_l2bm is not None
            and src_l2bm is None
            and dst_l1bm is None
        ):
            return self._emit_pe(f"l2bmd {src_l1bm.render()} {dst_l2bm.render()}")
        raise TypeError("l2bmd expects either src_l2bm/dst_l1bm or src_l1bm/dst_l2bm")

    def l2bm_at(self, *, l1badr: int, src_l1bm: L1BM, dst_l2bm: L2BM) -> Self:
        """
        対応: MNCore2.md 7.3 `l2bm@<l1badr>`

        指定 L1B から L2BM への個別転送を追加する。

        転送速度:
        - 指定 L1BM 読み出し: 16 長語/サイクル
        - L2BM 書き込み: 16 長語/サイクル

        主な引数:
        - `l1badr`, `src_l1bm`, `dst_l2bm`

        注意:
        - L1B 部分集合指定や `@<l1badr>` はオペコード埋め込み情報として扱う。
        - `l2bmd` はオペランド方向で意味が変わるので引数名を分けている。

        生成構文:
            `l2bm@<l1badr> <src_l1bm> <dst_l2bm>`

        入力と結果の例:
            入力例: `l2bm@5 $lb0 $lc2`
            結果例: L1BM 側アドレス 5 を起点にした個別転送として、`$lb0` の一部を L2BM `$lc2` へ吸い上げる。
        """
        return self._emit_pe(f"l2bm@{l1badr} {src_l1bm.render()} {dst_l2bm.render()}")

    def l2bmr(
        self,
        *,
        rrn_opcode: RRNOpcode,
        src_l1bm: L1BM,
        dst_l2bm: L2BM,
        l1bset: str | None = None,
    ) -> Self:
        """
        対応: MNCore2.md 7.3 `l2bmr<rrn_opcode>`

        L1BM 群を縮約して L2BM に書く命令を追加する。

        転送速度:
        - 各 L1BM 読み出し: 16 長語/サイクル
        - L2BM 書き込み: 16 長語/サイクル

        主な引数:
        - `rrn_opcode`, `src_l1bm`, `dst_l2bm`, `l1bset`

        注意:
        - L1B 部分集合指定や `@<l1badr>` はオペコード埋め込み情報として扱う。
        - `l2bmd` はオペランド方向で意味が変わるので引数名を分けている。

        生成構文:
            `l2bmr<rrn_opcode>[@<l1bset>] <src_l1bm> <dst_l2bm>`

        入力と結果の例:
            入力例: `l2bmrffadd@0-3 $lb0 $lc1`
            結果例: L1BM 群に分かれている float 部分和を `ffadd` で縮約し、L2BM `$lc1` に 1 本の結果として残す。
        """
        opcode = f"l2bmr{rrn_opcode}" + (f"@{l1bset}" if l1bset else "")
        return self._emit_pe(f"{opcode} {src_l1bm.render()} {dst_l2bm.render()}")

    def l2bmr2(self, *, rrn_opcode: RRNOpcode, src_l1bm: L1BM, dst_l2bm: L2BM) -> Self:
        """
        対応: MNCore2.md 7.3 `l2bmr2<rrn_opcode>`

        結合縮約つき L1BM -> L2BM 命令を追加する。

        転送速度:
        - 各 L1BM 読み出し: 16 長語/サイクル
        - L2BM 書き込み: 64 長語/サイクル

        主な引数:
        - `rrn_opcode`, `src_l1bm`, `dst_l2bm`

        注意:
        - L1B 部分集合指定や `@<l1badr>` はオペコード埋め込み情報として扱う。
        - `l2bmd` はオペランド方向で意味が変わるので引数名を分けている。

        生成構文:
            `l2bmr2<rrn_opcode> <src_l1bm> <dst_l2bm>`

        入力と結果の例:
            入力例: `l2bmr2ffadd $lb0 $lc1`
            結果例: 2 系統の L1BM データを対にして縮約し、L2BM 1 箇所へ畳み込む。
        """
        return self._emit_pe(
            f"l2bmr2{rrn_opcode} {src_l1bm.render()} {dst_l2bm.render()}"
        )

    def l2bmi(self, *, l1bset: str, src_l1bm: L1BM, dst_l1bm: L1BM) -> Self:
        """
        対応: MNCore2.md 7.3 `l2bmi`

        L1BM 間マルチキャスト命令を追加する。

        転送速度:
        - 読み出し元 L1BM: 16 長語/サイクル
        - 書き込み先 L1BM: 16 長語/サイクル

        主な引数:
        - `l1bset`, `src_l1bm`, `dst_l1bm`

        注意:
        - L1B 部分集合指定や `@<l1badr>` はオペコード埋め込み情報として扱う。
        - `l2bmd` はオペランド方向で意味が変わるので引数名を分けている。

        生成構文:
            `l2bmi@<l1bset> <src_l1bm> <dst_l1bm>`

        入力と結果の例:
            入力例: `l2bmi@0,2 $lb0 $lb8`
            結果例: 指定集合の L1BM から L1BM へ多重配送し、PE へ出す前の中間共有バッファを作る。
        """
        return self._emit_pe(f"l2bmi@{l1bset} {src_l1bm.render()} {dst_l1bm.render()}")

    def l2bmdars(self, *, src_l2bm: L2BM, dst_dar: DAR) -> Self:
        """
        対応: MNCore2.md 7.3 `l2bmdars`

        DAR 書き込み準備命令を追加する。

        転送速度:
        - L2BM 読み出し: 64 長語/サイクル
        - DARBUF 書き込み: 128 アドレス語/サイクル

        主な引数:
        - `src_l2bm`, `dst_dar`

        注意:
        - L1B 部分集合指定や `@<l1badr>` はオペコード埋め込み情報として扱う。
        - `l2bmd` はオペランド方向で意味が変わるので引数名を分けている。

        生成構文:
            `l2bmdars <src_l2bm> <dst_dar>`

        入力と結果の例:
            入力例: `l2bmdars $lc0@.1 $dar0`
            結果例: L2BM から DAR 書き込み用のアドレス列を準備し、続く `l2bmdarw` で実 DAR へ反映できる状態にする。
        """
        return self._emit_pe(f"l2bmdars {src_l2bm.render()} {dst_dar.render()}")

    def l2bmdarw(self) -> Self:
        """
        対応: MNCore2.md 7.3 `l2bmdarw`

        DARBUF から DAR へアドレスを書き込む命令を追加する。

        転送速度:
        - DARBUF 読み出し: 1 アドレス語/サイクル
        - DAR 書き込み: 1 アドレス語/サイクル

        主な引数:
        - 引数なし

        注意:
        - L1B 部分集合指定や `@<l1badr>` はオペコード埋め込み情報として扱う。
        - `l2bmd` はオペランド方向で意味が変わるので引数名を分けている。

        生成構文:
            `l2bmdarw`

        入力と結果の例:
            入力例: `l2bmdars ...` の直後に `l2bmdarw`
            結果例: DARBUF に積まれていた更新内容が DAR に書き込まれ、以後の DRAM 間接参照に新しいアドレスが使われる。
        """
        return self._emit_pe("l2bmdarw")

    def l1bmp(self, *, src_l1bm: L1BM, dst_operands: Sequence[PeWriteOperand]) -> Self:
        """
        対応: MNCore2.md 7.4 `l1bmp`

        L1BM から全 64 PE への放送命令を追加する。

        転送速度:
        - 1 長語版: L1BM 側 1 長語/サイクル、PE 側 1 長語/サイクル
        - 2 長語版: L1BM 側 2 長語/サイクル、PE 側 2 長語/サイクル

        主な引数:
        - `src_l1bm`, `dst_operands`
        - `dst_operands` は複数の書き込み先を空白区切りで並べる。1 個以上必須。

        注意:
        - L1BM 側語長と PE 側語長が一致しないとゼロ埋めまたは切り捨てが起こる。
        - `l1bmd` は方向で意味が変わるため overload で分けている。

        生成構文:
            `l1bmp <src_l1bm> <dst...>`

        入力と結果の例:
            入力例: `l1bmp $lb0 $lm0 $ln0`
            結果例: L1BM `$lb0` の同一データを全 PE へ放送し、各 PE はそれぞれ LM0 / LM1 側に受け取る。
        """
        return self._emit_pe(
            f"l1bmp {src_l1bm.render()} {self._render_operands(dst_operands)}"
        )

    # --- 7.4 L1BM 命令 ---

    def l1bmm(self, *, src_l1bm: L1BM, dst_operands: Sequence[PeWriteOperand]) -> Self:
        """
        対応: MNCore2.md 7.4 `l1bmm`

        16x1 MAB モード放送命令を追加する。

        転送速度:
        - 1 長語版: L1BM 側 4 長語/サイクル、PE 側 1 長語/サイクル
        - 2 長語版: L1BM 側 8 長語/サイクル、PE 側 2 長語/サイクル

        主な引数:
        - `src_l1bm`, `dst_operands`
        - `dst_operands` は複数の書き込み先を空白区切りで並べる。1 個以上必須。

        注意:
        - L1BM 側語長と PE 側語長が一致しないとゼロ埋めまたは切り捨てが起こる。
        - `l1bmd` は方向で意味が変わるため overload で分けている。

        生成構文:
            `l1bmm <src_l1bm> <dst...>`

        入力と結果の例:
            入力例: `l1bmm $lb0 $lr0`
            結果例: 16x1 MAB モードで L1BM の内容を各 PE へ広げる。1 本の L1BM を縦方向の PE 配列へ見せたいときに使う。
        """
        return self._emit_pe(
            f"l1bmm {src_l1bm.render()} {self._render_operands(dst_operands)}"
        )

    def l1bmm_at(
        self, *, mabadr: int, src_operand: PeReadOperand, dst_l1bm: L1BM
    ) -> Self:
        """
        対応: MNCore2.md 7.4 `l1bmm@<mabadr>`

        PE -> L1BM 個別転送命令を追加する。

        転送速度:
        - 1 長語版: L1BM 側 4 長語/サイクル、PE 側 1 長語/サイクル
        - 2 長語版: L1BM 側 8 長語/サイクル、PE 側 2 長語/サイクル

        主な引数:
        - `mabadr`, `src_operand`, `dst_l1bm`
        - 書き込み方向では単一の L1BM を取る。

        注意:
        - L1BM 側語長と PE 側語長が一致しないとゼロ埋めまたは切り捨てが起こる。
        - `l1bmd` は方向で意味が変わるため overload で分けている。

        生成構文:
            `l1bmm@<mabadr> <src> <dst_l1bm>`

        入力と結果の例:
            入力例: `l1bmm@3 $lr0 $lb0`
            結果例: PE 側 `$lr0` の値を、MAB アドレス 3 を使う個別転送として L1BM `$lb0` に書き込む。
        """
        return self._emit_pe(
            f"l1bmm@{mabadr} {src_operand.render()} {dst_l1bm.render()}"
        )

    def l1bmr(
        self,
        *,
        rrn_opcode: RRNOpcode,
        src_operand: PeReadOperand,
        dst_l1bm: L1BM,
    ) -> Self:
        """
        対応: MNCore2.md 7.4 `l1bmr<rrn_opcode>`

        16x1 MAB モード縮約命令を追加する。

        転送速度:
        - 1 長語版: L1BM 側 4 長語/サイクル、PE 側 1 長語/サイクル
        - 2 長語版: L1BM 側 8 長語/サイクル、PE 側 2 長語/サイクル

        主な引数:
        - `rrn_opcode`, `src_operand`, `dst_l1bm`
        - 書き込み方向では単一の L1BM を取る。

        注意:
        - L1BM 側語長と PE 側語長が一致しないとゼロ埋めまたは切り捨てが起こる。
        - `l1bmd` は方向で意味が変わるため overload で分けている。

        生成構文:
            `l1bmr<rrn_opcode> <src> <dst_l1bm>`

        入力と結果の例:
            入力例: `l1bmrffadd $lr0 $lb0`
            結果例: 16x1 MAB 内の PE 値を `ffadd` で縮約し、L1BM `$lb0` に 1 本の集約結果として残す。
        """
        return self._emit_pe(
            f"l1bmr{rrn_opcode} {src_operand.render()} {dst_l1bm.render()}"
        )

    def l1bmm4(self, *, src_l1bm: L1BM, dst_operands: Sequence[PeWriteOperand]) -> Self:
        """
        対応: MNCore2.md 7.4 `l1bmm4`

        4x4 MAB モード放送命令を追加する。

        転送速度:
        - 1 長語版: L1BM 側 16 長語/サイクル、PE 側 1 長語/サイクル
        - 2 長語版: L1BM 側 32 長語/サイクル、PE 側 2 長語/サイクル

        主な引数:
        - `src_l1bm`, `dst_operands`
        - `dst_operands` は複数の書き込み先を空白区切りで並べる。1 個以上必須。

        注意:
        - L1BM 側語長と PE 側語長が一致しないとゼロ埋めまたは切り捨てが起こる。
        - `l1bmd` は方向で意味が変わるため overload で分けている。

        生成構文:
            `l1bmm4 <src_l1bm> <dst...>`

        入力と結果の例:
            入力例: `l1bmm4 $lb0 $lr0`
            結果例: 4x4 MAB モードで L1BM から PE へ放送する。4x4 タイル単位の並びを保ったまま展開したいときに使う。
        """
        return self._emit_pe(
            f"l1bmm4 {src_l1bm.render()} {self._render_operands(dst_operands)}"
        )

    def l1bmm4_at(
        self, *, mabadr: int, src_operand: PeReadOperand, dst_l1bm: L1BM
    ) -> Self:
        """
        対応: MNCore2.md 7.4 `l1bmm4@<mabadr>`

        4x4 MAB モード個別転送命令を追加する。

        転送速度:
        - 1 長語版: L1BM 側 16 長語/サイクル、PE 側 1 長語/サイクル
        - 2 長語版: L1BM 側 32 長語/サイクル、PE 側 2 長語/サイクル

        主な引数:
        - `mabadr`, `src_operand`, `dst_l1bm`
        - 書き込み方向では単一の L1BM を取る。

        注意:
        - L1BM 側語長と PE 側語長が一致しないとゼロ埋めまたは切り捨てが起こる。
        - `l1bmd` は方向で意味が変わるため overload で分けている。

        生成構文:
            `l1bmm4@<mabadr> <src> <dst_l1bm>`

        入力と結果の例:
            入力例: `l1bmm4@2 $lr0 $lb0`
            結果例: 4x4 タイル中の指定 MAB アドレスへ対応する PE 値だけを抜き出し、L1BM へ書く。
        """
        return self._emit_pe(
            f"l1bmm4@{mabadr} {src_operand.render()} {dst_l1bm.render()}"
        )

    def l1bmr4(
        self,
        *,
        rrn_opcode: RRNOpcode,
        src_operand: PeReadOperand,
        dst_l1bm: L1BM,
    ) -> Self:
        """
        対応: MNCore2.md 7.4 `l1bmr4<rrn_opcode>`

        4x4 MAB モード縮約命令を追加する。

        転送速度:
        - 1 長語版: L1BM 側 16 長語/サイクル、PE 側 1 長語/サイクル
        - 2 長語版: L1BM 側 32 長語/サイクル、PE 側 2 長語/サイクル

        主な引数:
        - `rrn_opcode`, `src_operand`, `dst_l1bm`
        - 書き込み方向では単一の L1BM を取る。

        注意:
        - L1BM 側語長と PE 側語長が一致しないとゼロ埋めまたは切り捨てが起こる。
        - `l1bmd` は方向で意味が変わるため overload で分けている。

        生成構文:
            `l1bmr4<rrn_opcode> <src> <dst_l1bm>`

        入力と結果の例:
            入力例: `l1bmr4ffadd $lr0 $lb0`
            結果例: 4x4 MAB 単位の PE 値を縮約し、L1BM `$lb0` にまとめる。4x4 放送の逆方向に相当する。
        """
        return self._emit_pe(
            f"l1bmr4{rrn_opcode} {src_operand.render()} {dst_l1bm.render()}"
        )

    @overload
    def l1bmd(
        self, *, src_l1bm: L1BM, dst_operands: Sequence[PeWriteOperand]
    ) -> Self: ...

    @overload
    def l1bmd(self, *, src_operand: PeReadOperand, dst_l1bm: L1BM) -> Self: ...

    def l1bmd(
        self,
        *,
        src_l1bm: L1BM | None = None,
        dst_operands: Sequence[PeWriteOperand] | None = None,
        src_operand: PeReadOperand | None = None,
        dst_l1bm: L1BM | None = None,
    ) -> Self:
        """
        対応: MNCore2.md 7.4 `l1bmd`

        L1BM -> PE の分配、または PE -> L1BM の結合を追加する。

        転送速度:
        - `L1BM -> PE` 分配: L1BM 側 64 長語/サイクル、PE 側 1 長語/サイクル
        - `PE -> L1BM` 結合: L1BM 側 64 長語/サイクル、PE 側 1 長語/サイクル

        主な引数:
        - `src_l1bm`/`dst_operands` または `src_operand`/`dst_l1bm`
        - `dst_operands` は複数の書き込み先を空白区切りで並べる。1 個以上必須。

        注意:
        - L1BM 側語長と PE 側語長が一致しないとゼロ埋めまたは切り捨てが起こる。
        - `l1bmd` は方向で意味が変わるため overload で分けている。

        生成構文:
            `l1bmd <src_l1bm> <dst...>`
            `l1bmd <src> <dst_l1bm>`

        入力と結果の例:
            入力例 1: `l1bmd $lb0 $lm0 $ln0`
            結果例 1: L1BM `$lb0` の内容を PE 側 LM0 / LM1 へ分配する。
            入力例 2: `l1bmd $lr0 $lb8`
            結果例 2: PE 側 `$lr0` の値を結合し、L1BM `$lb8` へ書き戻す。

        補足:
            tutorial では LM0 から LM1 へコピーした値が 2 step 後に観測できる例があり、実機上の待機サイクルを意識して使う必要がある。
        """
        if (
            src_l1bm is not None
            and dst_operands is not None
            and src_operand is None
            and dst_l1bm is None
        ):
            return self._emit_pe(
                f"l1bmd {src_l1bm.render()} {self._render_operands(dst_operands)}"
            )
        if (
            src_operand is not None
            and dst_l1bm is not None
            and src_l1bm is None
            and dst_operands is None
        ):
            return self._emit_pe(f"l1bmd {src_operand.render()} {dst_l1bm.render()}")
        raise TypeError(
            "l1bmd expects either src_l1bm/dst_operands or src_operand/dst_l1bm"
        )

    def dmfma(
        self,
        *,
        half_select: MAUHalfSelect,
        src_matrix: MatrixVector,
        src_x_operand: MauReadOperand,
        src_y_operand: MauReadOperand,
        dst_operands: Sequence[PeWriteOperand],
    ) -> Self:
        """
        対応: MNCore2.md 7.5 `dmfma`

        倍精度行列ベクトル積和 `Ax + y` を追加する。

        主な引数:
        - `half_select`, `src_matrix`, `src_x_operand`, `src_y_operand`, `dst_operands`
        - `dst_operands` は複数の書き込み先を空白区切りで並べる。1 個以上必須。

        注意:
        - 精度縮減や符号反転などの詳細オプションは、必要ならオペランド側や別 API で拡張する前提。
        - 倍精度の `u` / `d` は上下半分の PE を選ぶ。

        生成構文:
            `dmfma(u|d) $l(x|y) <src_x> <src_y> <dst...>`

        入力と結果の例:
            入力例: 行列 A=[[1,2],[3,4]]、ベクトル x=[10,20]、加算入力 y=[1,1] を考える。
            結果例: 出力は概念的に `A*x + y = [51, 111]` となる。実際には block-float 形式で PE 群へ分配して書き込まれる。

        補足:
            `half_select='u'/'d'` は上下どちらの半分の PE へ結果を出すかを表す。
        """
        return self._emit_pe(
            f"dmfma{half_select} {src_matrix.render()} {src_x_operand.render()} {src_y_operand.render()} {self._render_operands(dst_operands)}"
        )

    # --- 7.5 MAU 命令 ---

    def dmmul(
        self,
        *,
        half_select: MAUHalfSelect,
        src_matrix: MatrixVector,
        src_x_operand: MauReadOperand,
        dst_operands: Sequence[PeWriteOperand],
    ) -> Self:
        """
        対応: MNCore2.md 7.5 `dmmul`

        倍精度行列ベクトル積 `Ax` を追加する。

        主な引数:
        - `half_select`, `src_matrix`, `src_x_operand`, `dst_operands`
        - `dst_operands` は複数の書き込み先を空白区切りで並べる。1 個以上必須。

        注意:
        - 精度縮減や符号反転などの詳細オプションは、必要ならオペランド側や別 API で拡張する前提。
        - 倍精度の `u` / `d` は上下半分の PE を選ぶ。

        生成構文:
            `dmmul(u|d) $l(x|y) <src_x> <dst...>`

        入力と結果の例:
            入力例: 行列 A=[[1,2],[3,4]]、ベクトル x=[10,20] を考える。
            結果例: 出力は概念的に `A*x = [50, 110]` となる。`dmfma` の加算入力 y を 0 にしたものと考えると分かりやすい。
        """
        return self._emit_pe(
            f"dmmul{half_select} {src_matrix.render()} {src_x_operand.render()} {self._render_operands(dst_operands)}"
        )

    def fmfma(
        self,
        *,
        src_matrix: MatrixVector,
        src_x_operand: MauReadOperand,
        src_y_operand: MauReadOperand,
        dst_operands: Sequence[PeWriteOperand],
    ) -> Self:
        """
        対応: MNCore2.md 7.5 `fmfma`

        単精度 matvec FMA を追加する。

        主な引数:
        - `src_matrix`, `src_x_operand`, `src_y_operand`, `dst_operands`
        - `dst_operands` は複数の書き込み先を空白区切りで並べる。1 個以上必須。

        注意:
        - 精度縮減や符号反転などの詳細オプションは、必要ならオペランド側や別 API で拡張する前提。
        - 倍精度の `u` / `d` は上下半分の PE を選ぶ。

        生成構文:
            `fmfma $l(x|y) <src_x> <src_y> <dst...>`

        入力と結果の例:
            入力例: 単精度行列 A と x, y を与える。
            結果例: 各出力要素には `A*x + y` の単精度結果が入る。行列入力は block-float 系の前処理済みデータを前提にする。
        """
        return self._emit_pe(
            f"fmfma {src_matrix.render()} {src_x_operand.render()} {src_y_operand.render()} {self._render_operands(dst_operands)}"
        )

    def fmmul(
        self,
        *,
        src_matrix: MatrixVector,
        src_x_operand: MauReadOperand,
        dst_operands: Sequence[PeWriteOperand],
    ) -> Self:
        """
        対応: MNCore2.md 7.5 `fmmul`

        単精度 matvec MUL を追加する。

        主な引数:
        - `src_matrix`, `src_x_operand`, `dst_operands`
        - `dst_operands` は複数の書き込み先を空白区切りで並べる。1 個以上必須。

        注意:
        - 精度縮減や符号反転などの詳細オプションは、必要ならオペランド側や別 API で拡張する前提。
        - 倍精度の `u` / `d` は上下半分の PE を選ぶ。

        生成構文:
            `fmmul $l(x|y) <src_x> <dst...>`

        入力と結果の例:
            入力例: 単精度行列 A と x を与える。
            結果例: 各出力要素には `A*x` の単精度結果が入り、加算入力は持たない。
        """
        return self._emit_pe(
            f"fmmul {src_matrix.render()} {src_x_operand.render()} {self._render_operands(dst_operands)}"
        )

    def gmfma(
        self,
        *,
        src_matrix: MatrixVector,
        src_x_operand: MauReadOperand,
        src_y_operand: MauReadOperand,
        dst_operands: Sequence[PeWriteOperand],
    ) -> Self:
        """
        対応: MNCore2.md 7.5 `gmfma`

        疑似単精度 matvec FMA を追加する。

        主な引数:
        - `src_matrix`, `src_x_operand`, `src_y_operand`, `dst_operands`
        - `dst_operands` は複数の書き込み先を空白区切りで並べる。1 個以上必須。

        注意:
        - 精度縮減や符号反転などの詳細オプションは、必要ならオペランド側や別 API で拡張する前提。
        - 倍精度の `u` / `d` は上下半分の PE を選ぶ。

        生成構文:
            `gmfma $l(x|y) <src_x> <src_y> <dst...>`

        入力と結果の例:
            入力例: 疑似単精度行列 A と x, y を与える。
            結果例: `A*x + y` を疑似単精度系で評価した値が各 dst に出る。float と half の中間表現を意識したいときに使う。
        """
        return self._emit_pe(
            f"gmfma {src_matrix.render()} {src_x_operand.render()} {src_y_operand.render()} {self._render_operands(dst_operands)}"
        )

    def gmmul(
        self,
        *,
        src_matrix: MatrixVector,
        src_x_operand: MauReadOperand,
        dst_operands: Sequence[PeWriteOperand],
    ) -> Self:
        """
        対応: MNCore2.md 7.5 `gmmul`

        疑似単精度 matvec MUL を追加する。

        主な引数:
        - `src_matrix`, `src_x_operand`, `dst_operands`
        - `dst_operands` は複数の書き込み先を空白区切りで並べる。1 個以上必須。

        注意:
        - 精度縮減や符号反転などの詳細オプションは、必要ならオペランド側や別 API で拡張する前提。
        - 倍精度の `u` / `d` は上下半分の PE を選ぶ。

        生成構文:
            `gmmul $l(x|y) <src_x> <dst...>`

        入力と結果の例:
            入力例: 疑似単精度行列 A と x を与える。
            結果例: `A*x` を疑似単精度系で評価した値が各 dst に出る。
        """
        return self._emit_pe(
            f"gmmul {src_matrix.render()} {src_x_operand.render()} {self._render_operands(dst_operands)}"
        )

    def hmfma(
        self,
        *,
        src_matrix: MatrixVector,
        src_x_operand: MauReadOperand,
        src_y_operand: MauReadOperand,
        dst_operands: Sequence[PeWriteOperand],
    ) -> Self:
        """
        対応: MNCore2.md 7.5 `hmfma`

        半精度 matvec FMA を追加する。

        主な引数:
        - `src_matrix`, `src_x_operand`, `src_y_operand`, `dst_operands`
        - `dst_operands` は複数の書き込み先を空白区切りで並べる。1 個以上必須。

        注意:
        - 精度縮減や符号反転などの詳細オプションは、必要ならオペランド側や別 API で拡張する前提。
        - 倍精度の `u` / `d` は上下半分の PE を選ぶ。

        生成構文:
            `hmfma $l(x|y) <src_x> <src_y> <dst...>`

        入力と結果の例:
            入力例: 半精度行列 A と x, y を与える。
            結果例: `A*x + y` を半精度で評価した値が各 dst に出る。1 長語あたり 4 half を扱う点を意識すると読みやすい。
        """
        return self._emit_pe(
            f"hmfma {src_matrix.render()} {src_x_operand.render()} {src_y_operand.render()} {self._render_operands(dst_operands)}"
        )

    def hmmul(
        self,
        *,
        src_matrix: MatrixVector,
        src_x_operand: MauReadOperand,
        dst_operands: Sequence[PeWriteOperand],
    ) -> Self:
        """
        対応: MNCore2.md 7.5 `hmmul`

        半精度 matvec MUL を追加する。

        主な引数:
        - `src_matrix`, `src_x_operand`, `dst_operands`
        - `dst_operands` は複数の書き込み先を空白区切りで並べる。1 個以上必須。

        注意:
        - 精度縮減や符号反転などの詳細オプションは、必要ならオペランド側や別 API で拡張する前提。
        - 倍精度の `u` / `d` は上下半分の PE を選ぶ。

        生成構文:
            `hmmul $l(x|y) <src_x> <dst...>`

        入力と結果の例:
            入力例: 半精度行列 A と x を与える。
            結果例: `A*x` の半精度結果が各 dst に出る。
        """
        return self._emit_pe(
            f"hmmul {src_matrix.render()} {src_x_operand.render()} {self._render_operands(dst_operands)}"
        )

    def dvfma(
        self,
        *,
        half_select: MAUHalfSelect,
        src_x_operand: MauReadOperand,
        src_y_operand: MauReadOperand,
        src_z_operand: MauReadOperand,
        dst_operands: Sequence[PeWriteOperand],
    ) -> Self:
        """
        対応: MNCore2.md 7.5 `dvfma`

        倍精度 vector FMA を追加する。

        主な引数:
        - `half_select`, `src_x_operand`, `src_y_operand`, `src_z_operand`, `dst_operands`
        - `dst_operands` は複数の書き込み先を空白区切りで並べる。1 個以上必須。

        注意:
        - 精度縮減や符号反転などの詳細オプションは、必要ならオペランド側や別 API で拡張する前提。
        - 倍精度の `u` / `d` は上下半分の PE を選ぶ。

        生成構文:
            `dvfma(u|d) <src_x> <src_y> <src_z> <dst...>`

        入力と結果の例:
            入力例: x=(1.0, 5.0), y=(1.0, 9.0), z=(1.0, 1.0)
            結果例: 概念的には `(1*1+1, 5*9+1) = (2.0, 46.0)` が対応する dst に出る。倍精度版では 1 要素が 2 長語を使う。
        """
        return self._emit_pe(
            f"dvfma{half_select} {src_x_operand.render()} {src_y_operand.render()} {src_z_operand.render()} {self._render_operands(dst_operands)}"
        )

    def dvmul(
        self,
        *,
        half_select: MAUHalfSelect,
        src_x_operand: MauReadOperand,
        src_y_operand: MauReadOperand,
        dst_operands: Sequence[PeWriteOperand],
    ) -> Self:
        """
        対応: MNCore2.md 7.5 `dvmul`

        倍精度 vector MUL を追加する。

        主な引数:
        - `half_select`, `src_x_operand`, `src_y_operand`, `dst_operands`
        - `dst_operands` は複数の書き込み先を空白区切りで並べる。1 個以上必須。

        注意:
        - 精度縮減や符号反転などの詳細オプションは、必要ならオペランド側や別 API で拡張する前提。
        - 倍精度の `u` / `d` は上下半分の PE を選ぶ。

        生成構文:
            `dvmul(u|d) <src_x> <src_y> <dst...>`

        入力と結果の例:
            入力例: x=(1.0, 5.0), y=(1.0, 9.0)
            結果例: 概念的には `(1.0, 45.0)` が dst に出る。
        """
        return self._emit_pe(
            f"dvmul{half_select} {src_x_operand.render()} {src_y_operand.render()} {self._render_operands(dst_operands)}"
        )

    def dvadd(
        self,
        *,
        src_x_operand: MauReadOperand,
        src_y_operand: MauReadOperand,
        dst_operands: Sequence[PeWriteOperand],
    ) -> Self:
        """
        対応: MNCore2.md 7.5 `dvadd`

        倍精度 vector ADD を追加する。

        主な引数:
        - `src_x_operand`, `src_y_operand`, `dst_operands`
        - `dst_operands` は複数の書き込み先を空白区切りで並べる。1 個以上必須。

        注意:
        - 精度縮減や符号反転などの詳細オプションは、必要ならオペランド側や別 API で拡張する前提。
        - 倍精度の `u` / `d` は上下半分の PE を選ぶ。

        生成構文:
            `dvadd <src_x> <src_y> <dst...>`

        入力と結果の例:
            入力例: x=(1.0, 5.0), y=(1.0, 9.0)
            結果例: 概念的には `(2.0, 14.0)` が dst に出る。
        """
        return self._emit_pe(
            f"dvadd {src_x_operand.render()} {src_y_operand.render()} {self._render_operands(dst_operands)}"
        )

    def dvpassa(
        self, *, src_x_operand: MauReadOperand, dst_operands: Sequence[PeWriteOperand]
    ) -> Self:
        """
        対応: MNCore2.md 7.5 `dvpassa`

        倍精度 vector copy 相当命令を追加する。

        主な引数:
        - `src_x_operand`, `dst_operands`
        - `dst_operands` は複数の書き込み先を空白区切りで並べる。1 個以上必須。

        注意:
        - 精度縮減や符号反転などの詳細オプションは、必要ならオペランド側や別 API で拡張する前提。
        - 倍精度の `u` / `d` は上下半分の PE を選ぶ。

        生成構文:
            `dvpassa <src_x> <dst...>`

        入力と結果の例:
            入力例: x=(1.0, 5.0)
            結果例: dst には `(1.0, 5.0)` がそのまま出る。ベクトル経路の copy / 配線固定として使える。
        """
        return self._emit_pe(
            f"dvpassa {src_x_operand.render()} {self._render_operands(dst_operands)}"
        )

    def fvfma(
        self,
        *,
        src_x_operand: MauReadOperand,
        src_y_operand: MauReadOperand,
        src_z_operand: MauReadOperand,
        dst_operands: Sequence[PeWriteOperand],
    ) -> Self:
        """
        対応: MNCore2.md 7.5 `fvfma`

        単精度 vector FMA を追加する。

        主な引数:
        - `src_x_operand`, `src_y_operand`, `src_z_operand`, `dst_operands`
        - `dst_operands` は複数の書き込み先を空白区切りで並べる。1 個以上必須。

        注意:
        - 精度縮減や符号反転などの詳細オプションは、必要ならオペランド側や別 API で拡張する前提。
        - 倍精度の `u` / `d` は上下半分の PE を選ぶ。

        生成構文:
            `fvfma <src_x> <src_y> <src_z> <dst...>`

        入力と結果の例:
            入力例: tutorial では `(1.0, 5.0)`, `(1.0, 9.0)`, `(1.0, 1.0)` を与えて `fvfma` を実行する。
            結果例: `d getf` の出力は `(2, 46)` となり、要素ごとに `x*y+z` が計算されていることを確認できる。
        """
        return self._emit_pe(
            f"fvfma {src_x_operand.render()} {src_y_operand.render()} {src_z_operand.render()} {self._render_operands(dst_operands)}"
        )

    def fvmul(
        self,
        *,
        src_x_operand: MauReadOperand,
        src_y_operand: MauReadOperand,
        dst_operands: Sequence[PeWriteOperand],
    ) -> Self:
        """
        対応: MNCore2.md 7.5 `fvmul`

        単精度 vector MUL を追加する。

        主な引数:
        - `src_x_operand`, `src_y_operand`, `dst_operands`
        - `dst_operands` は複数の書き込み先を空白区切りで並べる。1 個以上必須。

        注意:
        - 精度縮減や符号反転などの詳細オプションは、必要ならオペランド側や別 API で拡張する前提。
        - 倍精度の `u` / `d` は上下半分の PE を選ぶ。

        生成構文:
            `fvmul <src_x> <src_y> <dst...>`

        入力と結果の例:
            入力例: x=(1.0, 5.0), y=(1.0, 9.0)
            結果例: dst には `(1.0, 45.0)` が出る。`fvfma` の加算入力 z を省いた形だと考えると追いやすい。
        """
        return self._emit_pe(
            f"fvmul {src_x_operand.render()} {src_y_operand.render()} {self._render_operands(dst_operands)}"
        )

    def fvadd(
        self,
        *,
        src_x_operand: MauReadOperand,
        src_y_operand: MauReadOperand,
        dst_operands: Sequence[PeWriteOperand],
    ) -> Self:
        """
        対応: MNCore2.md 7.5 `fvadd`

        単精度 vector ADD を追加する。

        主な引数:
        - `src_x_operand`, `src_y_operand`, `dst_operands`
        - `dst_operands` は複数の書き込み先を空白区切りで並べる。1 個以上必須。

        注意:
        - 精度縮減や符号反転などの詳細オプションは、必要ならオペランド側や別 API で拡張する前提。
        - 倍精度の `u` / `d` は上下半分の PE を選ぶ。

        生成構文:
            `fvadd <src_x> <src_y> <dst...>`

        入力と結果の例:
            入力例: x=(1.0, 5.0), y=(1.0, 9.0)
            結果例: dst には `(2.0, 14.0)` が出る。
        """
        return self._emit_pe(
            f"fvadd {src_x_operand.render()} {src_y_operand.render()} {self._render_operands(dst_operands)}"
        )

    def fvpassa(
        self, *, src_x_operand: MauReadOperand, dst_operands: Sequence[PeWriteOperand]
    ) -> Self:
        """
        対応: MNCore2.md 7.5 `fvpassa`

        単精度 vector copy 相当命令を追加する。

        主な引数:
        - `src_x_operand`, `dst_operands`
        - `dst_operands` は複数の書き込み先を空白区切りで並べる。1 個以上必須。

        注意:
        - 精度縮減や符号反転などの詳細オプションは、必要ならオペランド側や別 API で拡張する前提。
        - 倍精度の `u` / `d` は上下半分の PE を選ぶ。

        生成構文:
            `fvpassa <src_x> <dst...>`

        入力と結果の例:
            入力例: x=(1.0, 5.0)
            結果例: dst には `(1.0, 5.0)` がそのまま現れる。
        """
        return self._emit_pe(
            f"fvpassa {src_x_operand.render()} {self._render_operands(dst_operands)}"
        )

    def hvfma(
        self,
        *,
        src_x_operand: MauReadOperand,
        src_y_operand: MauReadOperand,
        src_z_operand: MauReadOperand,
        dst_operands: Sequence[PeWriteOperand],
    ) -> Self:
        """
        対応: MNCore2.md 7.5 `hvfma`

        半精度 vector FMA を追加する。

        主な引数:
        - `src_x_operand`, `src_y_operand`, `src_z_operand`, `dst_operands`
        - `dst_operands` は複数の書き込み先を空白区切りで並べる。1 個以上必須。

        注意:
        - 精度縮減や符号反転などの詳細オプションは、必要ならオペランド側や別 API で拡張する前提。
        - 倍精度の `u` / `d` は上下半分の PE を選ぶ。

        生成構文:
            `hvfma <src_x> <src_y> <src_z> <dst...>`

        入力と結果の例:
            入力例: x=(1,2,3,4), y=(10,10,10,10), z=(0,0,0,0)
            結果例: dst には `(10,20,30,40)` 相当の half ベクトルが出る。
        """
        return self._emit_pe(
            f"hvfma {src_x_operand.render()} {src_y_operand.render()} {src_z_operand.render()} {self._render_operands(dst_operands)}"
        )

    def hvmul(
        self,
        *,
        src_x_operand: MauReadOperand,
        src_y_operand: MauReadOperand,
        dst_operands: Sequence[PeWriteOperand],
    ) -> Self:
        """
        対応: MNCore2.md 7.5 `hvmul`

        半精度 vector MUL を追加する。

        主な引数:
        - `src_x_operand`, `src_y_operand`, `dst_operands`
        - `dst_operands` は複数の書き込み先を空白区切りで並べる。1 個以上必須。

        注意:
        - 精度縮減や符号反転などの詳細オプションは、必要ならオペランド側や別 API で拡張する前提。
        - 倍精度の `u` / `d` は上下半分の PE を選ぶ。

        生成構文:
            `hvmul <src_x> <src_y> <dst...>`

        入力と結果の例:
            入力例: x=(1,2,3,4), y=(10,10,10,10)
            結果例: dst には `(10,20,30,40)` が出る。
        """
        return self._emit_pe(
            f"hvmul {src_x_operand.render()} {src_y_operand.render()} {self._render_operands(dst_operands)}"
        )

    def hvadd(
        self,
        *,
        src_x_operand: MauReadOperand,
        src_y_operand: MauReadOperand,
        dst_operands: Sequence[PeWriteOperand],
    ) -> Self:
        """
        対応: MNCore2.md 7.5 `hvadd`

        半精度 vector ADD を追加する。

        主な引数:
        - `src_x_operand`, `src_y_operand`, `dst_operands`
        - `dst_operands` は複数の書き込み先を空白区切りで並べる。1 個以上必須。

        注意:
        - 精度縮減や符号反転などの詳細オプションは、必要ならオペランド側や別 API で拡張する前提。
        - 倍精度の `u` / `d` は上下半分の PE を選ぶ。

        生成構文:
            `hvadd <src_x> <src_y> <dst...>`

        入力と結果の例:
            入力例: x=(1,2,3,4), y=(10,10,10,10)
            結果例: dst には `(11,12,13,14)` が出る。
        """
        return self._emit_pe(
            f"hvadd {src_x_operand.render()} {src_y_operand.render()} {self._render_operands(dst_operands)}"
        )

    def hvpassa(
        self, *, src_x_operand: MauReadOperand, dst_operands: Sequence[PeWriteOperand]
    ) -> Self:
        """
        対応: MNCore2.md 7.5 `hvpassa`

        半精度 vector copy 相当命令を追加する。

        主な引数:
        - `src_x_operand`, `dst_operands`
        - `dst_operands` は複数の書き込み先を空白区切りで並べる。1 個以上必須。

        注意:
        - 精度縮減や符号反転などの詳細オプションは、必要ならオペランド側や別 API で拡張する前提。
        - 倍精度の `u` / `d` は上下半分の PE を選ぶ。

        生成構文:
            `hvpassa <src_x> <dst...>`

        入力と結果の例:
            入力例: x=(1,2,3,4)
            結果例: dst には `(1,2,3,4)` がそのまま出る。
        """
        return self._emit_pe(
            f"hvpassa {src_x_operand.render()} {self._render_operands(dst_operands)}"
        )

    def dmwrite(self, *, src_operand: PeReadOperand, dst_matrix: Matrix) -> Self:
        """
        対応: MNCore2.md 7.6 `dmwrite`

        倍精度データを行列レジスタへ書き込む。

        主な引数:
        - `src_operand`, `dst_matrix`

        注意:
        - 半精度版では `ll` 幅や偶数アラインなど追加制約がある。
        - 行列レジスタの物理表現差は `Matrix` / `MatrixVector` 側で表す。

        生成構文:
            `dmwrite <src> $l(x|y)<addr>`

        入力と結果の例:
            入力例: manual では LM 側に 1.0, 2.0, 3.0, 4.0 を置いた後で `dmwrite $aluf $lx0` を実行する。
            結果例: 続く `d getbd $lx0n0c0b0m0 4` では、行列レジスタ内に書き込まれた 1.0, 2.0, 3.0, 4.0 相当の値を確認できる。
        """
        return self._emit_pe(f"dmwrite {src_operand.render()} {dst_matrix.render()}")

    # --- 7.6 行列レジスタ書き込み命令 ---

    def fmwrite(self, *, src_operand: PeReadOperand, dst_matrix: Matrix) -> Self:
        """
        対応: MNCore2.md 7.6 `fmwrite`

        単精度データを行列レジスタへ書き込む。

        主な引数:
        - `src_operand`, `dst_matrix`

        注意:
        - 半精度版では `ll` 幅や偶数アラインなど追加制約がある。
        - 行列レジスタの物理表現差は `Matrix` / `MatrixVector` 側で表す。

        生成構文:
            `fmwrite <src> $l(x|y)<addr>`

        入力と結果の例:
            入力例: `fmwrite $lr0 $lx0`
            結果例: GRF / LM 側の単精度ベクトルを、後段の `fmfma` / `fmread` が参照する行列レジスタ行へ書き込む。
        """
        return self._emit_pe(f"fmwrite {src_operand.render()} {dst_matrix.render()}")

    def gmwrite(self, *, src_operand: PeReadOperand, dst_matrix: Matrix) -> Self:
        """
        対応: MNCore2.md 7.6 `gmwrite`

        疑似単精度データを行列レジスタへ書き込む。

        主な引数:
        - `src_operand`, `dst_matrix`

        注意:
        - 半精度版では `ll` 幅や偶数アラインなど追加制約がある。
        - 行列レジスタの物理表現差は `Matrix` / `MatrixVector` 側で表す。

        生成構文:
            `gmwrite <src> $l(x|y)<addr>`

        入力と結果の例:
            入力例: `gmwrite $lr0 $lx0`
            結果例: 疑似単精度形式のベクトルを行列レジスタへ書き込み、`gmfma` / `gmread` 系で再利用できるようにする。
        """
        return self._emit_pe(f"gmwrite {src_operand.render()} {dst_matrix.render()}")

    def hmwrite(self, *, src_operand: PeReadOperand, dst_matrix: Matrix) -> Self:
        """
        対応: MNCore2.md 7.6 `hmwrite`

        半精度データを行列レジスタへ書き込む。

        主な引数:
        - `src_operand`, `dst_matrix`

        注意:
        - 半精度版では `ll` 幅や偶数アラインなど追加制約がある。
        - 行列レジスタの物理表現差は `Matrix` / `MatrixVector` 側で表す。

        生成構文:
            `hmwrite <src> $l(x|y)<addr>`

        入力と結果の例:
            入力例: `hmwrite $lr0 $lx0`
            結果例: half ベクトルを行列レジスタへ並べ、`hmfma` / `hmread` で参照できるようにする。
        """
        self._validate_half_matrix(
            dst_matrix, opcode="hmwrite", require_double_long=False
        )
        return self._emit_pe(f"hmwrite {src_operand.render()} {dst_matrix.render()}")

    def dmread(
        self, *, src_matrix: Matrix, dst_operands: Sequence[PeWriteOperand]
    ) -> Self:
        """
        対応: MNCore2.md 7.7 `dmread`

        倍精度行列を転置読み出しする。

        主な引数:
        - `src_matrix`, `dst_operands`

        注意:
        - 半精度版では `ll` 幅や偶数アラインなど追加制約がある。
        - 行列レジスタの物理表現差は `Matrix` / `MatrixVector` 側で表す。

        生成構文:
            `dmread $l(x|y)<addr> <dst...>`

        入力と結果の例:
            入力例: `dmread $lx0 $ln0`
            結果例: 行列レジスタ `$lx0` を転置読み出しし、列方向のデータが dst ベクトルへ出る。manual では整数ビット列のまま読む用途にも使えると説明される。
        """
        return self._emit_pe(
            f"dmread {src_matrix.render()} {self._render_operands(dst_operands)}"
        )

    # --- 7.7 行列レジスタ転置読み出し命令 ---

    def fmread(
        self, *, src_matrix: Matrix, dst_operands: Sequence[PeWriteOperand]
    ) -> Self:
        """
        対応: MNCore2.md 7.7 `fmread`

        単精度行列を転置読み出しする。

        主な引数:
        - `src_matrix`, `dst_operands`

        注意:
        - 半精度版では `ll` 幅や偶数アラインなど追加制約がある。
        - 行列レジスタの物理表現差は `Matrix` / `MatrixVector` 側で表す。

        生成構文:
            `fmread $l(x|y)<addr> <dst...>`

        入力と結果の例:
            入力例: `fmread $lx0 $ln0`
            結果例: 単精度行列行を転置読み出しし、次のベクトル演算で使いやすい並びに戻す。
        """
        return self._emit_pe(
            f"fmread {src_matrix.render()} {self._render_operands(dst_operands)}"
        )

    def gmread(
        self, *, src_matrix: Matrix, dst_operands: Sequence[PeWriteOperand]
    ) -> Self:
        """
        対応: MNCore2.md 7.7 `gmread`

        疑似単精度行列を転置読み出しする。

        主な引数:
        - `src_matrix`, `dst_operands`

        注意:
        - 半精度版では `ll` 幅や偶数アラインなど追加制約がある。
        - 行列レジスタの物理表現差は `Matrix` / `MatrixVector` 側で表す。

        生成構文:
            `gmread $l(x|y)<addr> <dst...>`

        入力と結果の例:
            入力例: `gmread $lx0 $ln0`
            結果例: 疑似単精度行列を転置読み出しし、ベクトル経路へ戻す。
        """
        return self._emit_pe(
            f"gmread {src_matrix.render()} {self._render_operands(dst_operands)}"
        )

    def hmread(
        self, *, src_matrix: Matrix, dst_operands: Sequence[PeWriteOperand]
    ) -> Self:
        """
        対応: MNCore2.md 7.7 `hmread`

        半精度行列を転置読み出しする。

        主な引数:
        - `src_matrix`, `dst_operands`

        注意:
        - 半精度版では `ll` 幅や偶数アラインなど追加制約がある。
        - 行列レジスタの物理表現差は `Matrix` / `MatrixVector` 側で表す。

        生成構文:
            `hmread $l(x|y)<addr> <dst...>`

        入力と結果の例:
            入力例: `hmread $lx0 $ln0`
            結果例: half 行列を転置読み出しし、4 half / 長語の形で dst へ戻す。
        """
        self._validate_half_matrix(
            src_matrix, opcode="hmread", require_double_long=True
        )
        return self._emit_pe(
            f"hmread {src_matrix.render()} {self._render_operands(dst_operands)}"
        )

    def zero(self, *, dst_operands: Sequence[PeWriteOperand]) -> Self:
        """
        対応: MNCore2.md 7.8 `zero`

        all-0 を出力する。

        主な引数:
        - `dst_operands`

        注意:
        - `dst_operands` は複数の書き込み先を空白区切りで並べる。1 個以上必須。
        - precision 接頭辞や unsigned 指定は、命令のサポート範囲に合わせて呼び出し側で選ぶ。

        生成構文:
            `zero <dst...>`

        入力と結果の例:
            入力例: `zero $lr0`
            結果例: dst には常に all-0 が書かれる。初期化や条件付き書き込みの既定値づくりに使う。
        """
        return self._emit_pe(f"zero {self._render_operands(dst_operands)}")

    # --- 7.8 ALU 命令 ---

    def imm(
        self,
        *,
        payload: str | int,
        dst_operands: Sequence[PeWriteOperand],
        unsigned: bool = False,
    ) -> Self:
        """
        対応: MNCore2.md 7.8 `imm`

        即値 payload を出力する。

        主な引数:
        - `payload`, `dst_operands`, `unsigned`

        注意:
        - `unsigned=True` で `immu` を選ぶ。
        - precision 接頭辞や unsigned 指定は、命令のサポート範囲に合わせて呼び出し側で選ぶ。

        生成構文:
            `imm[u] <payload> <dst...>`

        入力と結果の例:
            入力例: `imm 0x42 $lr0`
            結果例: payload `0x42` を内部規則に従って 2 長語へ展開し、dst に即値として供給する。`unsigned=True` なら `immu` になる。
        """
        opcode = "immu" if unsigned else "imm"
        return self._emit_pe(
            f"{opcode} {payload} {self._render_operands(dst_operands)}"
        )

    def msl(
        self, *, src_operand: AluReadOperand, dst_operands: Sequence[PeWriteOperand]
    ) -> Self:
        """
        対応: MNCore2.md 7.8 `msl`

        PE 間循環左シフトを行う。

        主な引数:
        - `src_operand`, `dst_operands`

        注意:
        - `dst_operands` は複数の書き込み先を空白区切りで並べる。1 個以上必須。
        - precision 接頭辞や unsigned 指定は、命令のサポート範囲に合わせて呼び出し側で選ぶ。

        生成構文:
            `msl <src> <dst...>`

        入力と結果の例:
            入力例: PE0..3 が `(10,20,30,40)` を持つ状態で `msl` を実行する。
            結果例: 値は `0 -> 1 -> 2 -> 3 -> 0` の向きに循環し、PE0 には元の PE3 の値、PE1 には元の PE0 の値が入る。
        """
        return self._emit_alu_unary("msl", src_operand, dst_operands)

    def msr(
        self, *, src_operand: AluReadOperand, dst_operands: Sequence[PeWriteOperand]
    ) -> Self:
        """
        対応: MNCore2.md 7.8 `msr`

        PE 間循環右シフトを行う。

        主な引数:
        - `src_operand`, `dst_operands`

        注意:
        - `dst_operands` は複数の書き込み先を空白区切りで並べる。1 個以上必須。
        - precision 接頭辞や unsigned 指定は、命令のサポート範囲に合わせて呼び出し側で選ぶ。

        生成構文:
            `msr <src> <dst...>`

        入力と結果の例:
            入力例: PE0..3 が `(10,20,30,40)` を持つ状態で `msr` を実行する。
            結果例: `msl` と逆向きに循環し、PE0 には元の PE1 の値、PE3 には元の PE0 の値が入る。
        """
        return self._emit_alu_unary("msr", src_operand, dst_operands)

    def passa(
        self,
        *,
        precision: ALUAnyPrecision,
        src_operand: AluReadOperand,
        dst_operands: Sequence[PeWriteOperand],
    ) -> Self:
        """
        対応: MNCore2.md 7.8 `passa`

        入力をそのまま出力する。

        主な引数:
        - `precision`, `src_operand`, `dst_operands`

        注意:
        - `dst_operands` は複数の書き込み先を空白区切りで並べる。1 個以上必須。
        - precision 接頭辞や unsigned 指定は、命令のサポート範囲に合わせて呼び出し側で選ぶ。

        生成構文:
            `<prec>passa <src> <dst...>`

        入力と結果の例:
            入力例: `lpassa $lr0 $ln0`
            結果例: `$lr0` に 42 が入っていれば、dst 側にも同じ 42 が出る。tutorial では PE 番号を書き込む例の基本形として使われる。
        """
        return self._emit_alu_unary(f"{precision}passa", src_operand, dst_operands)

    def inc(
        self,
        *,
        precision: ALUIntPrecision,
        src_operand: AluReadOperand,
        dst_operands: Sequence[PeWriteOperand],
        unsigned: bool = False,
    ) -> Self:
        """
        対応: MNCore2.md 7.8 `inc`

        整数インクリメントを行う。

        主な引数:
        - `precision`, `src_operand`, `dst_operands`, `unsigned`

        注意:
        - `unsigned=True` で符号なし版を選ぶ。
        - precision 接頭辞や unsigned 指定は、命令のサポート範囲に合わせて呼び出し側で選ぶ。

        生成構文:
            `[u]<int-prec>inc <src> <dst...>`

        入力と結果の例:
            入力例: `linc $lr0 $ln0`
            結果例: `$lr0` が 41 なら dst には 42 が出る。`unsigned=True` のときはオーバーフロー判定の意味が変わる。
        """
        opcode = f"{'u' if unsigned else ''}{precision}inc"
        return self._emit_alu_unary(opcode, src_operand, dst_operands)

    def dec(
        self,
        *,
        precision: ALUIntPrecision,
        src_operand: AluReadOperand,
        dst_operands: Sequence[PeWriteOperand],
        unsigned: bool = False,
    ) -> Self:
        """
        対応: MNCore2.md 7.8 `dec`

        整数デクリメントを行う。

        主な引数:
        - `precision`, `src_operand`, `dst_operands`, `unsigned`

        注意:
        - `unsigned=True` で符号なし版を選ぶ。
        - precision 接頭辞や unsigned 指定は、命令のサポート範囲に合わせて呼び出し側で選ぶ。

        生成構文:
            `[u]<int-prec>dec <src> <dst...>`

        入力と結果の例:
            入力例: `ldec $lr0 $ln0`
            結果例: `$lr0` が 42 なら dst には 41 が出る。
        """
        opcode = f"{'u' if unsigned else ''}{precision}dec"
        return self._emit_alu_unary(opcode, src_operand, dst_operands)

    def not_(
        self,
        *,
        precision: ALUIntPrecision,
        src_operand: AluReadOperand,
        dst_operands: Sequence[PeWriteOperand],
    ) -> Self:
        """
        対応: MNCore2.md 7.8 `not`

        整数ビット反転を行う。

        主な引数:
        - `precision`, `src_operand`, `dst_operands`

        注意:
        - `dst_operands` は複数の書き込み先を空白区切りで並べる。1 個以上必須。
        - precision 接頭辞や unsigned 指定は、命令のサポート範囲に合わせて呼び出し側で選ぶ。

        生成構文:
            `<int-prec>not <src> <dst...>`

        入力と結果の例:
            入力例: `snot $lr0 $ln0`
            結果例: half 精度相当で `$lr0` が `0x0000` なら、dst には `0xFFFF` が出る。
        """
        return self._emit_alu_unary(f"{precision}not", src_operand, dst_operands)

    def lnot(
        self,
        *,
        precision: ALUIntPrecision,
        src_operand: AluReadOperand,
        dst_operands: Sequence[PeWriteOperand],
    ) -> Self:
        """
        対応: MNCore2.md 7.8 `lnot`

        論理否定を行う。

        主な引数:
        - `precision`, `src_operand`, `dst_operands`

        注意:
        - `dst_operands` は複数の書き込み先を空白区切りで並べる。1 個以上必須。
        - precision 接頭辞や unsigned 指定は、命令のサポート範囲に合わせて呼び出し側で選ぶ。

        生成構文:
            `<int-prec>lnot <src> <dst...>`

        入力と結果の例:
            入力例: `slnot $lr0 $ln0`
            結果例: `$lr0` が 0 なら dst は 1、0 以外なら 0 になる。ビット反転ではなく真偽値化である点が `not` と違う。
        """
        return self._emit_alu_unary(f"{precision}lnot", src_operand, dst_operands)

    def rsqrt(
        self,
        *,
        precision: ALUFloatPrecision,
        src_operand: AluReadOperand,
        dst_operands: Sequence[PeWriteOperand],
    ) -> Self:
        """
        対応: MNCore2.md 7.8 `rsqrt`

        近似逆数平方根を計算する。

        主な引数:
        - `precision`, `src_operand`, `dst_operands`

        注意:
        - `dst_operands` は複数の書き込み先を空白区切りで並べる。1 個以上必須。
        - precision 接頭辞や unsigned 指定は、命令のサポート範囲に合わせて呼び出し側で選ぶ。

        生成構文:
            `<float-prec>rsqrt <src> <dst...>`

        入力と結果の例:
            入力例: `frsqrt $lr0 $ln0`
            結果例: `$lr0` が 4.0 なら、dst には概ね 0.5 に近い近似値が出る。
        """
        return self._emit_alu_unary(f"{precision}rsqrt", src_operand, dst_operands)

    def floor(
        self,
        *,
        precision: ALUFloatPrecision,
        src_operand: AluReadOperand,
        dst_operands: Sequence[PeWriteOperand],
    ) -> Self:
        """
        対応: MNCore2.md 7.8 `floor`

        floor 演算を行う。

        主な引数:
        - `precision`, `src_operand`, `dst_operands`

        注意:
        - `dst_operands` は複数の書き込み先を空白区切りで並べる。1 個以上必須。
        - precision 接頭辞や unsigned 指定は、命令のサポート範囲に合わせて呼び出し側で選ぶ。

        生成構文:
            `<float-prec>floor <src> <dst...>`

        入力と結果の例:
            入力例: `ffloor $lr0 $ln0`
            結果例: `$lr0` が 3.75 なら、dst には 3.0 が出る。
        """
        return self._emit_alu_unary(f"{precision}floor", src_operand, dst_operands)

    def ftoi(
        self,
        *,
        precision: ALUFloatPrecision,
        src_operand: AluReadOperand,
        dst_operands: Sequence[PeWriteOperand],
        unsigned: bool = False,
    ) -> Self:
        """
        対応: MNCore2.md 7.8 `ftoi`

        浮動小数点から整数へ変換する。

        主な引数:
        - `precision`, `src_operand`, `dst_operands`, `unsigned`

        注意:
        - 丸めや飽和の詳細は manual 第 4 章準拠。
        - precision 接頭辞や unsigned 指定は、命令のサポート範囲に合わせて呼び出し側で選ぶ。

        生成構文:
            `<float-prec>ftoi <src> <dst...>`

        入力と結果の例:
            入力例: `fftoi $lr0 $ln0`
            結果例: `$lr0` が 3.0 なら dst には整数 3 が出る。丸めや飽和の細部は manual 第 4 章を前提にする。
        """
        opcode = f"{precision}ftoi"
        if unsigned:
            opcode = f"u{opcode}"
        return self._emit_alu_unary(opcode, src_operand, dst_operands)

    def bfe(
        self, *, src_operand: AluReadOperand, dst_operands: Sequence[PeWriteOperand]
    ) -> Self:
        """
        対応: MNCore2.md 7.8 `bfe`

        half block float を拡張表現へ変換する。

        主な引数:
        - `src_operand`, `dst_operands`

        注意:
        - `dst_operands` は複数の書き込み先を空白区切りで並べる。1 個以上必須。
        - precision 接頭辞や unsigned 指定は、命令のサポート範囲に合わせて呼び出し側で選ぶ。

        生成構文:
            `hbfe <src> <dst...>`

        入力と結果の例:
            入力例: `hbfe $lm0 $ln0`
            結果例: half block float として格納された入力を、後段の通常 half 演算や debug 表示で扱いやすい extended 形式へ展開する。
        """
        return self._emit_alu_unary("hbfe", src_operand, dst_operands)

    def bfn(
        self,
        *,
        precision: ALUBfnPrecision,
        src_operand: AluReadOperand,
        dst_operands: Sequence[PeWriteOperand],
    ) -> Self:
        """
        対応: MNCore2.md 7.8 `bfn`

        ブロックフロート化を行う。

        主な引数:
        - `precision`, `src_operand`, `dst_operands`

        注意:
        - `dst_operands` は複数の書き込み先を空白区切りで並べる。1 個以上必須。
        - precision 接頭辞や unsigned 指定は、命令のサポート範囲に合わせて呼び出し側で選ぶ。

        生成構文:
            `<d|f|g|h>bfn <src> <dst...>`

        入力と結果の例:
            入力例: `fbfn $lr0 $ln0`
            結果例: 通常の float ベクトルを、MAU 行列入力向けの block-float 形式へ変換した値が dst に出る。
        """
        return self._emit_alu_unary(f"{precision}bfn", src_operand, dst_operands)

    def max(
        self,
        *,
        precision: ALUAnyPrecision,
        src_x_operand: AluReadOperand,
        src_y_operand: PeReadOperand,
        dst_operands: Sequence[PeWriteOperand],
        unsigned: bool = False,
    ) -> Self:
        """
        対応: MNCore2.md 7.8 `max`

        2 入力の最大値を返す。

        主な引数:
        - `precision`, `src_x_operand`, `src_y_operand`, `dst_operands`, `unsigned`

        注意:
        - 整数/浮動小数点の両系統に対応。
        - precision 接頭辞や unsigned 指定は、命令のサポート範囲に合わせて呼び出し側で選ぶ。

        生成構文:
            `[u]<prec>max <src_x> <src_y> <dst...>`

        入力と結果の例:
            入力例: `fmax $lr0 $ls0 $ln0`
            結果例: `src_x=2.0`, `src_y=5.0` なら dst には 5.0 が出る。
        """
        opcode = f"{'u' if unsigned else ''}{precision}max"
        return self._emit_alu_binary(opcode, src_x_operand, src_y_operand, dst_operands)

    def min(
        self,
        *,
        precision: ALUAnyPrecision,
        src_x_operand: AluReadOperand,
        src_y_operand: PeReadOperand,
        dst_operands: Sequence[PeWriteOperand],
        unsigned: bool = False,
    ) -> Self:
        """
        対応: MNCore2.md 7.8 `min`

        2 入力の最小値を返す。

        主な引数:
        - `precision`, `src_x_operand`, `src_y_operand`, `dst_operands`, `unsigned`

        注意:
        - 整数/浮動小数点の両系統に対応。
        - precision 接頭辞や unsigned 指定は、命令のサポート範囲に合わせて呼び出し側で選ぶ。

        生成構文:
            `[u]<prec>min <src_x> <src_y> <dst...>`

        入力と結果の例:
            入力例: `fmin $lr0 $ls0 $ln0`
            結果例: `src_x=2.0`, `src_y=5.0` なら dst には 2.0 が出る。
        """
        opcode = f"{'u' if unsigned else ''}{precision}min"
        return self._emit_alu_binary(opcode, src_x_operand, src_y_operand, dst_operands)

    def packbit(
        self,
        *,
        precision: ALUAnyPrecision,
        src_x_operand: AluReadOperand,
        src_y_operand: PeReadOperand,
        dst_operands: Sequence[PeWriteOperand],
    ) -> Self:
        """
        対応: MNCore2.md 7.8 `packbit`

        第 1 入力を左詰めし、第 2 入力の MSB を取り込む。

        主な引数:
        - `precision`, `src_x_operand`, `src_y_operand`, `dst_operands`

        注意:
        - `dst_operands` は複数の書き込み先を空白区切りで並べる。1 個以上必須。
        - precision 接頭辞や unsigned 指定は、命令のサポート範囲に合わせて呼び出し側で選ぶ。

        生成構文:
            `<prec>packbit <src_x> <src_y> <dst...>`

        入力と結果の例:
            入力例: 4bit の概念例で `src_x=1010`, `src_y` の MSB=1 とする。
            結果例: `src_x` を左詰めしつつ `src_y` の MSB を取り込み、概念的には `0101` のような packed 値になる。
        """
        return self._emit_alu_binary(
            f"{precision}packbit", src_x_operand, src_y_operand, dst_operands
        )

    def and_(
        self,
        *,
        precision: ALUIntPrecision,
        src_x_operand: AluReadOperand,
        src_y_operand: PeReadOperand,
        dst_operands: Sequence[PeWriteOperand],
    ) -> Self:
        """
        対応: MNCore2.md 7.8 `and`

        ビット論理積を計算する。

        主な引数:
        - `precision`, `src_x_operand`, `src_y_operand`, `dst_operands`

        注意:
        - `dst_operands` は複数の書き込み先を空白区切りで並べる。1 個以上必須。
        - precision 接頭辞や unsigned 指定は、命令のサポート範囲に合わせて呼び出し側で選ぶ。

        生成構文:
            `<int-prec>and <src_x> <src_y> <dst...>`

        入力と結果の例:
            入力例: `land $lr0 $ls0 $ln0`
            結果例: `0b1100 AND 0b1010 = 0b1000` が dst に出る。
        """
        return self._emit_alu_binary(
            f"{precision}and", src_x_operand, src_y_operand, dst_operands
        )

    def or_(
        self,
        *,
        precision: ALUIntPrecision,
        src_x_operand: AluReadOperand,
        src_y_operand: PeReadOperand,
        dst_operands: Sequence[PeWriteOperand],
    ) -> Self:
        """
        対応: MNCore2.md 7.8 `or`

        ビット論理和を計算する。

        主な引数:
        - `precision`, `src_x_operand`, `src_y_operand`, `dst_operands`

        注意:
        - `dst_operands` は複数の書き込み先を空白区切りで並べる。1 個以上必須。
        - precision 接頭辞や unsigned 指定は、命令のサポート範囲に合わせて呼び出し側で選ぶ。

        生成構文:
            `<int-prec>or <src_x> <src_y> <dst...>`

        入力と結果の例:
            入力例: `lor $lr0 $ls0 $ln0`
            結果例: `0b1100 OR 0b1010 = 0b1110` が dst に出る。
        """
        return self._emit_alu_binary(
            f"{precision}or", src_x_operand, src_y_operand, dst_operands
        )

    def xor(
        self,
        *,
        precision: ALUIntPrecision,
        src_x_operand: AluReadOperand,
        src_y_operand: PeReadOperand,
        dst_operands: Sequence[PeWriteOperand],
    ) -> Self:
        """
        対応: MNCore2.md 7.8 `xor`

        排他的論理和を計算する。

        主な引数:
        - `precision`, `src_x_operand`, `src_y_operand`, `dst_operands`

        注意:
        - `dst_operands` は複数の書き込み先を空白区切りで並べる。1 個以上必須。
        - precision 接頭辞や unsigned 指定は、命令のサポート範囲に合わせて呼び出し側で選ぶ。

        生成構文:
            `<int-prec>xor <src_x> <src_y> <dst...>`

        入力と結果の例:
            入力例: `lxor $lr0 $ls0 $ln0`
            結果例: `0b1100 XOR 0b1010 = 0b0110` が dst に出る。
        """
        return self._emit_alu_binary(
            f"{precision}xor", src_x_operand, src_y_operand, dst_operands
        )

    def add(
        self,
        *,
        precision: ALUIntPrecision,
        src_x_operand: AluReadOperand,
        src_y_operand: PeReadOperand,
        dst_operands: Sequence[PeWriteOperand],
        unsigned: bool = False,
    ) -> Self:
        """
        対応: MNCore2.md 7.8 `add`

        整数加算を行う。

        主な引数:
        - `precision`, `src_x_operand`, `src_y_operand`, `dst_operands`, `unsigned`

        注意:
        - `unsigned=True` で符号なし版を選ぶ。
        - precision 接頭辞や unsigned 指定は、命令のサポート範囲に合わせて呼び出し側で選ぶ。

        生成構文:
            `[u]<int-prec>add <src_x> <src_y> <dst...>`

        入力と結果の例:
            入力例: `ladd $lr0 $ls0 $ln0`
            結果例: `src_x=2`, `src_y=5` なら dst には 7 が出る。
        """
        opcode = f"{'u' if unsigned else ''}{precision}add"
        return self._emit_alu_binary(opcode, src_x_operand, src_y_operand, dst_operands)

    def sub(
        self,
        *,
        precision: ALUIntPrecision,
        src_x_operand: AluReadOperand,
        src_y_operand: PeReadOperand,
        dst_operands: Sequence[PeWriteOperand],
        unsigned: bool = False,
    ) -> Self:
        """
        対応: MNCore2.md 7.8 `sub`

        整数減算を行う。

        主な引数:
        - `precision`, `src_x_operand`, `src_y_operand`, `dst_operands`, `unsigned`

        注意:
        - `unsigned=True` で符号なし版を選ぶ。
        - precision 接頭辞や unsigned 指定は、命令のサポート範囲に合わせて呼び出し側で選ぶ。

        生成構文:
            `[u]<int-prec>sub <src_x> <src_y> <dst...>`

        入力と結果の例:
            入力例: `lsub $lr0 $ls0 $ln0`
            結果例: `src_x=9`, `src_y=4` なら dst には 5 が出る。
        """
        opcode = f"{'u' if unsigned else ''}{precision}sub"
        return self._emit_alu_binary(opcode, src_x_operand, src_y_operand, dst_operands)

    def lsl(
        self,
        *,
        precision: ALUIntPrecision,
        src_x_operand: AluReadOperand,
        src_y_operand: PeReadOperand,
        dst_operands: Sequence[PeWriteOperand],
    ) -> Self:
        """
        対応: MNCore2.md 7.8 `lsl`

        左シフトを行う。

        主な引数:
        - `precision`, `src_x_operand`, `src_y_operand`, `dst_operands`

        注意:
        - `dst_operands` は複数の書き込み先を空白区切りで並べる。1 個以上必須。
        - precision 接頭辞や unsigned 指定は、命令のサポート範囲に合わせて呼び出し側で選ぶ。

        生成構文:
            `<int-prec>lsl <src_x> <src_y> <dst...>`

        入力と結果の例:
            入力例: `llsl $lr0 $ls0 $ln0`
            結果例: `src_x=3`, `src_y=2` なら dst には `3 << 2 = 12` が出る。
        """
        return self._emit_alu_binary(
            f"{precision}lsl", src_x_operand, src_y_operand, dst_operands
        )

    def lsr(
        self,
        *,
        precision: ALUIntPrecision,
        src_x_operand: AluReadOperand,
        src_y_operand: PeReadOperand,
        dst_operands: Sequence[PeWriteOperand],
        unsigned: bool = False,
    ) -> Self:
        """
        対応: MNCore2.md 7.8 `lsr`

        右シフトを行う。

        主な引数:
        - `precision`, `src_x_operand`, `src_y_operand`, `dst_operands`, `unsigned`

        注意:
        - `unsigned=True` で論理右シフト寄りの扱いになる。
        - precision 接頭辞や unsigned 指定は、命令のサポート範囲に合わせて呼び出し側で選ぶ。

        生成構文:
            `[u]<int-prec>lsr <src_x> <src_y> <dst...>`

        入力と結果の例:
            入力例: `ulsr $lr0 $ls0 $ln0`
            結果例: `src_x=16`, `src_y=2` なら dst には 4 が出る。
        """
        opcode = f"{'u' if unsigned else ''}{precision}lsr"
        return self._emit_alu_binary(opcode, src_x_operand, src_y_operand, dst_operands)

    def bsl(
        self,
        *,
        precision: ALUIntPrecision,
        src_x_operand: AluReadOperand,
        src_y_operand: PeReadOperand,
        dst_operands: Sequence[PeWriteOperand],
    ) -> Self:
        """
        対応: MNCore2.md 7.8 `bsl`

        循環左シフトを行う。

        主な引数:
        - `precision`, `src_x_operand`, `src_y_operand`, `dst_operands`

        注意:
        - `dst_operands` は複数の書き込み先を空白区切りで並べる。1 個以上必須。
        - precision 接頭辞や unsigned 指定は、命令のサポート範囲に合わせて呼び出し側で選ぶ。

        生成構文:
            `<int-prec>bsl <src_x> <src_y> <dst...>`

        入力と結果の例:
            入力例: `lbsl $lr0 $ls0 $ln0`
            結果例: `src_x=0b1001`, `src_y=1` なら、ビットは循環左シフトされて `0b0011` 相当になる。
        """
        return self._emit_alu_binary(
            f"{precision}bsl", src_x_operand, src_y_operand, dst_operands
        )

    def bsr(
        self,
        *,
        precision: ALUIntPrecision,
        src_x_operand: AluReadOperand,
        src_y_operand: PeReadOperand,
        dst_operands: Sequence[PeWriteOperand],
    ) -> Self:
        """
        対応: MNCore2.md 7.8 `bsr`

        循環右シフトを行う。

        主な引数:
        - `precision`, `src_x_operand`, `src_y_operand`, `dst_operands`

        注意:
        - `dst_operands` は複数の書き込み先を空白区切りで並べる。1 個以上必須。
        - precision 接頭辞や unsigned 指定は、命令のサポート範囲に合わせて呼び出し側で選ぶ。

        生成構文:
            `<int-prec>bsr <src_x> <src_y> <dst...>`

        入力と結果の例:
            入力例: `lbsr $lr0 $ls0 $ln0`
            結果例: `src_x=0b1001`, `src_y=1` なら、ビットは循環右シフトされて `0b1100` 相当になる。
        """
        return self._emit_alu_binary(
            f"{precision}bsr", src_x_operand, src_y_operand, dst_operands
        )

    def relu(
        self,
        *,
        precision: ALUFloatPrecision,
        src_x_operand: AluReadOperand,
        src_y_operand: PeReadOperand,
        dst_operands: Sequence[PeWriteOperand],
    ) -> Self:
        """
        対応: MNCore2.md 7.8 `relu`

        `src_x` の符号で `src_y` を通すか `-0` にする。

        主な引数:
        - `precision`, `src_x_operand`, `src_y_operand`, `dst_operands`

        注意:
        - `dst_operands` は複数の書き込み先を空白区切りで並べる。1 個以上必須。
        - precision 接頭辞や unsigned 指定は、命令のサポート範囲に合わせて呼び出し側で選ぶ。

        生成構文:
            `<float-prec>relu <src_x> <src_y> <dst...>`

        入力と結果の例:
            入力例: `frelu $lr0 $ls0 $ln0`
            結果例: `src_x=-1.0`, `src_y=5.0` なら dst は `-0`、`src_x=+1.0` なら dst は 5.0 になる。`src_x` は条件、`src_y` が実データである。
        """
        return self._emit_alu_binary(
            f"{precision}relu", src_x_operand, src_y_operand, dst_operands
        )

    def relu0(
        self,
        *,
        precision: ALUFloatPrecision,
        src_x_operand: AluReadOperand,
        src_y_operand: PeReadOperand,
        dst_operands: Sequence[PeWriteOperand],
    ) -> Self:
        """
        対応: MNCore2.md 7.8 `relu0`

        `relu` と同義の別名命令を追加する。

        主な引数:
        - `precision`, `src_x_operand`, `src_y_operand`, `dst_operands`

        注意:
        - `dst_operands` は複数の書き込み先を空白区切りで並べる。1 個以上必須。
        - precision 接頭辞や unsigned 指定は、命令のサポート範囲に合わせて呼び出し側で選ぶ。

        生成構文:
            `<float-prec>relu0 <src_x> <src_y> <dst...>`

        入力と結果の例:
            入力例: `frelu0 $lr0 $ls0 $ln0`
            結果例: 振る舞いは `relu` と同じで、`src_x` が負なら `-0`、非負なら `src_y` が通る。
        """
        return self._emit_alu_binary(
            f"{precision}relu0", src_x_operand, src_y_operand, dst_operands
        )

    def relu1(
        self,
        *,
        precision: ALUFloatPrecision,
        src_x_operand: AluReadOperand,
        src_y_operand: PeReadOperand,
        dst_operands: Sequence[PeWriteOperand],
    ) -> Self:
        """
        対応: MNCore2.md 7.8 `relu1`

        `src_x` の第 2 MSB を条件に `src_y` を通す。

        主な引数:
        - `precision`, `src_x_operand`, `src_y_operand`, `dst_operands`

        注意:
        - `dst_operands` は複数の書き込み先を空白区切りで並べる。1 個以上必須。
        - precision 接頭辞や unsigned 指定は、命令のサポート範囲に合わせて呼び出し側で選ぶ。

        生成構文:
            `<float-prec>relu1 <src_x> <src_y> <dst...>`

        入力と結果の例:
            入力例: `frelu1 $lr0 $ls0 $ln0`
            結果例: `src_x` の第 2 MSB が 0 側なら `src_y` を通し、1 側なら `-0` にする。符号ビットではなく別条件ビットを使いたいときに選ぶ。
        """
        return self._emit_alu_binary(
            f"{precision}relu1", src_x_operand, src_y_operand, dst_operands
        )

    def relu2(
        self,
        *,
        precision: ALUFloatPrecision,
        src_x_operand: AluReadOperand,
        src_y_operand: PeReadOperand,
        dst_operands: Sequence[PeWriteOperand],
    ) -> Self:
        """
        対応: MNCore2.md 7.8 `relu2`

        `src_x` の第 3 MSB を条件に `src_y` を通す。

        主な引数:
        - `precision`, `src_x_operand`, `src_y_operand`, `dst_operands`

        注意:
        - `dst_operands` は複数の書き込み先を空白区切りで並べる。1 個以上必須。
        - precision 接頭辞や unsigned 指定は、命令のサポート範囲に合わせて呼び出し側で選ぶ。

        生成構文:
            `<float-prec>relu2 <src_x> <src_y> <dst...>`

        入力と結果の例:
            入力例: `frelu2 $lr0 $ls0 $ln0`
            結果例: `src_x` の第 3 MSB を条件として `src_y` を通すか `-0` にする。
        """
        return self._emit_alu_binary(
            f"{precision}relu2", src_x_operand, src_y_operand, dst_operands
        )

    def relu3(
        self,
        *,
        precision: ALUFloatPrecision,
        src_x_operand: AluReadOperand,
        src_y_operand: PeReadOperand,
        dst_operands: Sequence[PeWriteOperand],
    ) -> Self:
        """
        対応: MNCore2.md 7.8 `relu3`

        `src_x` の第 4 MSB を条件に `src_y` を通す。

        主な引数:
        - `precision`, `src_x_operand`, `src_y_operand`, `dst_operands`

        注意:
        - `dst_operands` は複数の書き込み先を空白区切りで並べる。1 個以上必須。
        - precision 接頭辞や unsigned 指定は、命令のサポート範囲に合わせて呼び出し側で選ぶ。

        生成構文:
            `<float-prec>relu3 <src_x> <src_y> <dst...>`

        入力と結果の例:
            入力例: `frelu3 $lr0 $ls0 $ln0`
            結果例: `src_x` の第 4 MSB を条件として `src_y` を通すか `-0` にする。
        """
        return self._emit_alu_binary(
            f"{precision}relu3", src_x_operand, src_y_operand, dst_operands
        )

    def lrelud(
        self,
        *,
        precision: ALUFloatPrecision,
        src_x_operand: AluReadOperand,
        src_y_operand: PeReadOperand,
        dst_operands: Sequence[PeWriteOperand],
    ) -> Self:
        """
        対応: MNCore2.md 7.8 `lrelud`

        負側を 1/2 に落とす Leaky ReLU 系命令を追加する。

        主な引数:
        - `precision`, `src_x_operand`, `src_y_operand`, `dst_operands`

        注意:
        - `dst_operands` は複数の書き込み先を空白区切りで並べる。1 個以上必須。
        - precision 接頭辞や unsigned 指定は、命令のサポート範囲に合わせて呼び出し側で選ぶ。

        生成構文:
            `<float-prec>lrelud <src_x> <src_y> <dst...>`

        入力と結果の例:
            入力例: `flrelud $lr0 $ls0 $ln0`
            結果例: `src_x=-1.0`, `src_y=8.0` なら dst は 4.0、`src_x=+1.0` なら 8.0 になる。
        """
        return self._emit_alu_binary(
            f"{precision}lrelud", src_x_operand, src_y_operand, dst_operands
        )

    def lreluo(
        self,
        *,
        precision: ALUFloatPrecision,
        src_x_operand: AluReadOperand,
        src_y_operand: PeReadOperand,
        dst_operands: Sequence[PeWriteOperand],
    ) -> Self:
        """
        対応: MNCore2.md 7.8 `lreluo`

        負側を 1/8 に落とす Leaky ReLU 系命令を追加する。

        主な引数:
        - `precision`, `src_x_operand`, `src_y_operand`, `dst_operands`

        注意:
        - `dst_operands` は複数の書き込み先を空白区切りで並べる。1 個以上必須。
        - precision 接頭辞や unsigned 指定は、命令のサポート範囲に合わせて呼び出し側で選ぶ。

        生成構文:
            `<float-prec>lreluo <src_x> <src_y> <dst...>`

        入力と結果の例:
            入力例: `flreluo $lr0 $ls0 $ln0`
            結果例: `src_x=-1.0`, `src_y=8.0` なら dst は 1.0、`src_x=+1.0` なら 8.0 になる。
        """
        return self._emit_alu_binary(
            f"{precision}lreluo", src_x_operand, src_y_operand, dst_operands
        )

    def ilrelud(
        self,
        *,
        precision: ALUFloatPrecision,
        src_x_operand: AluReadOperand,
        src_y_operand: PeReadOperand,
        dst_operands: Sequence[PeWriteOperand],
    ) -> Self:
        """
        対応: MNCore2.md 7.8 `ilrelud`

        指数操作系の Leaky ReLU 変形命令を追加する。

        主な引数:
        - `precision`, `src_x_operand`, `src_y_operand`, `dst_operands`

        注意:
        - `dst_operands` は複数の書き込み先を空白区切りで並べる。1 個以上必須。
        - precision 接頭辞や unsigned 指定は、命令のサポート範囲に合わせて呼び出し側で選ぶ。

        生成構文:
            `<float-prec>ilrelud <src_x> <src_y> <dst...>`

        入力と結果の例:
            入力例: `filrelud $lr0 $ls0 $ln0`
            結果例: `src_x` が負の要素だけに対して、通常の算術除算ではなく `src_y` の指数部を 1 段操作した変形 Leaky ReLU 結果が出る。非負側は `src_y` がそのまま通る。

        補足:
            manual でも「指数操作として理解する」とされており、`lrelud` と同一の数値規則ではない。
        """
        return self._emit_alu_binary(
            f"{precision}ilrelud", src_x_operand, src_y_operand, dst_operands
        )
