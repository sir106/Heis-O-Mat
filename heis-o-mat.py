#!/usr/bin/env python3
import argparse
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
import urllib3

# Try to import dotenv, but don't fail if not present (can rely on env vars)
try:
    from dotenv import load_dotenv
    # Find .env in current directory or parent directories
    load_dotenv()
except ImportError:
    pass

# Suppress insecure request warnings (equivalent to curl -k)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Configuration
MIN_PDF_SIZE = 5000000  # 5MB
WAIT_TIME = 80
MAX_TRIES = 3
DOWNLOAD_DIR = os.environ.get("DOWNLOAD_DIR", "/downloads")
APPRISE_URL = os.environ.get("APPRISE_URL")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Setup logging
class ColoredFormatter(logging.Formatter):
    COLORS = {
        'INFO': '\033[0;36m',
        'SUCCESS': '\033[0;32m',
        'WARNING': '\033[0;33m', # Used for SKIP
        'ERROR': '\033[0;31m',
        'DEBUG': '\033[0;36m',
        'RESET': '\033[0m'
    }

    def format(self, record):
        level_name = record.levelname
        color = self.COLORS.get(level_name, self.COLORS['RESET'])

        # Replace levelname with formatted one for specific keywords
        if level_name == 'WARNING':
            display_name = 'SKIP'
        elif level_name == 'DEBUG':
            display_name = 'INFO'
        else:
            display_name = level_name

        # Avoid prefixing if the message itself is a custom formatted string (like SUCCESS message)
        if hasattr(record, 'no_prefix') and record.no_prefix:
            record.levelname = ""
            return record.getMessage()

        record.levelname = f"[{color}{display_name}{self.COLORS['RESET']}]"
        return super().format(record)

def setup_logger(verbose):
    logger = logging.getLogger('Heis-O-Mat')
    logger.setLevel(logging.DEBUG if verbose else logger.info)

    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG if verbose else logger.info)

    formatter = ColoredFormatter('%(levelname)s %(message)s')
    ch.setFormatter(formatter)

    logger.addHandler(ch)
    return logger

def sleepbar(wait_seconds, prefix="Waiting"):
    logger.info(f"{prefix} started ({wait_seconds}s)...")
    time.sleep(wait_seconds)
    logger.info(f"{prefix} finished.")

def send_apprise_notification(title, body, msg_type="info", logger=None):
    if not APPRISE_URL:
        return

    payload = {
        "title": title,
        "body": body,
        "type": msg_type,
        "format": "text"
    }

    try:
        res = requests.post(APPRISE_URL, json=payload, timeout=10, verify=False)
        res.raise_for_status()
    except Exception as e:
        if logger:
            logger.debug(f"Failed to send Apprise notification: {e}")

def main():
    current_year = datetime.now().year

    parser = argparse.ArgumentParser(description="Download Heise+ magazines")
    parser.add_argument('-v', '--verbose', action='store_true', help='Enable verbose output')
    parser.add_argument('magazine', help='Magazine name (e.g., ct)')

    parser.add_argument('start_year', type=int, nargs='?', default=current_year,
                        help=f'Start year (default: {current_year})')

    parser.add_argument('end_year', type=int, nargs='?',
                        help='End year (optional, defaults to start_year)')

    args = parser.parse_args()

    # Determine end year: args.end_year or just the start_year
    end_year = args.end_year if args.end_year else args.start_year

    logger = setup_logger(args.verbose)

    heise_username = os.environ.get("HEISE_USERNAME")
    heise_password = os.environ.get("HEISE_PASSWORD")

    if not heise_username or not heise_password:
        logger.error("HEISE_USERNAME or HEISE_PASSWORD not found in .env (or Environment)!")
        sys.exit(1)

    # Use a session to persist cookies
    session = requests.Session()
    session.headers.update({"User-Agent": UA})

    masked_user = heise_username[:2] + "*" * (len(heise_username) - 4) + heise_username[-2:] if len(heise_username) > 4 else "***"

    logger.info("Starting Up...")
    logger.info(f"[SETTINGS] (DOWNLOAD_DIR) Target download directory : {DOWNLOAD_DIR}")
    logger.info(f"[SETTINGS] (APPRISE_URL) Apprise URL                : {APPRISE_URL}")
    logger.info(f"[SETTINGS] (HEISE_USERNAME) Username for Login      : {masked_user}")
    logger.info(f"Sending login request as User {masked_user} to heise.de...")

    login_data = {
        "username": heise_username,
        "password": heise_password,
        "ajax": "1"
    }

    try:
        # POST to login
        login_res = session.post("https://www.heise.de/sso/login/login", data=login_data, verify=False)
        login_res.raise_for_status()
    except Exception as e:
        msg = f"Login request failed: {e}"
        logger.error(msg)
        send_apprise_notification("Heise+ Login Error", msg, "error", logger)
        sys.exit(1)

    # Extract tokens exactly like awk logic: looking for "token":"..."
    tokens = re.findall(r'"token":"([^"]+)"', login_res.text)

    if not tokens:
        msg = "Login failed (Token could not be extracted)."
        logger.error(msg)
        send_apprise_notification("Heise+ Login Error", msg, "error", logger)
        sys.exit(1)

    token1 = tokens[0]
    token2 = tokens[1] if len(tokens) > 1 else None

    logger.info("Login successful. Extracted tokens, performing SSO remote logins...")

    try:
        session.post("https://m.heise.de/sso/login/remote-login", data={"token": token1}, verify=False)
        if token2 and token2 != token1:
            logger.info("Performing secondary SSO shop login...")
            session.post("https://shop.heise.de/customer/account/loginRemote", data={"token": token2}, verify=False)
    except Exception as e:
        msg = f"SSO remote login failed: {e}"
        logger.error(msg)
        send_apprise_notification("Heise+ Login Error", msg, "error", logger)
        sys.exit(1)

    logger.info("[\033[0;32mSUCCESS\033[0m] Login phase completed.")

    count_success = 0
    count_fail = 0
    count_skip = 0

    match args.magazine.upper():
        case "CT":
            MAX_ISSUES=27
            MAGAZIN_NAME="c't"
        case "TR":
            MAX_ISSUES=8
            MAGAZIN_NAME="MIT Technology Review"
        case "IX":
            MAX_ISSUES=13
            MAGAZIN_NAME="iX"
        case "MAKE":
            MAGAZIN_NAME="Make"
            MAX_ISSUES=7
        case "ct-foto":
            MAGAZIN_NAME="c't Fotografie"
            MAX_ISSUES=7
        case "mac-and-i":
            MAGAZIN_NAME="Mac & i"
            MAX_ISSUES=7
        case _:
            MAGAZIN_NAME="heise+ magazine"
            MAX_ISSUES=27

    logger.debug(f"Setting MAX_ISSUES to {MAX_ISSUES} for {args.magazine.upper()}..")


    for year in range(args.start_year, end_year + 1):
        if args.verbose:
            logger.debug(f"Processing Year {year}")

        missing_consecutive = 0  # Reset counter for each year

        for i in range(1, MAX_ISSUES + 1):
            issue_str = f"{i:02d}"
            base_dir = Path(DOWNLOAD_DIR) / MAGAZIN_NAME / (MAGAZIN_NAME + " " + str(year))
            base_path = base_dir / f"{MAGAZIN_NAME}.{year}.{issue_str}.pdf"

            log_pfx = f"[{args.magazine}][{year}/{issue_str}]"

            if base_path.exists():
                count_skip += 1
                logger.warning(f"{log_pfx} Already exists ({base_path}).") # mapped to SKIP
                continue

            base_dir.mkdir(parents=True, exist_ok=True)

            thumb_url = f"https://heise.cloudimg.io/v7/_www-heise-de_/select/thumbnail/{args.magazine}/{year}/{i}.jpg"
            thumb_res = session.get(thumb_url, verify=False)

            if thumb_res.status_code != 200:
                missing_consecutive += 1
                if args.verbose:
                    logger.warning(f"{log_pfx} Issue might not (yet) exist - Thumbnail ({thumb_url}) not found (HTTP {thumb_res.status_code}).")
                if missing_consecutive >= 3:
                    logger.info(f"Stopping year {year}: 3 consecutive issues missing.")
                    break # Exit the issue loop (i) and move to next year
                continue

            # If we found an issue, reset the counter
            missing_consecutive = 0

            if args.verbose:
                logger.debug(f"{log_pfx} Issue found. Starting download sequence.")

            success = False
            for try_num in range(1, MAX_TRIES + 1):
                 logger.info(f"{log_pfx} [Try {try_num}/{MAX_TRIES}] Downloading...\r")
                 download_url = f"https://www.heise.de/select/{args.magazine}/archiv/{year}/{i}/download"

                try:
                    while True:
                        if args.verbose:
                            logger.debug(f"\n{log_pfx} Starting download ({download_url}) to {base_path}..")

                        pdf_res = session.get(download_url, verify=False, stream=True)

                        # Check if the server makes us wait
                        if "wait_sec=" in pdf_res.url:
                            wait_match = re.search(r'wait_sec=(\d+)', pdf_res.url)
                            if wait_match:
                                wait_seconds = int(wait_match.group(1))
                                logger.info(f"{log_pfx} Server requested wait period of {wait_seconds} seconds. ({pdf_res.url})")

                                sleepbar(wait_seconds + 2, prefix="Server-enforced wait (+2s)...")
                                continue  # Jumps to the next iteration of 'while True'
                            else:
                                # If "wait_sec" is in the URL, but no number was found
                                break
                        else:
                            # No more "wait_sec" in the URL -> We probably reached the actual PDF!
                            content = pdf_res.content
                            size = len(content)
                            break

                    if size > MIN_PDF_SIZE:
                        logger.info(f"\n{log_pfx} [\033[0;32mSUCCESS\033[0m] Done ({size // 1024 // 1024} MB)\n")
                        base_path.write_bytes(content)

                        # Log history
                        history_log = Path(DOWNLOAD_DIR) / "heis-o-mat_download_history.log"
                        with open(history_log, "a") as f:
                            timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
                            f.write(f"{timestamp} - {log_pfx} Successfully downloaded: {base_path} - Source: {download_url}\n")

                        send_apprise_notification(
                            title=f"Heise+ Download Success: {args.magazine.upper()} {year}/{i:02d}",
                            body=f"Successfully downloaded magazine '{args.magazine.upper()}' issue {i:02d} from {year}.\nFile size: {size // 1024 // 1024} MB\nSaved to: {base_path}",
                            msg_type="success",
                            logger=logger
                        )

                        success = True
                        count_success += 1
                        break
                    else:
                        logger.error(f"\n{log_pfx} Download failed or not a PDF (Size: {size} Bytes)\n")

                except Exception as e:
                    logger.error(f"\n{log_pfx} Request exception: {e}\n")

                if try_num < MAX_TRIES:
                    sleepbar(WAIT_TIME)

            if not success:
                logger.error(f"{log_pfx} [\033[0;31mERROR\033[0m] Download failed after {MAX_TRIES} attempts.\n")

                send_apprise_notification(
                    title=f"Heise+ Download Error: {args.magazine.upper()} {year}/{i:02d}",
                    body=f"Failed to download magazine '{args.magazine.upper()}' issue {i:02d} from {year} after {MAX_TRIES} attempts.",
                    msg_type="error",
                    logger=logger
                )

                count_fail += 1

     logger.info(f"----------- Summary: {count_success} ok, {count_fail} failed, {count_skip} skipped. "-----------")

    logger.info("Done!")

if __name__ == "__main__":
    main()