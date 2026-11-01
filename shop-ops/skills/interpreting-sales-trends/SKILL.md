---
name: interpreting-sales-trends
description: Read the shop's recent sales against the period before and the same weeks last year, and write a short note on trends and outlier days. Use when the owner asks how sales are going, for the weekly review, or before building an order.
metadata:
  data: shop.db (daily_sales, sales_line, product, calendar_event, demand_signal)
---

# Interpreting sales trends

## 1. Get the numbers from the script

```bash
uv run python skills/interpreting-sales-trends/scripts/sales_trends.py --weeks 4
```

Add `--as-of YYYY-MM-DD` to look at a past period. The script does all the math.
**Every number in your note must come from its output.** Don't add up, average or
estimate anything yourself.

## 2. Check what the data is

Read `data_basis` first.

- `real`: write the note normally.
- `synthetic` or `mixed`: start the note with "Placeholder data, not evidence."
  Trends and outliers in made-up data describe the generator, not the shop.
- `none`: say there are no sales for the period and stop.

## 3. Write the trend in three lines

1. **Revenue**: this period vs the period before and vs the same weeks last year,
   using `change_pct`. Last year is the fairer comparison, because flowers are
   seasonal.
2. **What drove it**: more transactions, or a bigger average ticket? Say which.
3. **Mix**: name any product type whose `share_pct` moved by 3 points or more
   between `mix_prior` and `mix`: twenties and fifteens (`bouquet_giftwrap`),
   single stems, bundles, arrangements.

A change under 5% is normal week-to-week movement. Call it "about the same."
Don't call anything a trend from fewer than 4 weeks.

## 4. Note each outlier day

The script flags days far from the usual for that weekday. For each one, sort it:

- **Explained by the calendar**: it falls in a holiday or owner event window
  (`calendar`). One line using `times_usual`, e.g. "Feb 13 was 4.6x a usual Friday:
  Valentine's week."
  Mention it only if it's in the period the owner asked about.
- **Possibly explained by demand signals**: `demand_signals` shows stockouts or
  turned-away customers that day. A low day with a stockout may be lost sales,
  not low demand. Say so.
- **No sales recorded**: the shop may have been closed, or the POS export may be
  missing a day. Ask which; don't assume.
- **Unexplained**: give the numbers and ask the owner one short question,
  e.g. "Sat Jan 31 was 48% above a usual Saturday. Do you know why?"

Her answer is a field note. Propose adding it as an owner event or a note in the
weekly review, so next year the same day is explained.

See [references/reading-outliers.md](references/reading-outliers.md) for how the
outlier test works and what it can't tell you.

## 5. What not to do

- Don't guess causes such as weather, the news or a competitor. Ask instead.
- Don't recommend an order change from one outlier. One day is not a pattern.
- Don't treat an assumption as proven. "Fridays are busiest" stays presumed until
  `shop-ops check-busiest-days` marks it supported on real data.

## Note format

```
Sales, <start> to <end> (<data basis>)
Revenue <+/-x%> vs the 4 weeks before, <+/-y%> vs last year.
<Driver line.> <Mix line, if anything moved.>
Outliers:
- <day>: <revenue> vs usual <usual> (<+/-z%>). <explanation or question>
```

Keep it short enough to read on a phone. At most one question for the owner.
