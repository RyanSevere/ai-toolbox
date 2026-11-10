# Duplicates and ordering

The same item appears twice, or items arrive in an order the code did not expect:
repeated keys, a name listed twice, out-of-order events, sorted input that is not sorted.

Ask of the spec and the code:

- Can any list, map or stream hold the same item twice? Which copy wins, and is that
  stated or an accident of the code?
- Does a duplicate silently overwrite, get counted twice, or get refused?
- Does the result depend on input order? Should it?
- If output order matters, is it fixed, or does it depend on a dict, a directory listing
  or a set?

The spec's line for this category reads like:

- Duplicates and ordering: a name listed twice is refused naming it; output is sorted by name whatever the input order

Or, where neither can arise:

- Duplicates and ordering: N/A: the input is one scalar, so there is nothing to repeat or reorder

Each case in the line gets a test of its own: a duplicate fed in, and the same input in
two orders. A case the line does not name is named back, not tested.
