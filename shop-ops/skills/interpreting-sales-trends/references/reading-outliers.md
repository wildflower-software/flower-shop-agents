# How the outlier test works

The script compares each day with the **same weekday over the previous 8 weeks**.
A Saturday is judged against Saturdays, because Saturdays and Tuesdays are
different businesses.

- Days inside a holiday or owner-event window are left out of the baseline, so
  Valentine's week doesn't make the next few Fridays look slow.
- "Usual" is the **median** of those days, not the average. One huge day doesn't
  move a median much.
- How unusual a day is comes from the **modified z-score**: the distance from the
  median, scaled by how much those days normally vary (the median absolute
  deviation). A score of 3.5 or more, up or down, is flagged. This is the
  Iglewicz and Hoaglin rule, a common, conservative choice.
- If the history is perfectly steady, any day 50% away from it is flagged.
- A day needs at least 4 usable baseline days to be judged at all.

## What it can't tell you

- **Why.** It finds the day; the owner knows the reason.
- **Lost sales.** A low day can be low demand or empty buckets. Only the stockout
  and turned-away signals can tell those apart, and only if someone sent them.
- **Slow drifts.** A shop that gets 2% busier every week never trips an outlier
  test. That's what the period comparisons are for.
- **Anything about placeholder data.** On synthetic sales, the outliers show how
  the generator was written.

## Tuning

`BASELINE_WEEKS`, `OUTLIER_Z` and `MIN_BASELINE_DAYS` are at the top of
`scripts/sales_trends.py`. Raise `OUTLIER_Z` if the notes flag too many ordinary
days; lower it if the owner keeps spotting days the note missed.
