# BOLT #41: Optimizing Bolt #11 encoding for Twitter

A simple and highly optimized encoding to embed Bolt 11 invoices inside tweets.

# Table of Contents

  * [Encoding Overview](#encoding-overview)
  * [Examples](#examples)
  * [Future Improvements](#future-improvements)

# Encoding Overview

The usual format for a Lightning invoice uses [bech32 encoding](https://github.com/bitcoin/bips/blob/master/bip-0173.mediawiki),
as specified in Bolt 11.

While bech32 has great properties for Bitcoin addresses, it has many shortcomings
for lightning invoices. The main issue is the size of the invoices; bech32 was
never designed to be a very compact encoding.

This is proving to be a major inconvenience for the lightning network's adoption.
Empirical evidence shows that most cryto-currency payments are done over the
decentralized network known as [Twitter](https://twitter.com). One severe limitation
of Twitter is that messages can be at most 280 characters long, and most Bolt 11
invoices are bigger than that when encoded using bech32.

Lightning needs a more compact encoding for invoices, that allows them to be sent
over tweets. The format we'll be using is based on [Twemoji](https://github.com/twitter/twemoji).

Twitter supports 3,245 different emojis as of 04-01-2020. We map every 11-bits value
to a specific emoji in that set. This provides an encoding 2,2 times more compact than
bech32. And an additional benefit is that it looks much better.

# Examples

Let's consider the following invoice: "On mainnet, with fallback (p2wsh) address
bc1qrp33g0q5c5txsp9arysrx4k6zdkfs4nce4xj0gdcccefvpysxf3qccfmv3 and a minimum htlc cltv expiry of 12".

The corresponding Bolt 11 invoice is:

```text
lnbc20m1pvjluezcqpvpp5qqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypqhp58yjmdan79s6qqdhdzgynm4zwqd5d7xmw5fk98klysy043l2ahrqsfp4qrp33g0q5c5txsp9arysrx4k6zdkfs4nce4xj0gdcccefvpysxf3q90qkf3gd7fcqs0ewr7t3xf72ptmc4n38evg0xhy4p64nlg7hgrmq6g997tkrvezs8afs0x0y8v4vs8thwsk6knkvdfvfa7wmhhpcsxcqw0ny48
```

Unfortunately, it's 295 characters long. It doesn't fit in a tweet.
Our poor user will probably never receive his payment, as it will be impossible
to share the invoice over Twitter.

However, with our proposed encoding, the same invoice becomes:

```text
🇪🇬🍅👩‍❤️‍👩💃🏼🇧🇱🇨🇳🏂🏿🅾🇨🇰👉🏿🇧🇬🍇📣🇯🇴🀄👩🏻‍🎓🇫🇮👨🇧🇶🎅🏾🇦🇩🀄🇭🆖🇭🇺👱🏿‍♀️🇧🏃🏻‍♀️🏃🏻‍♀️🇦🇽💛🏄🏽👩🏿‍🤝‍👨🏾🗞🕞🌧👱🏽‍♀️🇬🇭🖥🇹🇭👰🏾🏰📖👦🏼🚜🗝🏅📼🙋🏽‍♂️👩🏿‍🔬🇻🇺🐪🙇🏼‍♂️👨🏼‍🎨👩🏻‍🔬🏋🏻‍♂️🏧👋🏻👌🏽🎦👶🏼🏇🏿🕠🏌🏾‍♂️👩🏽‍✈️👩🏻‍🌾👨🏻‍🏫🖤👭🏽🈯💁🏿‍♀️👩🏾‍🌾👶🏿👰🏻🍾🔅👩🏿👩🏻‍🎤🇹🇬🈲🆔🙍🏻🔠🏭🚟📔🇨🇮🌶🚪📹🏣👱🏾👨‍🍳🌝📺🔬👩🏼‍🦰🖇🌔🙇🏻👱🏼‍♂️👩🏾‍🤝‍👩🏿🙅🚆👦🏾🌏🙄📮🍗🏃🏼🙇🏻‍♀️🇨🇫🕙🇬🇹🐐👩🏻‍💼💰🕥💇🏿‍♂️🏝👍🏽👩‍👧🎵👮🏿😍🇬🇳🇦🇷🀄
```

It's only 128 emojis long and provides a beautiful tweet.

# Future Improvements

As Twitter adds support for more emojis, our encoding becomes more compact.
Once Twitter supports more than 4,096 emojis, our words can become 12 bits long
instead of 11 bits long, giving us an even better compression ratio.

Thanks to that compression boost, users could even share invoices containing
rendezvous onions. This is a killer feature of lightning: amazing privacy thanks
to rendezvous routing, without the burden of using Tor or setting up a node thanks
to a tight integration between your wallet and your Twitter account.

But we need to overcome one limitation first. Twitter currently counts one emoji
as if it were two characters. Our encoding is thus twice less efficient than it
could be if Twitter were to fix that annoying bug. We kindly ask the users of the
Twitter decentralized network to use their stake to vote for a protocol change,
that would count emojis as single characters in tweets. The future UX of the
lightning network depends on you!
