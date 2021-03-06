#!/bin/bash
#
# Copyright 2014 Mimetic Markets, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
#

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd $DIR

git pull -u origin >/dev/null 2>/dev/null
(cd ..;git submodule update) >/dev/null 2>/dev/null
# For now just test the non-UI stuff until we get selenium installed at sputnikmkt.com
make clean >/dev/null
make -k no_ui report >/tmp/test_output.$$ 2>/tmp/test_errors.$$
if [ $? -ne 0 ]; then
  cat /tmp/test_output.$$
  cat /tmp/test_errors.$$
fi
rm /tmp/test_output.$$ /tmp/test_errors.$$
exit $?

