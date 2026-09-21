#!/bin/sh
set -eu
python -m unittest test_smoke.py -v
python -m unittest test_regression.py -v
python -m unittest test_fixture.py -v
