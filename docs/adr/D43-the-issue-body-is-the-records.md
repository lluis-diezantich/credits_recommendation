# D43: The issue body is the records; every count about the run is folded away

- **Status:** Accepted
- **Date:** 2026-10-30
- **Where it lives:** `to_markdown` and `run_lines` in
  [`../../radars/report.py`](../../radars/report.py)

## Context

Every issue so far has opened on four lines of arithmetic before the first
record:

    9 new releases from 128 of 128 artists in the gb-en store (last 6 days).

    Watching 128 of 170 on the list: 17 muted by hand, 21 ended or split up,
    2 with no id yet, 2 sharing an id.

    1 release was credited to more than one artist you watch, and is listed
    once.

[D42](D42-a-credit-is-a-release-you-would-have-missed.md) then added a fifth,
`credit candidates:`, and a second table under the first. The issue is read on a
phone on a Friday evening, and the thing it is for — what came out — had been
pushed below the fold by bookkeeping about the run that produced it.

Each of those lines was added for a reason that still holds. The watchlist line
exists because a mute used to be invisible: the issue said "146 of 146 artists"
and the 26 it had dropped appeared nowhere. The funnel line exists because
D42's role denylist is only trustworthy while somebody is watching the shape of
its counts. The question is not whether to keep them. It is whether the first
thing a reader sees should be a record or a number.

## Options

1. **Leave it.** Costs nothing, and the counts stay where a reader will
   actually meet them. The records keep starting on line nine, and D42 made
   that worse rather than better.
2. **Drop the lines.** Shortest body. Throws away the three things each line
   was added to make visible, and a number that stops being reported stops
   being re-measured — which is the one invariant `CLAUDE.md` states about
   numbers in this repo.
3. **Fold them into the existing `<details>` block.** The body opens on the
   table; every count survives one click away, in the block that already
   exists for stderr. The cost is that nobody reads a collapsed block unless
   something looks wrong.
4. **Keep the headline, fold the rest.** A compromise: one line of context,
   the bookkeeping hidden. Still puts a number first, and the headline is the
   line the table immediately restates.

## Decision

Option 3. The body is the two tables and nothing else; `run_lines()` builds the
counts as plain text and they go into the `warnings` block above the stderr
output.

Two things deliberately stay in the body:

- **`Nothing new.`** With the counts folded away it is the only thing left
  saying the run happened and found nothing. An empty body would read as a
  broken job.
- **The `⚠ N of M artists could not be fetched` line.** That is not a count,
  it is a caveat about whether the table is the whole answer, and a reader who
  never opens the block still has to see it.

The folded text is plain, not markdown, because it renders inside a fence —
`` `gb-en` `` would show its backticks and `**9 new releases**` its asterisks.

The `<details>` block used to appear only when something had written to
stderr. It is now always present and always has content, which also fixes a
smaller thing: the block was previously evidence that something had gone
wrong, so its absence was reassuring and its presence alarming. It is now just
where the numbers live.

## Evidence

None, and this is a judgement about reading rather than a threshold. What can
be said is the shape: the 2026-10-30 issue carried 4 bookkeeping lines and 12
records, and the first record sat on line 9 of the body. After this it sits on
line 2.

No measurement would have settled option 3 against option 4 — that is a
preference about whether a one-line summary earns the top of the page, and it
was taken by the person who reads the issue.

## Consequences

- **The counts are one click away, and will be read less.** Accepted
  knowingly, and it is the real cost: the watchlist line exists because
  something invisible caused a wrong number to be believed for weeks, and
  folding it makes that failure mode slightly more likely again, not less.
- **D42's funnel is in the same position**, so the "re-measure this" intent
  behind printing it is weaker than when it was written. If the role denylist
  does drift, the signal is now behind a disclosure triangle. Worth
  revisiting if a drift is ever missed.
- **Four tests changed rather than broke**, because they asserted the old
  contract directly — `out.startswith("**1 new release**")` in
  `test_report.py` and the headline/watchlist ordering in
  `test_watchlist.py`. The assertions moved to the folded block; none of them
  were deleted.
- **Every other radar's report changes the same way.** `report.py` serves all
  of them, and none of them opted in. `radars/itunes.py` and
  `radars/listenbrainz.py` are not scheduled, so nothing is published from
  them today, but their bodies would now open on the table too.
- **What would reopen this:** a week where something was wrong and the folded
  block was not opened, which is the failure this trades for.
