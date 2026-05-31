from enum import Enum

import numpy as np


class Dtype(Enum):
    ULong = 0
    UInt = 1
    UShort = 2
    UByte = 3

    Long = 4
    Int = 5
    Short = 6
    Byte = 7

    Double = 8
    Float = 9
    Half = 10
    E4M3 = 11
    E5M2 = 12

    String = 13

    def __str__(self):
        return DTYPE_TO_STR[self]

    def is_unsigned_integral(self):
        return self in [Dtype.UByte, Dtype.UShort, Dtype.UInt, Dtype.ULong]

    def is_integral(self):
        return self in [Dtype.Byte, Dtype.Short, Dtype.Int, Dtype.Long]

    def is_floating(self):
        return self in [Dtype.E4M3, Dtype.E5M2, Dtype.Half, Dtype.Float, Dtype.Double]

    def num_bits(self):
        if self == Dtype.ULong or self == Dtype.Long or self == Dtype.Double:
            return 64

        if self == Dtype.UInt or self == Dtype.Int or self == Dtype.Float:
            return 32

        if self == Dtype.UShort or self == Dtype.Short or self == Dtype.Half:
            return 16

        if self == Dtype.UByte or self == Dtype.Byte or self == Dtype.E4M3 or self == Dtype.E5M2:
            return 8

        if self == Dtype.String:
            return 8

        raise AssertionError(f"Unknown dtype: {self}")

    def exponent_bits(self):
        TABLE = {
            Dtype.Double: 11,
            Dtype.Float: 8,
            Dtype.Half: 6,
            Dtype.E4M3: 4,
            Dtype.E5M2: 5,
        }
        assert self in TABLE, f"{self} is not a floating point type"

        return TABLE[self]

    def mantissa_bits(self):
        TABLE = {
            Dtype.Double: 52,
            Dtype.Float: 23,
            Dtype.Half: 9,
            Dtype.E4M3: 3,
            Dtype.E5M2: 2,
        }
        assert self in TABLE, f"{self} is not a floating point type"

        return TABLE[self]

    def has_inf_extend(self):
        return self == Dtype.E4M3

    def has_subnormal(self):
        return self in [Dtype.E4M3, Dtype.E5M2]

    def num_elements_in_long_word(self):
        return 64 // self.num_bits()

    def to_unsigned(self):
        TABLE = {
            Dtype.Long: Dtype.ULong,
            Dtype.Int: Dtype.UInt,
            Dtype.Short: Dtype.UShort,
            Dtype.Byte: Dtype.UByte,
            Dtype.Double: Dtype.ULong,
            Dtype.Float: Dtype.UInt,
            Dtype.Half: Dtype.UShort,
            Dtype.E4M3: Dtype.UByte,
            Dtype.E5M2: Dtype.UByte,
        }
        assert self in TABLE, f"{self} is not a signed integer nor a floating point type"

        return TABLE[self]

    def to_numpy_dtype(self):
        TABLE = {
            Dtype.ULong: np.uint64,
            Dtype.UInt: np.uint32,
            Dtype.UShort: np.uint16,
            Dtype.UByte: np.uint8,
            Dtype.Long: np.int64,
            Dtype.Int: np.int32,
            Dtype.Short: np.int16,
            Dtype.Byte: np.int8,
            Dtype.Double: np.float64,
            Dtype.Float: np.float32,
            Dtype.Half: np.float32,
            Dtype.E4M3: np.float32,
            Dtype.E5M2: np.float32,
            Dtype.String: str,
        }
        return TABLE[self]

    @staticmethod
    def deserialize(dtype_str):
        for dtype, s in DTYPE_TO_STR.items():
            if s == dtype_str:
                return dtype

        raise AssertionError(f"Unknown dtype: {dtype_str}")


class NumpyHalf:
    @staticmethod
    def exponent_bits():
        return 5

    @staticmethod
    def mantissa_bits():
        return 10

    @staticmethod
    def has_inf_extend():
        return False

    @staticmethod
    def has_subnormal():
        return True


class NumpyFloat:
    @staticmethod
    def exponent_bits():
        return 8

    @staticmethod
    def mantissa_bits():
        return 23

    @staticmethod
    def has_inf_extend():
        return False

    @staticmethod
    def has_subnormal():
        return True


class NumpyDouble:
    @staticmethod
    def exponent_bits():
        return 11

    @staticmethod
    def mantissa_bits():
        return 52

    @staticmethod
    def has_inf_extend():
        return False

    @staticmethod
    def has_subnormal():
        return True


DTYPE_TO_STR = {
    Dtype.ULong: "ULong",
    Dtype.UInt: "UInt",
    Dtype.UShort: "UShort",
    Dtype.UByte: "UByte",
    Dtype.Long: "Long",
    Dtype.Int: "Int",
    Dtype.Short: "Short",
    Dtype.Byte: "Byte",
    Dtype.Double: "Double",
    Dtype.Float: "Float",
    Dtype.Half: "Half",
    Dtype.E4M3: "E4M3",
    Dtype.E5M2: "E5M2",
    Dtype.String: "String",
}
