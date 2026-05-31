import argparse
import ast
import os
import re
import subprocess
import sys
from typing import List

import numpy as np
from converter import from_payload
from dtype import Dtype
from numpy.typing import NDArray
from vsm_here import GET_OUTPUT_COMMENT, VSM_HERE_COMMENT

ROOT = os.path.dirname(os.path.abspath(__file__))


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("testcase", help="testcase vsm file", type=str)
    parser.add_argument("vsm", help="solution to check", type=str)
    parser.add_argument("--device", help="device name", default="noto", type=str)
    parser.add_argument("--emulator", help="path to emulator", default=ROOT + "/mncore2_emuenv/gpfn3_package_main", type=str)
    parser.add_argument("--assembler", help="path to assembler", default=ROOT + "/mncore2_emuenv/assemble3", type=str)
    parser.add_argument("--enable-get", help="preserve 'd get*' in vsm", action="store_true")
    parser.add_argument("--enable-set", help="preserve 'd set' in vsm", action="store_true")
    parser.add_argument("--seccomp-log", help="Enable seccomp logger", action="store_true")
    parser.add_argument("--seccomp", help="Enable seccomp sandbox", action="store_true")
    parser.add_argument("--dirty", help="Enable emulator dirty mode run", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args()


def read_file(filename):
    with open(filename, mode="r") as f:
        content = f.read()
    return content


def sanitize_vsm(vsm: str):
    return re.sub(r"[#!].*$", "", vsm, flags=re.MULTILINE)


def prepare_env(args):
    env = os.environ.copy()
    if args.seccomp:
        env["LD_PRELOAD"] = os.path.join(ROOT, "sandbox/golfsandbox_kill.so")
        assert os.path.exists(env["LD_PRELOAD"]), f"{env['LD_PRELOAD']} not found"
    elif args.seccomp_log:
        env["LD_PRELOAD"] = os.path.join(ROOT, "sandbox/golfsandbox_log.so")
        assert os.path.exists(env["LD_PRELOAD"]), f"{env['LD_PRELOAD']} not found"
    return env


def assemble(vsm: str, args):
    if args.verbose:
        print("------------------- asm --------------------", file=sys.stderr)

    env = prepare_env(args)

    cmd_args = [args.assembler]
    if args.device != "lime":
        cmd_args += ["--instruction-mode", "flat"]
    p = subprocess.Popen(cmd_args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    asm, stderr = p.communicate(vsm.encode())

    if stderr.decode(errors="replace") != "":
        print(stderr.decode(errors="replace"), file=sys.stderr)
    assert p.returncode == 0, f"{args.assembler} exits with code={p.returncode}"

    if args.verbose:
        print(asm.decode(errors="replace"), file=sys.stderr)
    return asm.decode(errors="replace")


def sanitize_asm(asm: str, args):
    def is_valid_line(asm: str, args):
        tokens = asm.split()
        if len(tokens) == 0:
            return True
        if tokens[0] in ["j", "m"]:
            return True
        if args.device == "lime" and tokens[0] == "i":
            return True
        if tokens[0] == "d" and len(tokens) > 1:
            if args.enable_get and tokens[1].startswith("get"):
                return True
            if args.enable_set and tokens[1] == "set":
                return True
        return False

    return "\n".join(line for line in asm.split("\n") if is_valid_line(line, args))


def emulate(asm: str, args):
    if args.verbose:
        print("------------------- emu --------------------", file=sys.stderr)

    env = prepare_env(args)
    env["OMP_THREAD_LIMIT"] = "1"  # stop showing duplicated errors

    cmd_args = [args.emulator]
    if args.device == "noto":
        cmd_args += ["--offchip-memory-init", "zero"]
    if args.dirty:
        cmd_args += ["--dirty"]
    p = subprocess.Popen(cmd_args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)

    stdout, stderr = p.communicate(asm.encode())

    result = stderr.decode(errors="replace")

    if p.returncode != 0 or args.verbose:
        print(result + stdout.decode(errors="replace"), file=sys.stderr)
    assert p.returncode == 0, f"{args.emulator} exits with code={p.returncode}"

    return result


class TestcaseLine:
    def __init__(self, op: str, values: List[int] | List[float] | str, dtype: Dtype, indices: List[int], atol: float, rtol: float | None):
        self.op = op
        self.values = values
        self.dtype = dtype
        self.indices = indices
        self.atol = atol
        self.rtol = rtol

    @staticmethod
    def parse_line(line: str):
        op = line[0]
        values_str, dtype_str, indices_str, atol_str, rtol_str = re.search(r"# .*?=(.*?) / (.*?) @([^ ]+)( atol=[^ ]*)?( rtol=[^ ]*)?", line).groups()
        dtype = Dtype.deserialize(dtype_str)

        if dtype.is_floating():
            # ast.literal_eval cannot eval "inf"
            values_str = values_str.replace("-inf", "'-inf'").replace("inf", "'inf'")
            values = ast.literal_eval(values_str)
            values = [(float("-inf") if v == "-inf" else float("inf") if v == "inf" else v) for v in values]
        else:
            values = ast.literal_eval(values_str)

        indices = ast.literal_eval("[" + indices_str + "]")[: len(values_str)]

        atol = ast.literal_eval(atol_str.split("=")[1]) if atol_str is not None else 0
        rtol = ast.literal_eval(rtol_str.split("=")[1]) if rtol_str is not None else 0

        return TestcaseLine(op, values, dtype, indices, atol, rtol)

    def __str__(self):
        return f"{{op={self.op} indices={self.indices}}}"


def parse_testcase_lines(vsm_prefix_or_suffix: str) -> List[List[TestcaseLine]]:
    lines_list = []
    lines = []
    for line in vsm_prefix_or_suffix.split("\n"):
        if line == "":
            continue
        if line[0] == "#":
            if len(lines) > 0:
                lines_list.append(lines)
            lines = []
        else:
            lines.append(TestcaseLine.parse_line(line))

    if len(lines) > 0:
        lines_list.append(lines)

    return lines_list


def split_into_lines(entire: str):
    return [line for line in entire.split("\n") if len(line) > 0 and line[0] != "#"]


def discard_userdump_lines(expect_lines: List[TestcaseLine], result_lines: List[str]):
    for line in expect_lines:
        assert line.op == "d", f"[internal error] invalid testcase line: {line}"

    # Reverse to get by pop method.
    result_cut = list(reversed(result_lines[len(result_lines) - len(expect_lines) :]))
    assert len(result_cut) == len(expect_lines)

    user_dump = result_lines[: len(result_lines) - len(expect_lines)]
    if user_dump:
        print("------------------- user dump --------------------", file=sys.stderr)
        for line in user_dump:
            print(line, file=sys.stderr)
        print("", file=sys.stderr)

    return result_cut


def get_actual_lines(expect_lines: List[TestcaseLine], result_lines: List[str]):
    actual_lines = []
    for line in expect_lines:
        assert line.op == "d", f"invalid testcase line: {line}"

        result = result_lines.pop()
        payload = re.search(r":\([^)]+\) \(0x([^)]+)\)", result).group(1)

        actual_values = from_payload(payload, line.dtype)[: len(line.values)]

        actual_line = TestcaseLine(line.op, actual_values, line.dtype, line.indices, line.atol, line.rtol)
        actual_lines.append(actual_line)
    return actual_lines


def check_result(actual: NDArray | str, expected: NDArray | str, atol: float, rtol: float):
    error_num = 0
    correct_num = 0

    if isinstance(actual, str):
        assert isinstance(expected, str), "internal error"
        assert len(actual) == len(expected), "internal error"
        for i in range(len(actual)):
            if actual[i] != expected[i]:
                print(f"RESULT MISMATCH: pos={i} actual='{actual[i]}' expected='{expected[i]}'", file=sys.stderr)
                error_num += 1
            else:
                correct_num += 1
    else:
        assert actual.shape == expected.shape, "internal error"

        for i in range(np.prod(actual.shape)):
            if len(actual.shape) > 1:
                i = np.unravel_index(i, actual.shape)

            is_atol_err = abs(actual[i] - expected[i]) > atol
            is_rtol_err = abs(actual[i] - expected[i]) > rtol * abs(expected[i])

            if is_atol_err and is_rtol_err:
                print(
                    f"RESULT MISMATCH: pos={i} actual={actual[i]} expected={expected[i]} error={actual[i] - expected[i]}",
                    file=sys.stderr,
                )
                error_num += 1
            else:
                correct_num += 1
    if error_num > 0:
        print("", file=sys.stderr)
        print(f"{correct_num} value(s) correct, but {error_num} value(s) mismatch")
        exit(1)


def lines_to_tensor(lines: List[TestcaseLine]) -> NDArray | str:
    assert len(lines) > 0, "empty tensor"

    max_shape_index = lines[0].indices[0]
    for line in lines:
        for si in line.indices:
            max_shape_index = max(max_shape_index, si)

    shape = [i + 1 for i in max_shape_index]

    if lines[0].dtype == Dtype.String:
        x = [0] * shape[0]
        for line in lines:
            for si, v in zip(line.indices, line.values):
                x[si[0]] = v
        return "".join(x)
    else:
        x = np.zeros(shape=shape, dtype=object)
        for line in lines:
            for si, v in zip(line.indices, line.values):
                x[tuple(si)] = v
    return x


def count_lines(asm: str):
    cnt = {
        "j": 0,
        "m": 0,
        "i": 0,
    }
    for line in asm.split("\n"):
        if line != "":
            if line[0] not in cnt:
                cnt[line[0]] = 0
            cnt[line[0]] += 1
    return cnt


def remove_comments(vsm: str):
    new_vsm = ""
    for line in vsm.split("\n"):
        line = re.sub(r"[#!].*$", "", line).strip()
        if line != "":
            new_vsm += line + "\n"
    return new_vsm.strip()


def print_tensor(dtype: Dtype, tensor: NDArray | str, file):
    if dtype == Dtype.String:
        if len(tensor) > 100:
            print(f"{tensor[:100]}...", file=file)
        else:
            print(tensor, file=file)
    else:
        if dtype.is_unsigned_integral():
            tensor = tensor.astype(np.uint64)
        elif dtype.is_integral():
            tensor = tensor.astype(np.int64)
        else:
            tensor = tensor.astype(np.float64)
        print(np.array2string(tensor, separator=", ", formatter={"float_kind": lambda x: f"{x:g}"}), file=file)
    print("", file=file)


def judge(testcase_vsm: str, main_vsm: str, args):
    vsm_input, vsm_entire_suffix = testcase_vsm.split(VSM_HERE_COMMENT + "\n")
    vsm_suffix, vsm_output = vsm_entire_suffix.split(GET_OUTPUT_COMMENT + "\n")

    if args.verbose:
        print("------------------- vsm --------------------", file=sys.stderr)
        print(vsm_input, file=sys.stderr)
        print(main_vsm, file=sys.stderr)
        print(vsm_suffix, file=sys.stderr)
        print(vsm_output, file=sys.stderr)

    main_asm = sanitize_asm(assemble(sanitize_vsm(main_vsm), args), args)
    asm_suffix = ""
    if vsm_suffix.strip() != "":
        asm_suffix = sanitize_asm(assemble(sanitize_vsm(vsm_suffix), args), args)

    asm = vsm_input + main_asm + asm_suffix + vsm_output

    result_lines = emulate(asm, args)

    input_lines_list = parse_testcase_lines(vsm_input)
    expect_lines = parse_testcase_lines(vsm_output)[0]

    result_lines = split_into_lines(result_lines)

    result_lines = discard_userdump_lines(expect_lines, result_lines)
    actual_lines = get_actual_lines(expect_lines, result_lines)

    inputs = [lines_to_tensor(input_lines) for input_lines in input_lines_list]
    expect = lines_to_tensor(expect_lines)
    actual = lines_to_tensor(actual_lines)

    if args.verbose:
        print("------------------- inputs --------------------", file=sys.stderr)
        for input_tensor, lines in zip(inputs, input_lines_list):
            print_tensor(lines[0].dtype, input_tensor, file=sys.stderr)

        out_dtype = expect_lines[0].dtype

        print("------------------- expect --------------------", file=sys.stderr)
        print_tensor(out_dtype, expect, file=sys.stderr)

        print("------------------- actual --------------------", file=sys.stderr)
        print_tensor(out_dtype, actual, file=sys.stderr)

    if args.verbose:
        print("------------------- check result --------------------", file=sys.stderr)
    check_result(actual, expect, expect_lines[0].atol, expect_lines[0].rtol)

    cnt = count_lines(main_asm)
    if args.device == "lime":
        score = cnt["i"]
        accepted_str = f"ACCEPTED!! score={score} bytes={len(remove_comments(main_vsm).strip())}"
    else:
        score = cnt["j"] + cnt["m"]
        accepted_str = f"ACCEPTED!! score={score} j={cnt['j']} m={cnt['m']} bytes={len(remove_comments(main_vsm).strip())}"

    if "d set" in main_asm:
        print(accepted_str, file=sys.stderr)
        print("but 'd set' used. Score invalid. Remove and submit again.", file=sys.stderr)
        sys.exit(1)
    print(accepted_str)


def main():
    args = parse_args()

    vsm = read_file(args.vsm)
    testcase_vsm = read_file(args.testcase)
    judge(testcase_vsm, vsm, args)


if __name__ == "__main__":
    main()
