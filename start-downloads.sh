#!/bin/bash

# Get the directory where the script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"

# Change into that directory so relative paths and .env work
cd "$SCRIPT_DIR"

# Run the python script, passing all arguments to it
python3 heis-o-mat.py -v tr "$@"
python3 heis-o-mat.py -v make "$@"
python3 heis-o-mat.py -v ct "$@"
python3 heis-o-mat.py -v ix "$@"
python3 heis-o-mat.py -v ct-foto "$@"
python3 heis-o-mat.py -v mac-and-i "$@"