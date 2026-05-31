import numpy as np
from dtype import Dtype, NumpyDouble, NumpyFloat, NumpyHalf


def decompose_float(f: int, dtype: Dtype):
    mantissa = f & ((1 << dtype.mantissa_bits()) - 1)
    f >>= dtype.mantissa_bits()

    exponent = f & ((1 << dtype.exponent_bits()) - 1)
    f >>= dtype.exponent_bits()

    sign = f

    return sign, exponent, mantissa


def compose_float(sign: int, exponent: int, mantissa: int, dtype: Dtype):
    f = sign
    f = (f << dtype.exponent_bits()) + exponent
    f = (f << dtype.mantissa_bits()) + mantissa
    return f


def iszero(value: int, dtype: Dtype):
    sign, exponent, mantissa = decompose_float(value, dtype)
    if dtype.has_subnormal():
        return exponent == 0 and mantissa == 0
    else:
        return exponent == 0


def isinf(value: int, dtype: Dtype):
    sign, exponent, mantissa = decompose_float(value, dtype)
    if dtype.has_inf_extend():
        return exponent == ((1 << dtype.exponent_bits()) - 1) and mantissa == ((1 << dtype.mantissa_bits()) - 1)
    else:
        return exponent == ((1 << dtype.exponent_bits()) - 1)


def normalize_float(value: int, dtype: Dtype):
    sign, exponent, mantissa = decompose_float(value, dtype)
    if exponent == 0 and not dtype.has_subnormal():
        mantissa = 0
        # TODO: sign?
    if exponent == ((1 << dtype.exponent_bits()) - 1) and not dtype.has_inf_extend():
        mantissa = 0
    return compose_float(sign, exponent, mantissa, dtype)


def cast(value: int, from_dtype: Dtype, to_dtype: Dtype):
    sign, exponent, mantissa = decompose_float(value, from_dtype)

    if exponent == 0 and not iszero(value, from_dtype):  # subnormal
        assert mantissa > 0
        exponent = 1
        while mantissa < (1 << from_dtype.mantissa_bits()):
            exponent -= 1
            mantissa <<= 1
        mantissa -= 1 << from_dtype.mantissa_bits()

    exponent = exponent - (2 ** (from_dtype.exponent_bits() - 1)) + (2 ** (to_dtype.exponent_bits() - 1))
    mantissa = mantissa * (2 ** to_dtype.mantissa_bits()) // (2 ** from_dtype.mantissa_bits())

    if isinf(value, from_dtype) or exponent > (1 << to_dtype.exponent_bits()) - 1:
        if to_dtype.has_inf_extend():
            mantissa = (1 << to_dtype.mantissa_bits()) - 1
        return compose_float(sign, (1 << to_dtype.exponent_bits()) - 1, mantissa, to_dtype)

    if iszero(value, from_dtype) or (exponent <= 0 and not to_dtype.has_subnormal()):
        if to_dtype.has_subnormal():
            mantissa = 0
        return compose_float(sign, 0, mantissa, to_dtype)

    if exponent <= 0:  # subnormal
        mantissa += 1 << to_dtype.mantissa_bits()
        nshift = 1 - exponent
        # TODO: rounding
        mantissa >>= nshift
        exponent = 0

    assert 0 <= exponent and exponent < 2 ** to_dtype.exponent_bits()

    return compose_float(sign, exponent, mantissa, to_dtype)


def from_payload(payload: str, dtype: Dtype):
    if dtype.is_unsigned_integral():
        hexlen = dtype.num_bits() >> 2
        return [int(payload[i * hexlen : (i + 1) * hexlen], 16) for i in range(dtype.num_elements_in_long_word())]

    if dtype.is_integral():
        values = from_payload(payload, dtype.to_unsigned())
        values_signed = []
        for v in values:
            if v & (1 << (dtype.num_bits() - 1)):
                v -= 1 << dtype.num_bits()
            values_signed += [v]
        return values_signed

    if dtype.is_floating():
        values = [normalize_float(v, dtype) for v in from_payload(payload, dtype.to_unsigned())]
        if dtype in [Dtype.Half, Dtype.E4M3, Dtype.E5M2]:
            values = [cast(v, dtype, Dtype.Float) for v in values]
            dtype = Dtype.Float
        np_values = np.array(values, dtype=dtype.to_unsigned().to_numpy_dtype()).view(dtype.to_numpy_dtype())
        return [float(v) for v in np_values]

    if dtype == Dtype.String:
        res = ""
        for i in range(8):
            res += chr(int(payload[i * 2 : i * 2 + 2], 16))
        return res

    raise AssertionError(f"other dtypes are not supported: dtype={dtype}")


def bcast_lw(lw_values, dtype):
    return lw_values * dtype.num_elements_in_long_word()


def unsigned_integral_dtype_with_same_width(dtype: np.dtype):
    if dtype == np.float16:
        return np.uint16
    if dtype == np.float32:
        return np.uint32
    if dtype == np.float64:
        return np.uint64
    raise AssertionError(f"dtype {dtype} is not handled")


def get_numpy_dtype_spec(dtype: np.dtype):
    if dtype == np.float16:
        return NumpyHalf
    if dtype == np.float32:
        return NumpyFloat
    if dtype == np.float64:
        return NumpyDouble
    raise AssertionError(f"dtype {dtype} is not handled")


def round_value(value, dtype: Dtype):
    assert value.dtype == dtype.to_numpy_dtype(), f"dtype mismatches: actual={value.dtype} expected={dtype.to_numpy_dtype()} dtype={dtype}"

    if dtype.is_floating() and dtype != Dtype.Double:
        view_dtype = unsigned_integral_dtype_with_same_width(value.dtype)
        numpy_dtype = get_numpy_dtype_spec(value.dtype)
        value = cast(int(value.view(view_dtype)), numpy_dtype, dtype)
        value = cast(value, dtype, Dtype.Float)
        value = np.array(value, np.uint32).view(np.float32)

    return value


def to_payload(lw_values, dtype: Dtype):
    if len(lw_values) == 1 and dtype.num_elements_in_long_word() > 1:
        lw_values = bcast_lw(lw_values, dtype)

    assert len(lw_values) == dtype.num_elements_in_long_word(), f"padding is not supported: lw_values={lw_values} dtype={dtype}"

    if dtype.is_unsigned_integral():
        hexlen = dtype.num_bits() >> 2
        return "".join(f"{v:0{hexlen}X}" for v in lw_values)

    if dtype.is_integral():
        lw_values = [(v + (1 << dtype.num_bits()) if v < 0 else v) for v in lw_values]
        return to_payload(lw_values, dtype.to_unsigned())

    if dtype == Dtype.Double:
        bits = np.float64(lw_values[0]).view(np.uint64)
        return f"{bits:016X}"

    if dtype == Dtype.Float:
        bits = np.float32(lw_values).view(np.uint32)
        return f"{bits[0]:08X}{bits[1]:08X}"

    if dtype == Dtype.Half:
        bits = [cast(int(np.float32(v).view(np.uint32)), NumpyFloat, Dtype.Half) for v in lw_values]
        return f"{bits[0]:04X}{bits[1]:04X}{bits[2]:04X}{bits[3]:04X}"

    if dtype in [Dtype.E4M3, Dtype.E5M2]:
        bits = [cast(int(np.float32(v).view(np.uint32)), NumpyFloat, dtype) for v in lw_values]
        return "".join([f"{bits[i]:02X}" for i in range(dtype.num_elements_in_long_word())])

    raise AssertionError(f"other dtypes are not supported: dtype={dtype}")
