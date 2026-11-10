# Boundary values

The edges of a valid range: zero, one, the maximum, one past the maximum, the first and
last item, the empty-to-one transition, a limit reached exactly.

Ask of the spec and the code:

- Where does each number, size, count or index have a limit, stated or implied?
- What happens exactly at the limit, one below it and one above it?
- Is each comparison `<` or `<=`, and does the spec say which?
- Do time limits, timeouts and dates have edges, such as midnight, a deadline reached
  exactly, or a cap of zero seconds?

The spec's line for this category reads like:

- Boundary values: a page of exactly 50 items has no next page; 51 items gives a second page of one

Or, where there is no limit to test:

- Boundary values: N/A: the input is a single flag with two values, both covered elsewhere

Each case in the line gets a test of its own: at the edge, and on each side of it. A
case the line does not name is named back, not tested.
