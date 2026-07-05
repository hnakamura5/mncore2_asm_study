def fizz_buzz(n: int) -> list[str]:
    result: list[str] = []
    for i in range(0, n):
        if i % 15 == 0:
            result.append("FizzBuzz")
        elif i % 3 == 0:
            result.append("Fizz")
        elif i % 5 == 0:
            result.append("Buzz")
        else:
            result.append(str(i))
    return result


fizz_buzz_list = fizz_buzz(8192)
all = ""
# sum = 0
# for i in range(0, 64):
#     per64 = ""
#     per_l1b = 120
#     for j in range(1, per_l1b + 1):
#         idx = i * per_l1b + j
#         per64 += fizz_buzz_list[idx] + "\n"
#         if idx <= 6334:
#             all += fizz_buzz_list[idx] + "\n"
#     sum += len(per64)
#     print(f"{i}: {len(per64)} bytes, sum: {sum} bytes")

all_8bytes: list[str] = []
start_8bytes: list[int] = [0]

current = ""
for i in range(1, 6334 + 1):
    all += fizz_buzz_list[i] + "\n"
    current += fizz_buzz_list[i] + "\n"
    if len(current) >= 8:
        all_8bytes.append(current[:8])
        start_8bytes.append(i)
        current = current[8:]
all_8bytes.append(current)


print(f"all: {len(all)} bytes")
# for i in range(0, len(all) // 8 + 1):
#     print(f"{all[i * 8 : (i + 1) * 8].replace('\n', '\\')}")

for i in range(0, len(all_8bytes)):
    print(f"{i}: {all_8bytes[i].replace('\n', '\\')}, start_idx: {start_8bytes[i]}")
