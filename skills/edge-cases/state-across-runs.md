# State across runs

What one run leaves behind for the next: files written, caches, lock files, a half-finished
write, a counter, a run directory that already exists.

Ask of the spec and the code:

- What does a run write that a later run reads? What if the earlier run stopped halfway?
- Is running it twice the same as running it once? Should it be?
- Does a second run refuse, overwrite, or append when the first run's output is already
  there?
- Can a stale file from an old version be read as current?

The spec's line for this category reads like:

- State across runs: a run directory that already exists is refused, so an earlier run's work is never overwritten

Or, where nothing persists:

- State across runs: N/A: nothing is written, and every run reads only its arguments

Each case in the line gets a test of its own, set up with the earlier run's leftovers in
place. A case the line does not name is named back, not tested.
