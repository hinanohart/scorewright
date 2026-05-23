"""A candidate program: iterative Fibonacci.

In a real run this file would be produced/mutated by an evolution loop. Here it
is a fixed, correct candidate so the example is deterministic.
"""


def fib(n: int) -> int:
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return a


if __name__ == "__main__":
    print(fib(25))
