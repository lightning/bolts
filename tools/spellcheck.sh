#!/bin/sh
# spellcheck.sh
# by ZmnSCPxj
# Simple script to spellcheck files.
#
# ZmnSCPxj puts this script into the public domain.

set -e

# Check if dirname works.
if (test_dir=`dirname -- /` && test "X"$test_dir = "X/")
then
 my_dirname=dirname
else
 my_dirname=false
fi

# Find the path to this script.
# We assume sed works on most systems, since it's very old.
my_dir=`$my_dirname -- "$0" ||
echo X"$0" |
 sed '/^X\(.*[^/]\)\/\/*[^/][^/]*\/*$/{
 s//\1/
 q
 }
 /^X\(\/\/\)[^/].*/{
 s//\1/
 q
 }
 /^X\(\/\/\)$/{
 s//\1/
 q
 }
 /^X\(\/\).*/{
 s//\1/
 q
 }
 s/.*/./; q'`

# This script should be in the tools/ directory of the
# repository.
homedir="$my_dir"/..

if [ x"$1" = x"--check" ]; then
    CHECK=1
    shift
fi

for f
do
    if [ -n "$CHECK" ]; then
	# Eliminate the following:
	# Inline references eg. [Use of segwit](#use-of-segwit)
	# Code blocks using ```
	# quoted identifiers eg. `htlc_id`
	# field descriptions, eg. `* [`num_htlcs*64`:`htlc_signature]'
	# indented field names, eg. '    `num_htlcs`: 0'
	# lightning addresses, eg. `lnbc1qpvj6chq...`
	# BIP 173 addresses, eg. `bc1qpvj6chq...`
	# Short hex strings, eg '0x2bb038521914 12'
	# long hex strings
	# long base58 strings
	WORDS=$(sed -e 's/\]([-#a-zA-Z0-9_.]*)//g' \
	    -e '/^```/,/^```/d' \
	    -e 's/`[a-zA-Z0-9_]*`//g' \
	    -e 's/\* \[`[_a-z0-9*]\+`://g' \
	    -e 's/0x[a-fA-F0-9 ]\+//g' \
	    -e 's/[a-fA-F0-9]\{20,\}//g' \
	    -e 's/^    .*_htlcs//g' \
	    -e 's/ ln\(bc\|tb\)[0-9munp]*1[qpzry9x8gf2tvdw0s3jn54khce6mua7l]\+//g' \
	    -e 's/ \(bc\|tb\|bcrt\)1[qpzry9x8gf2tvdw0s3jn54khce6mua7l]\+//g' \
	    -e 's/[123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz]\{20,\}//g' < $f | aspell -l en_US --home-dir ${homedir} list)
	if [ -n "$WORDS" ]; then
	    echo Misspelled words in $f: $WORDS >&2
	    exit 1
	fi
    else
	aspell -l en_US --home-dir ${homedir} -c $f
    fi
done
