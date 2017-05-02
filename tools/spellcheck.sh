#!/bin/sh
# spellcheck.sh
# by ZmnSCPxj
# Simple script to spellcheck files.
#
# ZmnSCPxj puts this script into the public domain.

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

for f
do
 aspell -l en_US --home-dir ${homedir} -c $f
done
