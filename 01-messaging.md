# BOLT #1: Base Protocol

# BOLT #1: 基本プロトコル

## Overview

## 概要

This protocol assumes an underlying authenticated and ordered transport mechanism that takes care of framing individual messages.
[BOLT #8](08-transport.md) specifies the canonical transport layer used in Lightning, though it can be replaced by any transport that fulfills the above guarantees.

このプロトコルは、個々のメッセージが従う基礎的な認証および整列転送メカニズムがあることを仮定しています。
[BOLT #8](08-transport.md) はライトニングネットワークで使われる標準的な転送レイヤーの記述に特化しており、上記の保証を満たすどんな転送方法で下位層を置き換えても問題ないように設計されています。

The default TCP port is 9735. This corresponds to hexadecimal `0x2607`, the unicode code point for LIGHTNING.<sup>[1](#reference-1)</sup>

デフォルトのTCPポートは9735番を使います。これは、16進数での `0x2607` に対応し、LIGHTNINGに対するユニコードの符号位置になっています。<sup>[1](#reference-1)</sup>

All data fields are big-endian unless otherwise specified.

全てのデータフィールドは特に指定がない限りビッグエンディアンです。

## Table of Contents
  * [Connection handling and multiplexing](#connection-handling-and-multiplexing)
  * [Lightning Message Format](#lightning-message-format)
  * [Setup Messages](#setup-messages)
    * [The `init` message](#the-init-message)
    * [The `error` message](#the-error-message)
  * [Control Messages](#control-messages)
    * [The `ping` and `pong` messages](#the-ping-and-pong-messages)
  * [Acknowledgements](#acknowledgements)
  * [References](#references)
  * [Authors](#authors)

## 目次
  * [コネクションハンドリングと多重化](#connection-handling-and-multiplexing)
  * [ライトニングメッセージフォーマット](#lightning-message-format)
  * [セットアップメッセージ](#setup-messages)
    * [ `init` メッセージ](#the-init-message)
    * [ `error` メッセージ](#the-error-message)
  * [コントロールメッセージ](#control-messages)
    * [ `ping` メッセージと `pong` メッセージ](#the-ping-and-pong-messages)
  * [謝辞](#acknowledgements)
  * [参考文献](#references)
  * [著者](#authors)

## Connection handling and multiplexing

## コネクションハンドリングと多重化

Implementations MUST use one connection per peer, channel messages (which include a channel id) being multiplexed over this single connection.

１つのピアおよびチャネルメッセージ(チャネルidを含む)に対して１つのコネクションを使うように実装しなければいけません。
チャネルメッセージは１つのコネクション上で多重化されて実装されなければいけません。


## Lightning Message Format

## ライトニングメッセージフォーマット

After decryption, all lightning messages are of the form:

全てのライトニングメッセージは復号後に以下のフォーマッになります。

1. `type`: 2 byte big-endian field indicating the type of the message.
2. `payload`: variable length payload. It comprises the remainder of
   the message and conforms to the format matching the `type`.

1. `type`: メッセージの種類を示す２バイトフィールド(ビッグエンディアン)
2. `payload`: 可変長ペイロード。これはメッセージからtypeを除いた部分であり、 `type` にマッチしたフォーマットに従います。

The `type` field indicates how to interpret the `payload` field.
The format for each individual type is specified in a specification in this repository.
The type follows the _it's ok to be odd_ rule, so nodes MAY send odd-numbered types without ascertaining that the recipient understands it. 
A node MUST NOT send an evenly-typed message not listed here without prior negotiation.
A node MUST ignore a received message of unknown type, if that type is odd.
A node MUST fail the channels if it receives a message of unknown type, if that type is even.

`type` フィールドは `payload` フィールドを解釈する方法を示します。
個々のtypeに対するフォーマットはこのリポジトリの仕様の中で規定されています。
typeフィールドは _it's ok to be odd_ ルールに従っています。
このため、ノードは受金者がそれに対応しているかどうかを把握することなく奇数番号のtypeを送信するかもしれません。
ノードは事前の確認なしにここに挙げられていない偶数番号のtypeを送信してはいけません。
もしtypeが奇数番号であれば、ノードは知らないタイプのメッセージを無視しなければいけません。
もしtypeが偶数番号であれば、ノードは知らないタイプのメッセージを受け取ると同時にチャネルを停止しなければいけません。

The messages are grouped logically into 4 groups by their most significant set bit:

メッセージは、最重要ビットによって論理的には以下の４つのグループに分けられます。

 - Setup & Control (types `0`-`31`): messages related to connection setup, control, supported features, and error reporting. These are described below.
 - Channel (types `32`-`127`): comprises messages used to setup and tear down micropayment channels. These are described in [BOLT #2](02-peer-protocol.md).
 - Commitment (types `128`-`255`): comprises messages related to updating the current commitment transaction, which includes adding, revoking, and settling HTLCs, as well as updating fees and exchanging signatures. These are described in [BOLT #2](02-peer-protocol.md).
 - Routing (types `256`-`511`): node and channel announcements, as well as any active route exploration. These are described in [BOLT #7](07-routing-gossip.md).

 - セットアップ & コントロール (type `0`-`31`): コネクションセットアップ、コントロール、サポートしている機能、エラーレポーティングに関連したメッセージ。詳細は以下に記載。
 - チャネル (types `32`-`127`): マイクロペイメントチャネルのオープンとクローズに使われるメッセージが含まれています。詳細は [BOLT #2](02-peer-protocol.md) に記載。
 - コミットメント (types `128`-`255`: 現在のコミットメントトランザクションの更新に関連したメッセージが含まれています。コミットメントトランザクションの更新には、手数料の更新、署名の交換だけでなく、追加、取り消し、HTLCの確定(ブロードキャスト)も含まれます。詳細は [BOLT #2](02-peer-protocol.md) に記載。
 - ルーティング (types `256`-`511`): アクティブなルート探索だけでなく、ノードやチャネル関係の通知も含まれます。詳細は [BOLT #7](07-routing-gossip.md) に記載。

The size of the message is required to fit into a 2 byte unsigned int by the transport layer, therefore the maximum possible size is 65535 bytes.
A node MUST ignore any additional data within a message, beyond the length it expects for that type.
A node MUST fail the channels if it receives a known message with insufficient length for the contents.

メッセージのサイズはトランスポート層の制限により符号なし２バイト整数に収まる必要があります。
このため、最大サイズは65535バイトになります。
ノードはメッセージ内にあるtypeごとに想定される長さよりも長い食み出たデータは無視しなければいけません。
また、もし規定に対して不十分な長さの既知メッセージを受け取った場合、ノードはチャネルを停止しなければいけません。


### Rationale

### 合理性

The standard endian of `SHA2` and the encoding of Bitcoin public keys
are big endian, thus it would be unusual to use a different endian for
other fields.

標準的な `SHA2` やBitcoinの公開鍵のエンコーディングはビッグエンディアンです。
このため、ライトニングネットワークでの他のフィールドで他のエンコーディングを使うことは統一性に欠けると思われます。

Length is limited to 65535 bytes by the cryptographic wrapping, and
messages in the protocol are never more than that length anyway.

長さは暗号学的変換によって65535バイトに制限され、プロトコル内のメッセージはこの長さを超えることはあり得ません。

The "it's OK to be odd" rule allows for future optional extensions
without negotiation or special coding in clients.  The "ignore
additional data" rule similarly allows for future expansion.

"it's OK to be odd" ルールは、将来的にクライアントサイドでの特別な実装を可能とし調整なしに拡張可能にするためにあります。
"ignore additional data" ルールも同様に将来における拡張性のために設けられています。

Implementations may prefer to have message data aligned on an 8 byte
boundary (the largest natural alignment requirement of any type here),
but adding a 6 byte padding after the type field was considered
wasteful: alignment may be achieved by decrypting the message into
a buffer with 6 bytes of pre-padding.

実装としては、８バイト境界アラインメント(ここにあるtypeで最も大きく自然なアラインメント制約)でのメッセージデータを持つのが好ましいかもしれません。
もしtypeフィールドが無駄だと考えられる場合は６バイトパディングを追加します。
つまり、アラインメントはメッセージを復号し６バイトのパディングとともにバッファに入れることで行われる可能性があります。

## Setup Messages

## セットアップメッセージ

### The `init` message

### `init` メッセージ

Once authentication is complete, the first message reveals the features supported or required by this node, even if this is a reconnection.
Odd features are optional, even features are compulsory (_it's OK to be odd_).
The meaning of these bits will be defined in the future.

認証が完了すると、これが再接続だとしてもこのノードでサポートしているまたは必須となっているfeatureが最初のメッセージで通知されます。
奇数番号featureは任意、偶数番号featureは強制です( _it's OK to be odd_ を意味します) 。
これらのビットの意味は将来的に以下で定義されます。

1. type: 16 (`init`)
2. data:
   * [2:gflen]
   * [gflen:globalfeatures]
   * [2:lflen]
   * [lflen:localfeatures]

The 2 byte `gflen` and `lflen` fields indicate the number of bytes in the immediately following field.

２バイトの `gflen` フィールドと `lflen` フィールドはすぐあとに続くフィールドのバイト長を示しています。

#### Requirements

#### 要件

The sending node MUST send `init` as the first lightning message for any
connection.
The sending node SHOULD use the minimum lengths required to represent
the feature fields.  The sending node MUST set feature bits
corresponding to features it requires the peer to support, and SHOULD
set feature bits corresponding to features it optionally supports.

メッセージを送るノードは `init` メッセージを最初のライトニングメッセージとして送らなければいけません。
メッセージを送るノードはfeatureフィールドを表す最小限の長さを使うべきです。
このノードは、ピアがサポートする必要があるfeatureに対応したfeatureビットはセットしなければいけません。また、任意にサポートするfeatureに対応したfeatureビットはセットしたほうが望ましいです。

The receiving node MUST fail the channels if it receives a
`globalfeatures` or `localfeatures` with an even bit set which it does
not understand.

もし理解できない偶数ビットを伴った `globalfeatures` または `localfeatures` を受け取った場合、メッセージを受け取ったノードはチャネルを停止しなければいけません。

Each node MUST wait to receive `init` before sending any other messages.

それぞれのノードは他のメッセージを送る前に `init` メッセージを受け取るまで待たなければいけません。

#### Rationale

#### 合理性

The even/odd semantic allows future incompatible changes, or backward
compatible changes.  Bits should generally be assigned in pairs, so
that optional features can later become compulsory.

偶数番号featureまたは奇数番号featureの意味付けは、前方互換性のない変更および後方互換性のある変更を可能にします。
一般的に、任意のfeatureがのちに強制的なものにできるように、ビットはペアになるように揃えられているほうがよいです。

Nodes wait for receipt of the other's features to simplify error
diagnosis where features are incompatible.

featureに互換性がないと誤判断しないように、ノードは他のfeatureの状況も見ます。

The feature masks are split into local features which only affect the
protocol between these two nodes, and global features which can affect
HTLCs and thus are also advertised to other nodes.

featureマスクは２つのノード間でのプロトコルにのみ影響を与えるような局所的featureとHTLCに影響を与え他のノードにも通知されるような全域的featureに分けます。

### The `error` message

### `error` メッセージ

For simplicity of diagnosis, it is often useful to tell the peer that something is incorrect.

判断の簡易化のため、ピアに何かが間違っていますよと頻繁に教えてあげることは意味があります。

1. type: 17 (`error`)
2. data:
   * [32:channel-id]
   * [2:len]
   * [len:data]

The 2-byte `len` field indicates the number of bytes in the immediately following field.

２バイトの `len` フィールドはすぐあとに続くフィールドのバイト長を示します。

#### Requirements

#### 要件

The channel is referred to by `channel-id` unless `channel-id` is zero (ie. all bytes zero), in which case it refers to all channels.

`channel-id` フィールドがゼロ(つまり、全てのバイトがゼロ)でない限り、チャネルは `channel-id` フィールドによって指定されます。 `channel-id` フィールドがゼロのときは全てのチャネルのことを意味します。

A node SHOULD send `error` for protocol violations or internal
errors which make channels unusable or further communication unusable.
A node MAY send an empty [data] field.  A node sending `error` MUST
fail the channel referred to by the error message, or if `channel-id` is zero, it MUST
fail all channels and MUST close the connection.
A node MUST set `len` equal to the length of `data`.  A node SHOULD include the raw, hex-encoded transaction in reply to a `funding_created`, `funding_signed`, `closing_signed` or `commitment_signed` message when failure was caused by an invalid signature check.

ノードは、プロトコル違反であったり、チャネルを使えなくするまたは追加のコミュニケーションを不可能にする内部エラーに対して `error` メッセージを送るべきです。
ノードはdataフィールドが空のerrorメッセージを送る可能性もあります。
`error` メッセージを送るノードは、errorメッセージによって指定されるチャネルを停止しなければいけません。
また、もし `channel-id` フィールドがゼロであれば全てのチャネルを停止し、そのコネクションを閉じなければいけません。
ノードは `len` フィールドに `data` フィールドの長さと等しい値を入れなければいけません。
もし不正な署名チェックが原因で失敗した時には、ノードは、`funding_created`メッセージ、`funding_signed`メッセージ、`closing_signed`メッセージ、`commitment_signed`メッセージに対する返答に１６進数のrawトランザクションを含めるべきです。

A node receiving `error` MUST fail the channel referred to by the message,
or if `channel-id` is zero, it MUST fail all channels and MUST close the connection.  If no existing channel is referred to by the message, the receiver MUST ignore the message. A receiving node MUST truncate
`len` to the remainder of the packet if it is larger.

`error` メッセージを受け取ったノードは、そのメッセージで指定されているチャネルを停止しなければいけません。
もし `channel-id` フィールドがゼロであれば、全てのチャネルをを停止しそのコネクションを閉じなければいけません。
メッセージで指定されているチャネルが存在しない場合、そのメッセージを無視しなければいけません。
もし受け取ったerrorメッセージがより大きいものであれば、 `len`フィールドで指定されている長さにパケットを切り落として使わなければいけません。

A receiving node SHOULD only print out `data` verbatim if the string is composed solely of printable ASCII characters.
For referece, the printable character set includes byte values 32 through 127 inclusive.

もし `data` フィールドの中の文字列が単に表示可能なASCII文字で構成されている場合、受け取ったノードは `data` フィールドの中身を言葉通りに表示するだけするべきです。

#### Rationale

#### 合理性

There are unrecoverable errors which require an abort of conversations;
if the connection is simply dropped then the peer may retry the
connection.  It's also useful to describe protocol violations for
diagnosis, as it indicates that one peer has a bug.

単にコネクションが切れてしまったのであればピアが再度コネクションを確立しなおせばいいのですが、それもできないようなコミュニケーションを諦めざるをえない回復不可能なエラーはありえます。
またこのような状況はピアにバグがあることを示すこともあるため、診断のためにプロトコル違反があったときの対応方法を決めておくことは有用です。

It may be wise not to distinguish errors in production settings, lest
it leak information, thus the optional data field.


## Control Messages

## コントロールメッセージ

### The `ping` and `pong` messages

### `ping`メッセージと`pong`メッセージ

In order to allow for the existence of very long-lived TCP connections, at
times it may be required that both ends keep alive the TCP connection at the
application level.  Such messages also allow obsfusation of traffic patterns.

とても長く張られ続けるTCPコネクションを許可するために、両端ノードが時にはアプリケーションレベルでTCPコネクションをアクティブにし続ける必要があるかもしれません。
そのようなメッセージはトラフィックパターンを読みにくくしてしまう可能性もあります。

1. type: 18 (`ping`)
2. data: 
    * [2:num_pong_bytes]
    * [2:byteslen]
    * [byteslen:ignored]

The `pong` message is to be sent whenever a `ping` message is received. It
serves as a reply, and also serves to keep the connection alive while
explicitly notifying the other end that the receiver is still active. Within
the received `ping` message, the sender will specify the number of bytes to be
included within the data payload of the `pong` message

`pong` メッセージは `ping` メッセージを受け取った時にいつでも送られます。
これは返答として送られるものですが、また受信側がまだアクティブであることを他方に明示的に通知することでコネクションがアクティブであると通知する意味もあります。

1. type: 19 (`pong`)
2. data:
    * [2:byteslen]
    * [byteslen:ignored]

#### Requirements

#### 要件

A node sending `pong` or `ping` SHOULD set `ignored` to zeroes, but MUST NOT
set `ignored` to sensitive data such as secrets, or portions of initialized
memory.

`pong` メッセージまたは `ping` メッセージを送ったノードは `ignored` フィールドにゼロを入れるべきであり、 `ignored` フィールドに機密情報や初期化されたメモリの位置などセンシティブなデータを入れるべきではありません。

A node SHOULD NOT send `ping` messages more often than once every 30 seconds,
and MAY terminate the network connection if it does not receive a corresponding
`pong`: it MUST NOT fail the channels in this case.

ノードは `ping` メッセージを３０秒毎に１回以上送るべきではありません。
pingメッセージに対応した `pong` メッセージがない場合はコネクションを閉じる可能性があります。
この場合チャネルを停止してはいけません。

A node receiving a `ping` message SHOULD fail the channels if it has received
significantly in excess of one `ping` per 30 seconds, otherwise if
`num_pong_bytes` is less than 65532 it MUST respond by sending a `pong` message
with `byteslen` equal to `num_pong_bytes`, otherwise it MUST ignore the `ping`.

もし３０秒毎に１つよりも著しく多くの `ping` メッセージを受け取った場合、 `ping` メッセージを受け取ったノードはチャネルを停止するべきです。
もしそうでない場合、 `num_pong_bytes` フィールドが65532より小さければそのノードは `num_pong_bytes` フィールドと等しい `byteslen` を持つ `pong` メッセージを送ることで返答しなければいけません。また、 `num_pong_bytes` フィールドが65532以上であれば `ping` メッセージを無視しなければいけません。

A node receiving a `pong` message MAY fail the channels if `byteslen` does not
correspond to any `ping` `num_pong_bytes` value it has sent.

もし `byteslen` フィールドが過去に送ったどの `ping` メッセージの `num_pong_bytes` フィールドにも一致しなければ `pong` メッセージを受け取ったノードはチャネルを停止する可能性があります。


### Rationale

### 合理性

The largest possible message is 65535 bytes, thus maximum sensible `byteslen`
is 65531 to account for the type field (`pong`) and `bytelen` itself.  This
gives us a convenient cutoff for `num_pong_bytes` to indicate that no reply
should be sent.

最も大きいメッセージは65535バイトであるため、 `pong` メッセージのtypeフィールドと `bytelen` フィールドそのものを計算に入れると最大の `byteslen` フィールドの値は65531です。
これは、pingメッセージへの返答としてpongメッセージを送るべきではない場合の `nom_pong_bytes` フィールドに対する基準になります。

Connections between nodes within the network may be very long lived as payment
channels have an indefinite lifetime. However, it's likely that for a
significant portion of the life-time of a connection, no new data will be
exchanged. Additionally, on several platforms it's possible that Lightning
clients will be put to sleep without prior warning.  As a result, we use a
distinct ping message in order to probe for the liveness of the connection on
the other side, and also to keep the established connection active. 

ペイメントチャネルはいつまで使われるかわからないため、ノード間のコネクションはとても長く維持される可能性があります。
しかし、きっとコネクションを張っているかなりの期間で新しいデータは交換されないです。
しかも、いくつかのプラットフォームではライトニングクライアントは事前予告なく睡眠状態に陥る可能性もあります。
結果として、相手サイドとのコネクションがアクティブであるかを調べるためやすでに確立されたコネクションをアクティブに保つために、一個一個が離れたpingメッセージを使うことになります。

Additionally, the ability for a sender to request that the receiver send a
response with a particular number of bytes enables nodes on the network to
create _synthetic_ traffic. Such traffic can be used to partially defend
against packet and timing analysis as nodes can fake the traffic patterns of
typical exchanges, without applying any true updates to their respective
channels. 

加えて、送信者が受信者に特定のバイト長のレスポンスを要求することは、ネットワーク上のノードに _偽の_ トラフィックを作らせることになります。
それぞれのチャネルに対してなんの更新もすることなくノードの典型的なトラフィックパターンを偽ることができるので、部分的にはパケットおよびタイミング分析からノードを守るために使うことができます。

When combined with the onion routing protocol defined in
[BOLT #4](https://github.com/lightningnetwork/lightning-rfc/blob/master/04-onion-routing.md),
careful statistically driven synthetic traffic can serve to further bolster the
privacy of participants within the network.

[BOLT #4](https://github.com/lightningnetwork/lightning-rfc/blob/master/04-onion-routing.md) で定義されているオニオンルーティングプロトコルと結びつけることで、注意深く統計的に作られた偽りのトラフィックはネットワーク内にいる参加者のプライバシーをさらに強化することになります。

Limited precautions are recommended against `ping` flooding, however some
latitude is given because of network delays.  Note that there are other methods
of incoming traffic flooding (eg. sending odd unknown message types, or padding
every message maximally).

いくつかの注意は `ping` メッセージの濫用に対する対策として推奨されるものですが、ネットワーク遅延を防止するためいくらかの自由度が与えられています。
入ってくるトラフィックの濫用に対しては他にも方法はあることを強調しておきます(例えば、奇数番号の未知メッセージtypeを送ることや全てのメッセージに対して最大限パディングをするなど)。

Finally, the usage of periodic `ping` messages serves to promote frequent key
rotations as specified within [BOLT #8](https://github.com/lightningnetwork/lightning-rfc/blob/master/08-transport.md).

最後に、周期的な `ping` メッセージの使用は [BOLT #8](https://github.com/lightningnetwork/lightning-rfc/blob/master/08-transport.md) で記載しているように頻繁な鍵の使い回しに繋がります。


## Acknowledgements

## 謝辞

TODO(roasbeef); fin


## References

## 参考文献
1. <a id="reference-2">http://www.unicode.org/charts/PDF/U2600.pdf</a>

## Authors

## 著者

FIXME

![Creative Commons License](https://i.creativecommons.org/l/by/4.0/88x31.png "License CC-BY")
<br>
This work is licensed under a [Creative Commons Attribution 4.0 International License](http://creativecommons.org/licenses/by/4.0/).
