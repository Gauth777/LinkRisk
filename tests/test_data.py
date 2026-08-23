import pandas as pd
from sentinelgraph.data import chronological_split

def test_chronological_split_preserves_order():
    df=pd.DataFrame({"TransactionDT":[5,1,4,3,2,6,7,8,9,10],"isFraud":[0]*10})
    tr,va,te=chronological_split(df)
    assert tr.TransactionDT.is_monotonic_increasing
    assert va.TransactionDT.is_monotonic_increasing
    assert te.TransactionDT.is_monotonic_increasing
    assert tr.TransactionDT.max()<va.TransactionDT.min()<te.TransactionDT.min()
