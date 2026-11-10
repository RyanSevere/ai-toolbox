# Empty or missing

Something the code expects is not there: an empty file, list, string or table; a field,
key, argument or setting left out; a file that does not exist.

Ask of the spec and the code:

- What does each input look like when it holds nothing? Is empty a valid reading, or a
  sign something upstream failed?
- What happens when an optional field is left out, and when a required one is?
- Does empty ever produce output that looks like a healthy result, such as a zero count
  or an empty report that reads as "all clear"?
- Is an empty secret or setting treated as missing? It must be.

The spec's line for this category reads like:

- Empty or missing: an empty table gives a count of zero, which is a real reading; a missing table raises naming it

Or, where nothing can be empty or missing:

- Empty or missing: N/A: every input is a constant compiled into the module

Each case in the line gets a test of its own. A case the line does not name is named
back, not tested.
