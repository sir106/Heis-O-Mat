#!/bin/bash

# Get the directory where the script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"

# Change into that directory so relative paths and .env work
cd "$SCRIPT_DIR"

# Run the python script, passing all arguments to it
#echo [start-downloads.sh] Starting download for "Technology Review..."
#python3 heis-o-mat.py -v tr "$@"

#echo [start-downloads.sh] Starting download for "Make..."
#python3 heis-o-mat.py -v make "$@"

echo [start-downloads.sh] Starting download for "c't..."
python3 heis-o-mat.py -v ct "$@"

#echo [start-downloads.shART] Starting download for "IX..."
#python3 heis-o-mat.py -v ix "$@"

#echo [start-downloads.sh] Starting download for "C't Foto..."
#python3 heis-o-mat.py -v ct-foto "$@"

#echo [start-downloads.sh] Starting download for "Mac & I..."
#python3 heis-o-mat.py -v mac-and-i "$@"