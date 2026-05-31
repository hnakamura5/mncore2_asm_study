
## judge.py の動かし方

Ubuntu 20.04 または Ubuntu 22.04 をご利用の方は次のコマンドを試してください。
```
$ pip3 install -r judge-py/requirements.txt
$ python3 judge-py/judge.py example/hello_world/testcase.vsm example/hello_world/example.vsm -v
```
Ubuntu 24.04 をご利用の方は、`judge-py/requirements.txt` の "numpy==1.23.1" を "numpy==1.26.4" に修正してから上記のコマンドを試してください。

他の OS をご利用の方は docker をインストールした後、次のコマンドを試してください。
- Mac 等
```
$ ./judge example/hello_world/testcase.vsm example/hello_world/example.vsm -v
```
- Windows
```
> ./judge.bat example/hello_world/testcase.vsm example/hello_world/example.vsm -v
```
※こちらは docker を立ててカレントディレクトリ `.` をマウントすることによってローカルのファイルを参照しています。
※したがって、絶対パスや `.` よりも上位のディレクトリを指定できないことに注意してください。
