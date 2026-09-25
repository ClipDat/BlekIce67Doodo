from live_trader import (
    leverage_after_loss,
    leverage_after_normal_close,
    leverage_after_timeout,
)


def check(actual, expected, label):
    if actual != expected:
        raise AssertionError(
            f"FAIL {label}: expected {expected}x, got {actual}x"
        )
    print(f"PASS {label}: {actual}x")


# Normal losses
check(leverage_after_loss(2), 4, "2x LOSS -> 4x")
check(leverage_after_loss(4), 8, "4x LOSS -> 8x")
check(leverage_after_loss(8), 16, "8x LOSS -> 16x")
check(leverage_after_loss(16), 32, "16x LOSS -> 32x")
check(leverage_after_loss(32), 2, "32x LOSS -> 2x")

# Normal wins always reset
for leverage in [2, 4, 8, 16, 32]:
    check(
        leverage_after_normal_close(leverage, 0.01),
        2,
        f"{leverage}x WIN -> 2x",
    )

# Normal losses advance
for leverage, expected in [(2, 4), (4, 8), (8, 16), (16, 32), (32, 2)]:
    check(
        leverage_after_normal_close(leverage, -0.01),
        expected,
        f"{leverage}x normal LOSS -> {expected}x",
    )

# Timeout profits stay the same; timeout losses advance
for leverage in [2, 4, 8, 16, 32]:
    check(
        leverage_after_timeout(leverage, 0.01),
        leverage,
        f"{leverage}x timeout PROFIT -> same",
    )

for leverage, expected in [(2, 4), (4, 8), (8, 16), (16, 32), (32, 2)]:
    check(
        leverage_after_timeout(leverage, -0.01),
        expected,
        f"{leverage}x timeout LOSS -> {expected}x",
    )

print("\nALL PROGRESSION TESTS PASSED")
