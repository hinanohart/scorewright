from fib import fib


def test_base_cases() -> None:
    assert fib(0) == 0
    assert fib(1) == 1


def test_sequence() -> None:
    assert fib(10) == 55
    assert fib(20) == 6765
