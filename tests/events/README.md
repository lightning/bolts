# Implementation Tests for Lightning Specifications

This directory contains conversation-style tests for Lightning
implementations.  The format is documented in
[tests/events/test-spec.md](events/test-spec.md), and the base driver for an
implementation is in the [tools/test-events.py](../tools/test-events.py).

To run the tests, you need to write a driver for your particular
implementation, like the one for
[c-lightning](../tools/test-events-clightning.py).  Then extract the
format of all messages into a file, like so:

	$ python3 tools/extract-formats.py 0*.md > format.csv

Finally, you can run a test like so:

	$ tools/test-events-clightning.py formats.csv tests/events/*.events

The `-v` option will give more verbose output, which is particularly
useful when debugging your test script.

Good luck!
Rusty.
