#!/bin/bash
export OMP_NUM_THREADS=1
export KMP_DUPLICATE_LIB_OK=TRUE
cd "$(dirname "$0")"
exec .venv/bin/python main.py
