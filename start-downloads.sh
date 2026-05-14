#!/bin/bash

# Get the directory where the script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"

# Change into that directory so relative paths and .env work
cd "$SCRIPT_DIR"

# Run the python script, passing all arguments to it
#echo [START] Starting download for "Technology Review..."
#python3 heis-o-mat.py -v tr "$@"

#echo [START] Starting download for "Make..."
#python3 heise-download.py -v make "$@"

echo [START] Starting download for "c't..."
python3 heise-download.py -v ct "$@"

#echo [START] Starting download for "IX..."
#python3 heise-download.py -v ix "$@"

#echo [START] Starting download for "C't Foto..."
#python3 heise-download.py -v ct-foto "$@"

#echo [START] Starting download for "Mac & I..."
#python3 heise-download.py -v mac-and-i "$@"