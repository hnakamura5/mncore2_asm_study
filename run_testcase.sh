SCRIPT_DIR=$(dirname "$(realpath "$0")")

$SCRIPT_DIR/.venv/bin/python main.py --testcase "mncore_judge/problems/$1/testcase.vsm" --keep-temp --enable-get --out-dir "mncore_judge/problems/$1/out" mncore_judge/problems/$1/$1.py
