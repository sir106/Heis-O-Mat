# Downloader for Heise Magazines

This is a Python script (`heise-download.py`) to download magazines as PDF files from https://www.heise.de/select. It replaces the legacy bash script implementation.

This project origins from AlexanderMelde's repository (https://github.com/AlexanderMelde/dl_for_heise).

You will need an active Heise+ subscription to download anything. This is just an alternative to clicking buttons in your browser.

Start Page for all available magazines from heise+ https://www.heise.de/select.

## Prerequisites

- Python 3.6 or higher
- Required Python packages: `requests`, `urllib3`
- Optional package: `python-dotenv` (highly recommended for `.env` file support)

You can install the required packages using pip:
```bash
pip install requests python-dotenv
```

## Setup & Credentials

Instead of editing the script directly, credentials are now securely managed via environment variables.

1. Create a `.env` file in the same directory as the script.
2. Add your Heise login credentials to the `.env` file:
   ```env
   HEISE_USERNAME=your_email@example.com
   HEISE_PASSWORD=your_password
   ```

You can optionally configure the target download directory and Apprise notifications:
```env
# Optional settings
DOWNLOAD_DIR=./downloads   # Defaults to /downloads if not set
APPRISE_URL=apprise://...  # Optional notification URL
```

## Usage

Run the script from your terminal:

```bash
python3 heise-download.py [-v] <magazine> <start_year> [end_year]
```

### Examples

- **Download all issues of the magazine c't from the year 2021:**
  ```bash
  python3 heise-download.py ct 2021
  ```
- **Download all c't magazines between 2014 and 2022:**
  ```bash
  python3 heise-download.py ct 2014 2022
  ```
- **Display additional verbose console output:**
  ```bash
  python3 heise-download.py -v ct 2014 2022
  ```

You will find all downloaded PDF files in subfolders divided by magazine name and year inside your specified `DOWNLOAD_DIR`.

## Further Options

- **Download other magazines:** replace `ct` with whatever is in the URL of the [heise archive page](https://www.heise.de/select). For example, for the archive of Make (`https://www.heise.de/select/make/archiv`), the correct name is `make`. For Retro Gamer (`https://www.heise.de/select/retro-gamer/archiv`), the name is `retro-gamer`. Further options include: `ix`, `tr`, `mac-and-i`, `ct-foto`, `ct-wissen`, `ix-special`, etc.

## Common Failures & Features

- **Rate Limiting & Wait Periods:** Heise's servers may enforce download rate limits. The new Python script detects "wait_sec" parameters from the server, automatically pauses for the requested duration, and resumes without failing.
- **Retries:** If the server throws temporary errors or drops connections, the script will automatically retry up to 3 times with pauses in between.
- **Incremental Downloads:** Already downloaded files will be detected and skipped, making it safe to rerun the script to catch up on new issues.
- **Not Authorized:** If your subscription does not permit downloading full PDFs for certain issues, the download will eventually fail and log an error. *Note: Ensure your subscription tier includes full PDF downloads; some tiers only allow reading individual articles.*

Please submit pull requests and open issues in this project if you want to further improve this script.

## Disclaimer
This project is a community-based non-commercial project and not affiliated with Heise Medien GmbH & Co. KG. The script only acts as a client to download files otherwise available via your web browser. It does not circumvent any security measures made by the magazine publishers; without an active subscription to their services, no downloads will be possible.