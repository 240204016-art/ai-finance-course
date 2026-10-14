import pytest

from services.payments import split_amount


@pytest.mark.parametrize("total,n,expected", [
    (4000, 2, [2000, 2000]),
    (4500, 3, [1500, 1500, 1500]),
    (4000, 3, [1334, 1333, 1333]),
    (4001, 4, [1001, 1000, 1000, 1000]),
    (4003, 4, [1001, 1001, 1001, 1000]),
    (3000, 1, [3000]),
    (1, 3, [1, 0, 0]),
])
def test_split_amount(total, n, expected):
    assert split_amount(total, n) == expected


@pytest.mark.parametrize("total", [1, 999, 3500, 4001, 12345, 100_000])
@pytest.mark.parametrize("n", [1, 2, 3, 4])
def test_split_sum_is_preserved_and_fair(total, n):
    shares = split_amount(total, n)
    assert len(shares) == n
    assert sum(shares) == total
    assert max(shares) - min(shares) <= 1
    assert shares == sorted(shares, reverse=True)  # лишний тенге — первым (организатору)


def test_split_invalid_arguments():
    with pytest.raises(ValueError):
        split_amount(1000, 0)
    with pytest.raises(ValueError):
        split_amount(-5, 2)
