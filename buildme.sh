#!/bin/bash

pdir=`pwd`
cd docs/html
python /usr/bin/pydoc -w $pdir
cd $pdir

python3 setup.py build bdist --format rpm,gztar