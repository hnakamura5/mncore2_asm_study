# tests

このディレクトリには、実行ラッパー `main.py` の end-to-end テストを置いている。

## 構成

- `test_runner_cli.py`: ラッパー CLI を subprocess で起動し、実際にアセンブラとエミュレータを通すテスト本体
- `expected/`: エミュレータ実行結果や judge 実行結果の期待値 fixture

現在のテスト対象:

- `examples/peid_lm0_sample.py` を通常実行し、dump 出力が期待値と一致すること
- `examples/peid_lm0_sample.py --testcase examples/peid_lm0_testcase.vsm` を実行し、judge 結果が期待値と一致すること
- `examples/mv_to_dram_sample.py` を通常実行し、DRAM dump が期待値と一致すること
- `examples/mv_to_dram_sample.vsm` を直接入力として実行し、期待値と一致すること
- `--out-dir` 指定時に `.vsm`, `.asm`, `.dmp` が生成され、`.dmp` の内容が期待値と一致すること

## expected の役割

`expected/` のファイルは、実行結果を文字列として固定した fixture である。
テストコードは stdout や生成された `.dmp` をこれらと比較する。

現在の fixture:

- `expected/peid_lm0_sample.dump.txt`: 最小サンプルの standalone dump
- `expected/peid_lm0_sample.judge.txt`: 最小サンプルの judge 互換結果
- `expected/mv_to_dram_sample.dump.txt`: MV/DRAM サンプルの dump

エミュレータの表示形式が変わった場合は、まずサンプルを手動で実行して差分が妥当か確認し、その後 fixture を更新する。

## 実行方法

```sh
python -m unittest discover -s tests -v
```

仮想環境を使う場合の例:

```sh
.venv/bin/python -m unittest discover -s tests -v
```

## 注意点

- テストは同梱 `assemble3` と `gpfn3_package_main` を実際に起動する
- `test_runner_cli.py` では実行前に同梱バイナリへユーザー実行ビットを付ける
- fixture 比較は改行込みで行うため、期待値ファイルを編集するときは末尾改行の扱いに注意する
