# MN-Core asm study

## judge / assembler / emulator の整理

`mncore_judge/README.md` と `mncore_judge/judge-py/judge.py` を合わせて読むと、同梱ツールの実行経路は次の 3 層に分かれています。

1. judge の公開エントリポイント

```sh
python3 mncore_judge/judge-py/judge.py \
	mncore_judge/example/hello_world/testcase.vsm \
	mncore_judge/example/hello_world/example.vsm \
	-v
```

2. judge が内部で使う同梱バイナリ

- アセンブラ: `mncore_judge/judge-py/mncore2_emuenv/assemble3`
- エミュレータ: `mncore_judge/judge-py/mncore2_emuenv/gpfn3_package_main`

3. バイナリ単体の標準的な起動方法

```sh
mncore_judge/judge-py/mncore2_emuenv/assemble3 sample.vsm > sample.asm
mncore_judge/judge-py/mncore2_emuenv/gpfn3_package_main -i sample.asm -d dump.txt
cat dump.txt
```

`mncore_judge/judge-py/mncore2_emuenv/README.md` では、上のファイルベース起動が基本形として説明されています。`tutorial.md` でも同じ流れで、まず `assemble3` で `.vsm` を `.asm` に変換し、次に `gpfn3_package_main -i ... -d ...` で dump を取得します。

`judge.py` はその上に採点用の薄いラッパーを載せています。主な挙動は次のとおりです。

- デフォルトのアセンブラとエミュレータのパスは `mncore_judge/judge-py/mncore2_emuenv/` 配下を向く
- `device != lime` のとき、アセンブラに `--instruction-mode flat` を付ける
- `device == noto` のとき、エミュレータに `--offchip-memory-init zero` を付ける
- testcase 内の `# ======= YOUR VSM WILL BE INSERTED HERE =======` に提出 VSM を差し込む
- アセンブル結果から emulator が読む命令行だけを残し、`d get` / `d set` も必要に応じて通す

補足:

- 同梱 README では Ubuntu 22.04 想定、依存ライブラリは `libgomp1`
- `debug_get()` などの debug 文を入れないと、エミュレータ実行自体はできても dump は空になることがあります

## asm_wrapper をそのまま流すラッパー

`asm_wrapper/runner.py` を追加しました。`InstructionBuilder` が作る VSM を受け取り、同梱 `assemble3` と `gpfn3_package_main` へそのまま流して dump を表示します。ルートの `main.py` からも同じ CLI を起動できます。

さらに `--testcase` を付けると、render した VSM を一時ファイルまたは `--out-dir` 配下へ保存したうえで、既存の `mncore_judge/judge-py/judge.py` をそのまま呼び出し、testcase 差し込みと judge 互換の検証まで一発で実行します。

受け取れる入力:

- `.py`: `build()` 関数、または `builder` 変数、または `source` 変数を読む
- `.vsm`: そのままアセンブルして実行する

Python 入力の返り値は次のどちらかです。

- `InstructionBuilder`
- VSM を表す `str`

リポジトリ内の最小サンプル:

- `examples/peid_lm0_sample.py`: `InstructionBuilder` を返す実行可能サンプル
- `examples/peid_lm0_testcase.vsm`: 上のサンプルを `--testcase` で検証するための judge 用 testcase
- `examples/mv_to_dram_sample.py`: PE 側の値を `L1BM -> L2BM -> DRAM` と流す、少し大きい `InstructionBuilder` サンプル
- `examples/mv_to_dram_sample.vsm`: 上のサンプルを素の `.vsm` 入力として試すためのレンダリング済み版

### 例: asm_wrapper の Python スクリプトをそのまま実行

```python
from asm_wrapper import DebugDataType, DebugLM0Ref, DebugScope, InstructionBuilder, PEID, LM0


def build() -> InstructionBuilder:
    builder = InstructionBuilder()
    builder.passa(precision="l", src_operand=PEID, dst_operands=[LM0.auto(0, vector=True)])
    builder.debug_get(
        target_memory=DebugLM0Ref(0, scope=DebugScope(group=0, l2b=0, l1b=0, mab=0, pe=0)),
        num_words=1,
        dtype=DebugDataType.DOUBLE,
    )
    return builder
```

```sh
python main.py path/to/program.py --print-vsm
```

同梱サンプルをそのまま試す場合:

```sh
python main.py examples/peid_lm0_sample.py
```

MV と DRAM 出力を含む少し大きいサンプル:

```sh
python main.py examples/mv_to_dram_sample.py
python main.py examples/mv_to_dram_sample.vsm --out-dir .mncore-out
```

### 例: 既存の VSM をそのまま実行

```sh
python main.py mncore_judge/example/hello_world/example.vsm --out-dir .mncore-out
```

### 例: asm_wrapper の出力を testcase に差し込んで judge 互換で検証

```sh
python main.py path/to/program.py \
	--testcase mncore_judge/example/hello_world/testcase.vsm \
	--out-dir .mncore-out
```

このモードでは、wrapper が render した提出 VSM を保存し、それを第 2 引数として `judge.py` に渡します。judge 側で `# ======= YOUR VSM WILL BE INSERTED HERE =======` への差し込み、期待値との比較、score 表示まで行います。

同梱サンプルを judge 互換で試す場合:

```sh
python main.py examples/peid_lm0_sample.py --testcase examples/peid_lm0_testcase.vsm
```

### よく使うオプション

- `--out-dir DIR`: 生成された `.vsm`, `.asm`, `.dmp` を保持する
- `--keep-temp`: 一時ディレクトリを削除せず残す
- `--device noto|lime`: `judge.py` と同じデバイス設定を使う
- `--testcase FILE`: testcase に差し込んで judge 互換の検証まで回す
- `--judge-script FILE`: `--testcase` 時に使う `judge.py` の場所を差し替える
- `--enable-get`, `--enable-set`: judge モードで `d get*`, `d set` を保持する
- `--seccomp`, `--seccomp-log`: judge モードの seccomp オプションを渡す
- `--dirty`: エミュレータに `--dirty` を渡す
- `--print-vsm`: アセンブル前の VSM を stderr に出す
- `--print-asm`: エミュレータに渡す `.asm` を stderr に出す
	- `--testcase` と同時指定は不可。judge 側で個別にアセンブルされるため

## 実行例

```sh
python main.py mncore_judge/example/hello_world/example.vsm --out-dir .mncore-out
cat .mncore-out/example.dmp
```

judge 互換の一発実行例:

```sh
python main.py mncore_judge/example/hello_world/example.vsm \
	--testcase mncore_judge/example/hello_world/testcase.vsm
```
