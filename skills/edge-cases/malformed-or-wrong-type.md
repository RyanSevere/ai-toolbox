# Malformed or wrong type

The input is there but wrong: text where a number belongs, a list where an object belongs,
invalid JSON or YAML, a bad encoding, a value outside the allowed set, a path that tries
to leave its directory.

Ask of the spec and the code:

- Where does each value come from? Anything read from a file, a request, an argument or
  another program can be malformed.
- What does the code do with the wrong type: refuse it naming the value, or carry on with
  a guess?
- Can a malformed value reach a path, a command or a query before it is checked?
- Is a parse failure ever reported as an empty or default result?

The spec's line for this category reads like:

- Malformed or wrong type: a non-numeric row raises naming the row; a path containing .. is refused before it is opened

Or, where every input is already typed:

- Malformed or wrong type: N/A: the only input is an enum checked by the caller's parser, which has its own tests

Each case in the line gets a test of its own, feeding the bad value in and checking the
refusal. A case the line does not name is named back, not tested.
