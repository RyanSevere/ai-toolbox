# A failed dependency or lookup

Something the code relies on does not answer: a network call times out, a service is
down, a command exits non-zero, a file cannot be read, a lookup finds nothing.

The rule for this category: unknown is not zero. A failed lookup must never produce a
value that reads as a healthy measurement.

Ask of the spec and the code:

- What does the code call that it does not control? Each one can fail.
- Does every outbound call have a timeout, and what happens when it fires?
- When a call fails, is the result an error, or a default like zero, empty, `false` or
  "ok" that looks like a real answer?
- Is "accepted the request" ever treated as "finished the work"?

The spec's line for this category reads like:

- A failed dependency or lookup: the lookup timing out raises naming the host; it never prints a count of zero

Or, where the code calls nothing outside itself:

- A failed dependency or lookup: N/A: the function is pure and reads only its arguments

Each case in the line gets a test of its own, with the dependency made to fail. A case
the line does not name is named back, not tested.
