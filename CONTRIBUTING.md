# How to Modify the Specification

Welcome!  This document is a meta-discussion of how the specifications
should be safely altered when you want to include some amazing new
functionality.

Please remember that we're all trying to Make Things Better.  Respect,
consideration, kindness and humor have made this process
[fun](00-introduction.md#theme-song) and rewarding and we'd like to keep it
that way.  We're nice!

## Extension Design

There are several extension mechanisms in the spec; you should seek to use
them, or introduce new ones if necessary.

### Adding New Inter-Peer Messages

Unknown odd inter-peer messages are ignored, aka "it's OK to be odd!"
which makes more sense as you get to know me.

If your message is an enhancement, and you don't need to know if the other
side supports it, you should give it an odd number.  If it would be broken
if the other side doesn't support it (ie. Should Never Happen) give it an
even number.  Mistakes happen, and future versions of the software may well
not be tested against ancient versions.

If you want to experiment with new [message types](01-messaging.md#lightning-message-format) internally, I recommend
using 32768 and above (use even, so it will break if these accidentally
escape into the wild).

### Adding New Feature Bits

[Feature bits](01-messaging.md#the-init-message) are how you know a message is legal to send (see above), and
also they can be used to find appropriate peers.

Feature bits are always assigned in pairs, even if it doesn't make sense
for them to ever be compulsory.

Almost every spec change should have a feature bit associated; in the past
we have grouped feature bits, then we couldn't disable a single feature
when implementations turned out to be broken.

Usually feature bits are odd when first deployed, then some become even
when deployment is almost universal.  This often allows legacy code to be
removed, since you'll never talk to peers who can't deal with the feature.

If you want to experiment with new feature bits internally, I recommend
using 100 and above.

### Extending Inter-Peer Messages

The spec says that additional data in messages is ignored, which is another
way we can extend in future.  For BOLT 1.0, optional fields were appended,
and their presence flagged by feature bits.

The modern way to do this is to add a TLV to the end of a message.  This
contains optional fields: again, even means you will only send it if a
feature bit indicates support, odd means it's OK to send to old peers
(often making implementation easier, since peers can send them
unconditionally).

## Writing The Spec

The specification is supposed to be readable in text form, readable once
converted to HTML, and digestible by [tools/extract-formats.py].  In
particular, fields should use the correct type and have as much of their
structure as possible described explicitly (avoid 100*byte fields).

If necessary, you can modify that tool if you need strange formatting
changes.

The output of this tool is used to generate code for several
implementations, and it's also recommended that implementations quote the
spec liberally and have automated testing that the quotes are correct, as
[c-lightning
does](https://github.com/ElementsProject/lightning/blob/master/tools/check-bolt.c).

If your New Thing replaces the existing one, be sure to move the existing
one to a Legacy subsection: new readers will want to go straight to the
modern version.  Don't emulate the classic Linux snprintf 1.27 man page:

    RETURN VALUE
       If the output was truncated, the return value is -1, otherwise it is the
       number of characters stored, not including the terminating null.   (Thus
       until  glibc  2.0.6.  Since glibc 2.1 these functions return the  number
       of characters (excluding the trailing null) which would have been  writ‐
       ten to the final string if enough space had been available.)

Imagine the bitterness of someone who only reads the first sentence
assuming they have the answer they're looking for!  Someone who still
remembers it with bitterness 20 years on and digs it out of prehistory
to use it as an example of how not to write.  Yep, that'd be sad.

There's a [detailed style guide](.copy-edit-stylesheet-checklist.md) if you
want to know how to format things, and we run a spellchecker in our [CI
system](.travis.yml) as well so you may need to add lines to
[.aspell.en.pws].

### Writing The Requirements

Some requirements are obvious, some are subtle.  They're designed to walk
an implementer through the code they have to write, so write them as YOU
develop YOUR implementation.  Stick with `MUST`/`SHOULD`/`MAY` and `NOT`:
see [RFC 2119](https://www.ietf.org/rfc/rfc2119.txt)

Requirements are grouped into writer and reader, just as implementations
are.  Make sure you define exactly what a writer must do, and exactly what
a reader must do if the writer doesn't do that!  A developer should
never have to intuit reader requirements from writer ones.

Note that the data doesn't have requirements: don't say `foo MUST be 0`,
say `The writer MUST set foo to 0` and `The reader MUST fail the connection
if foo is not 0`.

Avoid the term `MUST check`: use `MUST fail the connection if` or `MUST
fail the channel if` or `MUST send an error message if`.

There's a subtle art here for future extensions: you might say `a writer
MUST set foo to 0` and not mention it in the reader requirements, but it's
better to say `a reader MUST ignore foo`.  A future version of the spec
might define when a writer sets `foo` to `1` and we know that old readers
will ignore it.

`MAY` is a hint as to what something is for: an implementation may do
anything not written in the spec anyway.  `MUST` is when not doing
something will break the protocol or security.

Requirements can be vague (eg. "in a timely manner"), but only as a last
resort admission of defeat.  If you don't know, what hope has the poor
implementer?

### Creating Test Vectors

For new low-level protocol constructions, test vectors are necessary.
These have traditionally been lines within the spec itself, but the modern
trend is to use JSON and separate files.  The intent is that they be
machine-readable by implementations.

For new inter-peer messages, a test framework is in development to simulate
entire conversations.

## Specification Modification Process

There is a [mailing
list](https://lists.linuxfoundation.org/mailman/listinfo/lightning-dev)
for larger feature discussion, a [GitHub
repository](https://github.com/lightningnetwork/lightning-rfc) for
explicit issues and pull requests, and a bi-weekly IRC meeting on
#lightning-dev on Freenode, currently held at 5:30am Tuesday, 
Adelaide/Australia timezone (eg. Tuesday 23rd July 2019 05:30 == Mon, 22
Jul 2019 20:00 UTC).

Spelling, typo and formatting changes are accepted once two contributors
ack and there are no nacks.  All other changes get approved and minuted at
the IRC meeting.  Protocol changes require two independent implementations
which successfully inter-operate; be patient as spec changes are hard to
fix later, so agreement can take some time.

In addition, there are occasional face-to-face invitation-only Summits
where broad direction is established.  These are amazing, and you should
definitely join us sometime.

We look forward to you joining us!
Your Friendly Lightning Developers.
