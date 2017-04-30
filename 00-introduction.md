# BOLT #0: Introduction and Index

# BOLT #0: イントロダクションと索引

Welcome, friend!  These Basis of Lightning Technology (BOLT) documents
describe a layer-2 protocol for off-chain bitcoin transfer by mutual
cooperation, relying on on-chain transactions for enforcement if
necessary.

ようこそ、みなさん！これらのライトニングテクノロジー基盤(Basis of Lightning Technology, BOLT)に関するドキュメントは、相互協力によるオフチェーンbitcoin送金のためのレイヤー２プロトコルです。基本的にオフチェーンで行われ、オンチェーントランザクションは必要に応じて送金を執行するときに使われます。

Some requirements are subtle; we have tried to highlight motivations
and reasoning behind the results you see here.  I'm sure we've fallen
short: if you find any part confusing, or wrong, please contact us and
help us improve.

いくつかの要件は分かりにくく捉えにくいものではありますが、ドキュメントにあるもののモチベーションや理由がどんなものなのかが分かりやすくなるように試行錯誤をしてきました。まだまだ分かりにくいところがあると思いますので、もし混乱した点、間違っている点がありましたら我々にご連絡いただき、よりよいものに改善していけるようご協力をお願いします。

This is version 0.

このドキュメントのバージョンは０です。

1. [BOLT #1](01-messaging.md): Base Protocol
2. [BOLT #2](02-peer-protocol.md): Peer Protocol for Channel Management
3. [BOLT #3](03-transactions.md): Bitcoin Transaction and Script Formats
4. [BOLT #4](04-onion-routing.md): Onion Routing Protocol
5. [BOLT #5](05-onchain.md): Recommendations for On-chain Transaction Handling
6. [BOLT #6](06-irc-announcements.md): Interim Node and Channel Discovery
7. [BOLT #7](07-routing-gossip.md): P2P Node and Channel Discovery
8. [BOLT #8](08-transport.md): Encrypted and Authenticated Transport
9. [BOLT #9](09-features.md): Assigned Feature Flags


1. [BOLT #1](01-messaging.md): 基本プロトコル
2. [BOLT #2](02-peer-protocol.md): チャネル管理のためのピア間プロトコル
3. [BOLT #3](03-transactions.md): BitcoinトランザクションとScriptフォーマット
4. [BOLT #4](04-onion-routing.md): オニオンルーティングプロトコル
5. [BOLT #5](05-onchain.md): オンチェーントランザクションを操作するための推奨案
6. [BOLT #6](06-irc-announcements.md): 暫定ノードとチャネル探索
7. [BOLT #7](07-routing-gossip.md): P2Pノードとチャネル探索
8. [BOLT #8](08-transport.md): 認証および暗号済み転送
9. [BOLT #9](09-features.md): 割り当て済み特徴フラグ

## Glossary and Terminology Guide

## 用語集と用語説明

* *Funding Transaction*:
   * The on-chain, irreversible transaction which pays to both peers
         on a channel.  Thus it can only be spent by mutual consent.


* *Funding Transaction(ファンディングトランザクション)*:
   * チャネル上で両方のピアに対する支払いをするための不可逆なオンチェーントランザクション(2-of-2マルチシグアドレスへの送金)。
     相互同意によってのみ資金を移すことができます。


* *Channel*:
   * A fast, off-chain method of mutual exchange between two *peers*.
         To move funds, they exchange signatures for an updated *commitment
         transaction*.


* *チャネル*:
   * ２つの *ピア* 間で構成される素早くオフチェーンで通貨を相互交換するための方法。
     資金を移動させるために、更新される *コミットメントトランザクション* に対する署名を２つのピアで交換します。


* *Commitment Transaction*:
   * A transaction which spends the funding transaction; each peer
         holds a signature from the other peer for this transaction, so it
         always has a commitment transaction it can spend.  After a new
         commitment transaction is negotiated, the old one is *revoked*.


* *Commitment Transaction(コミットメントトランザクション)*:
   * ファンディングトランザクションを使うためのトランザクション。
     それぞれのピアは、相手のピアからもらったこのコミットメントトランザクション用の署名を保持しておきます。
     このため、この署名にはそれと紐づいて使用できるコミットメントトランザクションが常にあります。
     新しいコミットメントトランザクションが２つのピア間で作られると、古いコミットメントトランザクションは *無効* になります。


* *HTLC*: Hashed Time Locked Contract.
   * A conditional payment between two peers: the recipient can spend
         the payment by presenting its signature and a *payment preimage*,
         otherwise the payer can cancel the contract by spending it after
         a given time.  These are implemented as outputs from the
         *commitment transaction*.


* *HTLC*: Hashed Time Locked Contract(資金のロック期限が設けられたハッシュを伴う契約)
   * ２つのピア間の条件付き支払い。
     受金者は署名と *ペイメントプレイメージ* を提示することでこの支払いを使うことができ、また支払者はあらかじめ決められた期限以降であればこの契約をキャンセルすることができます。
     これらは *コミットメントトランザクション* のアウトプットとして実装されます。


* *Payment hash, payment preimage*:
   * The HTLC contains the payment hash, which is the hash of the
         payment preimage.  Only the final recipient knows the payment
         preimage; thus when it reveals the preimage to collect funds is
         considered proof that it received the payment.


* *Payment hash, payment preimage(ペイメントハッシュ、ペイメントプレイメージ)*:
   * HTLCにはペイメントハッシュが含まれています。
     このペイメントハッシュはペイメントプレイメージのハッシュ値です。
     最終的な受金者だけがペイメントプレイメージを知っています。
     受金者が資金を受け取るためにはこのプレイメージを公開する必要があるため、このプレイメージが公開されているということは受金者が支払いを受け取ったことの証明と考えられます。


* *Commitment revocation key*:
   * Every *commitment transaction* has a unique *commitment revocation key*
         value which allows the other peer to spend all outputs
         immediately: revealing this key is how old commitment
         transactions are revoked.  To do this, each output refers to the
         commitment revocation pubkey.


* *Commitment revocation key(コミットメント取り消し鍵)*:
   * 全ての *コミットメントトランザクション* には一意の *コミットメント取り消し鍵* が紐付いています。
     相手のピアはこの鍵を使うことで全てのアウトプットを直ちに使うことができます。
     つまり、この鍵の公開は全てのコミットメントトランザクションの取り消しを意味します。
     これを行うために、それぞれのアウトプットはコミットメント取り消し鍵に対応するコミットメント取り消し公開鍵を参照しています。


* *Per-commitment secret*:
   * Every commitment derives its keys from a *per-commitment secret*,
     which is generated such that the series of per-commitment secrets
     for all previous commitments can be stored compactly.


* *Per-commitment secret(個別コミットメントシークレット)*:
   * 全てのコミットメントは *個別コミットメントシークレット* から導出された鍵と紐付きます。
     このシークレットを使うことで、以前の全コミットメントに対する複数の個別コミットメントシークレットをコンパクトに保存できるようになっています。


* *Mutual Close*:
   * A cooperative close of a channel, by broadcasting an unconditional
         spend of the *funding transaction* with an output to each peer
         (unless one output is too small, and thus is not included).


* *Mutual Close(相互的クローズ)*:
   * チャネルの協力的クローズ。
     これは *ファンディングトランザクション* の無条件で使用するトランザクションのブロードキャストによって行われます。
　　 このトランザクションにはそれぞれのピアへのアウトプット(アウトプットの中にとても小さい金額のものがなければ。もしあれば片方だけ。)を持ちます。


* *Unilateral Close*:
   * An uncooperative close of a channel, by broadcasting a
         *commitment transaction*.  This transaction is larger (ie. less
         efficient) than a mutual close transaction, and the peer whose
         commitment is broadcast cannot access its own outputs for some
         previously-negotiated duration.


* *Unilateral Close(一方的なクローズ)*:
   * チャネルの非協力的なクローズ。
     これは *コミットメントトランザクション* をブロードキャストすることで行われます。
     このトランザクションは相互的クローズのトランザクションと比べるとサイズが大きいトランザクション(つまり、非効率的)で、コミットメントをブロードキャストしたピアは事前に決められた期日まで自身のアウトプットにアクセスできません。


* *Revoked Transaction Close*:
   * An invalid close of the channel, by broadcasting a revoked
         *commitment transaction*.  Since the other peer knows the
         *commitment revocation secret key*, it can create a *penalty transaction*.


* *Revoked Transaction Close(取り消し済みトランザクションのクローズ)*:
   * チャネルの不正なクローズ。
     これは、取り消された *コミットメントトランザクション* がブロードキャストされることによって行われます。
     ブロードキャストされた相手のピアが *コミットメント取り消し秘密鍵* を知っていれば、このピアは *ペナルティートランザクション* を作ることができます。


* *Penalty Transaction*:
   * A transaction which spends all outputs of a revoked commitment
         transaction, using the *commitment revocation secret key*.  A peer uses this
         if the other peer tries to "cheat" by broadcasting a revoked
         *commitment transaction*.


* *Penalty Transaction(ペナルティートランザクション)*:
   * 取り消し済みコミットメントトランザクションの全てのアウトプットを使うトランザクション。
     このトランザクションの作成時に *コミットメント取り消し秘密鍵* を使います。
     もし相手のピアが取り消し済み *コミットメントトランザクション* をブロードキャストして "ズル" をしようとする場合にこれを使います。


* *Commitment Number*:
   * A 48-bit incrementing counter for each *commitment transaction*; they
         are independent for each peer in the channel, and start at 0.


* *Commitment Number(コミットメント番号)*:
   * *コミットメントトランザクション* それぞれに対して順番に振られる４８ビットの番号。
     このカウンターは０から始まり、チャネルの中でそれぞれのピアごとに独立に持つ番号です。


* *It's ok to be odd*:
   * A rule applied to some numeric fields that indicates optional and
     compulsory support for features. Even numbers indicate that both endpoints
     MUST support the feature in question, while odd numbers indicate
     that the feature MAY be disregarded by the other endpoint.


* *It's ok to be odd*:
   * いくつかの数値フィールドに対して適用されるルール。
     これらのフィールドは任意または強制のいずれかを示します。
     偶数番号のfeatureは両端ノードが問題になっているfeatureをサポートしておかなければならないことを示し、一方奇数番号のfeatureは片端のノードによってfeatureが無視されるかもしれないことを示します。

## Theme Song


      Why this network could be democratic...
      Numismatic...
      Cryptographic!
      Why it could be released Lightning!
      (Release Lightning!)


      We'll have some timelocked contracts with hashed pubkeys, oh yeah.
      (Keep talking, whoa keep talkin')
      We'll segregate the witness for trustless starts, oh yeah.
      (I'll get the money, I've got to get the money)
      With dynamic onion routes, they'll be shakin' in their boots;
      You know that's just the truth, we'll be scaling through the roof.
      Release Lightning!
      (Go, go, go, go; go, go, go, go, go, go)


      [Chorus:]
      Oh released Lightning, it's better than a debit card..
      (Release Lightning, go release Lightning!)
      With released Lightning, micropayments just ain't hard...
      (Release Lightning, go release Lightning!)
      Then kaboom: we'll hit the moon -- release Lightning!
      (Go, go, go, go; go, go, go, go, go, go)


      We'll have QR codes, and smartphone apps, oh yeah.
      (Ooo ooo ooo ooo ooo ooo ooo)
      P2P messaging, and passive incomes, oh yeah.
      (Ooo ooo ooo ooo ooo ooo ooo)
      Outsourced closure watch, gives me feelings in my crotch.
      You'll know it's not a brag when the repo gets a tag:
      Released Lightning.


      [Chorus]
      [Instrumental, ~1m10s]
      [Chorus]
      (Lightning! Lightning! Lightning! Lightning!
       Lightning! Lightning! Lightning! Lightning!)


      C'mon guys, let's get to work!


   -- Anthony Towns <aj@erisian.com.au>


## Authors


[ FIXME: Insert Author List ]


![Creative Commons License](https://i.creativecommons.org/l/by/4.0/88x31.png "License CC-BY")
<br>
This work is licensed under a [Creative Commons Attribution 4.0 International License](http://creativecommons.org/licenses/by/4.0/).
