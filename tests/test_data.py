import pandas as pd

from linkrisk.data import chronological_split


def test_chronological_split_preserves_order():
    df = pd.DataFrame(
        {
            "TransactionDT": [5, 1, 4, 3, 2, 6, 7, 8, 9, 10],
            "isFraud": [0] * 10,
        }
    )

    train, validation, test = chronological_split(df)

    assert train.TransactionDT.is_monotonic_increasing
    assert validation.TransactionDT.is_monotonic_increasing
    assert test.TransactionDT.is_monotonic_increasing
    assert train.TransactionDT.max() < validation.TransactionDT.min()
    assert validation.TransactionDT.max() < test.TransactionDT.min()
