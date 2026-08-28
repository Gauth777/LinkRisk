# Focused REVIEW search

Use `find_live_review_candidate.py` for broad exploration. If the broad search produces a near-threshold candidate, use `find_focused_review_candidate.py` to hold the strongest public inputs fixed while sweeping only `payment_profile` tokens.

The live adapter deterministically maps `payment_profile` into masked IEEE-CIS-compatible card/address fields. This remains an input search only: the frozen model, REVIEW threshold, policy, live session, and Razorpay integration are untouched.

Example:

```powershell
python scripts\find_focused_review_candidate.py --count 1000000 --amount 499
```

The focused script never calls FastAPI or Razorpay and never reads or writes `.linkrisk/session.jsonl`.
