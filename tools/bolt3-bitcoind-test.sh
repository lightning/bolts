#! /bin/sh

# To run all tests, try:
# grep 'name: .*commitment tx' ../03-transactions.md | cut -d: -f2- | while read t; do ./bolt3-test-vector.sh $t || break; done

TESTDIR=/tmp/bolt3-testdir.$$
BOLT3=../03-transactions.md

set -e
CLI="bitcoin-cli -datadir=$TESTDIR"
TEST=$TESTDIR/test

VERBOSE=:
VERBOSEPIPE=:
if [ x"$1" = x"--verbose" ]; then
    VERBOSE=echo
    VERBOSEPIPE=cat
    shift
fi

# FIXME: This doesn't work in 0.14 (see bitcoin-core commit
# 7d4e9509ade0c258728011d8f6544ec3e75d63dc)
#FEELESS_TXS_OK=${FEELESS_TXS_OK:-true}
FEELESS_TXS_OK=${FEELESS_TXS_OK:-false}

# Comment this out to postmortem
trap "$CLI stop >/dev/null 2>&1 || true; sleep 1; rm -rf $TESTDIR" EXIT

if [ $# -lt 1 ]; then
    echo Usage: $0 "[--verbose] <testname>..." >&2
    exit 1
fi

# Usage <fieldname> <document>
extract_fields()
{
    grep "^    $1:" $2 || true
}

# Usage <fieldname> <document>
extract_field()
{
    if [ $(grep -c "^    $1:" $2) != 1 ]; then
	echo "Ambigious field $1" >&2
	exit 1
    fi
    extract_fields "$@" | cut -d: -f2-
}

# Usage <htlcnum> <property> <document>
htlc_property()
{
    extract_field "htlc $1 $2" $3
}

# Usage <testname>
extract_test()
{
    print=:
    found=false
    while read LINE; do
	case "$LINE" in
	    "name: $1")
		print=echo
		$print "    $LINE"
		found=true
		;;
	    "name:"*|"")
		print=true
		;;
	    *)
		$print "    $LINE"
		;;
	esac
    done < $BOLT3

    if ! $found; then
	echo "No test $1 found" >&2
	exit 1
    fi
}

mkdir $TESTDIR
echo regtest=1 > $TESTDIR/bitcoin.conf
echo rpcbind=127.0.0.1 >> $TESTDIR/bitcoin.conf
echo rpcport=18333 >> $TESTDIR/bitcoin.conf
echo rpcpassword=$(od -tx1 -A none -N20 < /dev/urandom | tr -d ' ') >> $TESTDIR/bitcoin.conf

if $FEELESS_TXS_OK; then
    echo minrelaytxfee=0 >> $TESTDIR/bitcoin.conf
else
    echo minrelaytxfee=0.00000001 >> $TESTDIR/bitcoin.conf
fi

$VERBOSE Starting bitcoind
bitcoind -datadir=$TESTDIR &

i=0
while ! $CLI getinfo >/dev/null 2>&1; do
    sleep 0.1
    i=$(($i + 1))
    if [ $i -ge 50 ]; then
	echo Bitcoind failed to start >&2
	exit 1
    fi
done

$VERBOSE Checking bitcoind genesis block matches BOLT3
GENESIS=$($CLI getblock $($CLI getblockhash 0) false)

if [ $GENESIS != $(extract_field 'Block 0 (genesis)' $BOLT3) ]; then
    echo Bad genesis block >&2
    exit 1
fi

$VERBOSE Submitting block '#1' from BOLT3
$CLI submitblock $(extract_field 'Block 1' $BOLT3)
# To activate segwit via BIP9, we need at least 432 blocks!  Also lets us spend tx.

$VERBOSE Activating SegWit
$CLI generate 432 > /dev/null

$VERBOSE Sending funding transaction from BOLT3
TXID=$($CLI sendrawtransaction $(extract_field 'funding tx' $BOLT3))
if [ $TXID != $(extract_field '# txid' $BOLT3) ]; then
    echo Bad funding txid >&2
    exit 1
fi

echo -n Running \""$*"\":\ 

extract_test "$*" > $TEST
if ! $FEELESS_TXS_OK && [ $(extract_field 'local_feerate_per_kw' $TEST) = 0 ]
then
    echo SKIPPED
    $VERBOSE "Override by prepending FEELESS_TXS_OK=true to commandline"
    exit 0
fi

# In verbose mode, we need a CR here.
$VERBOSE

TX=$(extract_field 'output commit_tx' $TEST)
$VERBOSE -n "Submitting commit_tx: "
$CLI sendrawtransaction $TX | $VERBOSEPIPE

# We can use success txs immediately
extract_fields 'output htlc_success_tx [0-9]*' $TEST | while read TX; do
    $VERBOSE -n "Submitting ${TX%%:*}: "
    $CLI sendrawtransaction ${TX#*:} | $VERBOSEPIPE
done

# Timeout txs have to wait for timeout; fortunately they're in order.
extract_fields 'output htlc_timeout_tx [0-9]*' $TEST | while read TX; do
    TITLE=${TX%%:*}
    HTLC=${TITLE##* }
    EXPIRY=$(htlc_property $HTLC expiry $BOLT3)
    # Should fail before expiry.
    $CLI generate $(($EXPIRY - 1 - $($CLI getblockcount) )) >/dev/null
    HEIGHT=$EXPIRY-1
    $VERBOSE -n "Submitting ${TX%%:*} TOO EARLY: "
    if $CLI sendrawtransaction ${TX#*:} > $TESTDIR/too-early 2>&1; then
	$VERBOSE $TESTDIR/too-early
	echo "Timeout worked at blockheight $($CLI getblockcount) not $EXPIRY" >&2
	exit 1
    fi
    tail -n1 $TESTDIR/too-early | $VERBOSEPIPE
    $CLI generate 1 >/dev/null
    $VERBOSE -n "Submitting ${TX%%:*}: "
    $CLI sendrawtransaction ${TX#*:} | $VERBOSEPIPE
done

echo Success
exit 0
