# Heise Magazine Downloader

## Project Overview
This project provides a collection of scripts to automate downloading magazines as PDF files from `https://www.heise.de/select`. It offers multiple implementations across different languages (Bash, Node.js, and Python), catering to various environments and user preferences. The scripts require an active Heise subscription.

**Key Technologies:**
- **Node.js:** Implementations (`download_simple.js`, `download_merge.js`) utilizing `axios`, `puppeteer`, and `pdf-lib`.
- **Bash:** The original script implementations (`download.sh`, `download_articles.sh`).
- **Python:** A Python implementation (`heise-download.py`) utilizing `requests`.

## Directory Overview
- `download.sh`: Original Bash script to download full magazine PDFs.
- `download_articles.sh`: Bash script to download single articles and merge them using GhostScript (for subscriptions that do not permit full PDF downloads).
- `download_simple.js`: Node.js version of the downloader.
- `download_merge.js`: Node.js script for downloading individual articles and merging them.
- `heise-download.py`: Python alternative to download the magazines.
- `package.json` / `package-lock.json`: Node.js dependency management.
- `compose.yaml`: Docker Compose file for containerized execution.
- `.env.example`: Template for environment variables (credentials).

## Setup and Usage

### Prerequisites
- An active Heise subscription.
- Create a `.env` file containing your credentials based on `.env.example` (used by Node.js and Python scripts):
  ```env
  HEISE_USERNAME=your_email@example.com
  HEISE_PASSWORD=your_password
  ```

### Node.js Scripts
1. **Install dependencies:**
   ```bash
   npm install
   ```
2. **Run the script** (example for simple downloader):
   ```bash
   node download_simple.js [options]
   ```

### Bash Scripts
1. Mark the script as executable:
   ```bash
   chmod +x download.sh
   ```
2. Run the script (e.g., to download all c't issues from 2021):
   ```bash
   ./download.sh ct 2021
   ```
*Note: Depending on the script version, you may need to edit the Bash file directly to insert your credentials.*

### Python Script
1. Ensure required packages are installed (e.g., `requests`, `python-dotenv`).
2. Run the script:
   ```bash
   python3 heise-download.py [args]
   ```

## Development Conventions
- **Credentials Management:** The Node.js and Python scripts use `.env` files for configuration to avoid hardcoding credentials. The Bash scripts may require manual editing. Ensure `.env` is never committed (it is listed in `.gitignore`).
- **Resilience:** The scripts are designed to skip previously downloaded files and include retry mechanisms for internal server errors or connection refusals.
