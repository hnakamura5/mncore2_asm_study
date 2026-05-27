# MN-Core 2 Assembler wrapper

MN-Core 2 の VSM テキストを Python から組み立てるための小さなラッパ。

## 方針

- 命令列は `InstructionBuilder` が保持する
- 同一サイクルで発行する PE 命令は `cycle()` context manager に積む
- オペランドは `PDM`, `L2BM`, `LM0`, `GRF0` などメモリ種別ごとの class で区別する
- debug target も `DebugLM0Ref`, `DebugTRegRef`, `DebugMatrixRef` など専用 class で区別する
- 方向が分かれる命令は `src_*` / `dst_*` を分けた引数名にしている
- 複数のオペランド種別を取る命令では `typing.overload` を使って主要な型分岐を付けている
- `builder.statements()` から `InstructionStatement` / `DebugStatement` / `PseudoStatement` / `CycleStatement` を型で判別できる
- debug 文と疑似構文は、レンダリング時に用途を示すコメントを自動で付ける
- 各 builder メソッドには `MNCore2.md` の対応節を踏まえた日本語 docstring を付けている

メモリ種別の整理:

- `PDM` / `DRAM` / `DAR` は MV 系の上位メモリと間接参照表を表す
- `L2BM` / `L1BM` は放送・分配・縮約の中継メモリを表す
- `LM0` / `LM1` / `GRF0` / `GRF1` / `TReg` は PE ローカル資源を表す
- `Matrix` / `MatrixVector` は MAU の行列レジスタ面を表す

制約の扱い:

- wrapper は構文と型の整理を主目的とし、MV 多重発行制約、PE ハザード待ち、並列実行条件までは自動検証しない
- ALU/MAU の精度縮減やマスクフラグ規則も、builder は命令文字列を作るだけで意味検証はしない

現在入っている主な guard:

- `wait(tag=0)` は `ValueError` にする
- `Nowrite()` は単独の dst にしか置けない
- ALU の固定値入力は第 1 入力だけに許可する
- `MREADF` は ALU の第 1 入力以外では `ValueError` にする
- `hmread` は `Matrix.half_read(...)` 相当の `ll` 幅かつ偶数 addr を要求する
- `LM0/LM1/GRF0/GRF1.auto(..., adri=...)` は `vector=True` を必須にする

## 例

```python
from asm_wrapper import (
    DebugDataType,
    DebugLM0Ref,
    DebugScope,
    InstructionBuilder,
    L1BM,
    LM0,
    MatrixBank,
    MatrixVector,
    PEID,
)

builder = InstructionBuilder()
builder.mvnop()

with builder.cycle():
    builder.passa(
        precision="l",
        src_operand=PEID,
        dst_operands=[LM0.auto(0, vector=True)],
    )
    builder.dmmul(
        half_select="u",
        src_matrix=MatrixVector(MatrixBank.X),
        src_x_operand=LM0.auto(0, vector=True),
        dst_operands=[LM0.auto(8, vector=True)],
    )

builder.debug_get(
    target_memory=DebugLM0Ref(0, scope=DebugScope(group=0, l2b=0, l1b=0, mab=0, pe=0)),
    num_words=1,
    dtype=DebugDataType.DOUBLE,
)
builder.mask(mask_index=0)
builder.nop_repeat(repeat=2)

# flat mode と `/1000` 派生表記も helper で書ける。
with builder.cycle():
    builder.l1bmm(
        src_l1bm=L1BM(addr=0),
        dst_operands=[LM0.auto(4, vector=True, cycle_mask="1000")],
    )

print(builder.to_source())

for statement in builder.statements():
    print(type(statement).__name__, statement.kind)
```

出力:

```text
mvnop
lpassa $peid $lm0v; dmmulu $lx $lm0v $lm8v
d getd $lm0n0c0b0m0p0 1  # debug: emulator-only memory dump
mask 0  # pseudo: tutorial helper syntax
nop/2  # pseudo: assembler repetition shorthand
l1bmm $lb0 $lm4v/1000
```

型の例:

```text
InstructionStatement instruction
CycleStatement cycle
DebugStatement debug
PseudoStatement pseudo
PseudoStatement pseudo
```

## 命名上の注意

- Python の予約語にぶつかる命令は `not_`, `and_`, `or_` にしている
- `l2bm@<l1badr>` は `l2bm_at(...)`
- `l1bmm@<mabadr>` は `l1bmm_at(...)`
- `l1bmm4@<mabadr>` は `l1bmm4_at(...)`
- `nop/2` は `nop_repeat(repeat=2)`
- flat mode は `LM0.flat([a0, a1, a2, a3])` や `GRF0.flat([...])` の helper を持つ
- 半精度行列アクセスは `Matrix.half(...)` と `Matrix.half_read(...)` で安全側に組み立てられる
- `/1000` のような派生表記は `cycle_mask="1000"` で付けられる
- raw な疑似構文が必要なら `pseudo_raw(...)` を使う

## 現時点の制限

- debug メモリは `DebugMemoryRef` を追加したが、行列レジスタなど一部の派生記法は必要に応じて raw string も使える
- debug メモリは代表的な対象を class 化したが、資料未確認の token は `DebugMemoryRef` で raw に保持できる
- 行列レジスタの debug token は直接の実例が手元資料にないため、通常オペランド表記からの推定実装である
- 並列発行ハザード、アラインメント、`n<size>` の合法値のような詳細検証は未実装
- `@<l1bset>` や `immode` の完全な構文が本文書だけでは特定しきれないため、現状はその部分を文字列として受ける
