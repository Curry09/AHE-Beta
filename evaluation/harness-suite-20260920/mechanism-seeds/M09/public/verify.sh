#!/bin/sh
set -eu
python -m unittest discover -s . -p 'test_contract.py' -v
python -m unittest discover -s . -p 'test_pipeline.py' -v
