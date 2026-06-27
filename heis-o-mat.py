#!/usr/bin/env python3
import argparse
import json
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

# Magazine configuration
MAGAZINE_CONFIG = {
    "CT": {"name": "c't", "max_issues": 27},
    "TR": {"name": "MIT Technology Review", "max_issues": 8},
    "IX": {"name": "iX", "max_issues": 13},
    "MAKE": {"name": "Make", "max_issues": 7},
    "CT-FOTO": {"name": "c't Fotografie", "max_issues": 7},
    "MAC-AND-I": {"name": "Mac & i", "max_issues": 7},
    # Add other magazines here
    "DEFAULT": {"name": "heise+ magazine", "max_issues": 27}
}


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

        # Use INFO for DEBUG level for cleaner output
        if level_name == 'DEBUG':
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
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)

    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG if verbose else logging.INFO)

    formatter = ColoredFormatter('%(levelname)s %(message)s')
    ch.setFormatter(formatter)

    logger.addHandler(ch)
    return logger

def sleepbar(wait_seconds, prefix="Waiting"):
    logger = logging.getLogger('Heis-O-Mat')
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

def get_login_session(logger, heise_username, heise_password):
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


    # Use a session to persist cookies
    session = requests.Session()
    session.headers.update({"User-Agent": UA})

    masked_user = heise_username[:2] + "*" * (len(heise_username) - 4) + heise_username[-2:] if len(heise_username) > 4 else "***"

    if args.verbose:
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

    try:
        login_json = login_res.json()
        tokens = login_json.get("token", [])
    except json.JSONDecodeError:
        msg = "Login failed (Token could not be extracted)."
        logger.error(msg)
        send_apprise_notification("Heise+ Login Error", msg, "error", logger)
        sys.exit(1)


    token1 = tokens[0]
    token2 = tokens[1] if len(tokens) > 1 else None

    if args.verbose:
        logger.info("Login successful. Extracted tokens, performing SSO remote logins...")

    try:
        session.post("https://m.heise.de/sso/login/remote-login", data={"token": token1}, verify=False)
        if token2 and token2 != token1:
            if args.verbose:
                logger.info("Performing secondary SSO shop login...")
            session.post("https://shop.heise.de/customer/account/loginRemote", data={"token": token2}, verify=False)
    except Exception as e:
        msg = f"SSO remote login failed: {e}"
        logger.error(msg)
        send_apprise_notification("Heise+ Login Error", msg, "error", logger)
        sys.exit(1)
    return session, args

def download_issue(session, magazine, year, issue, magazine_name, logger, verbose):
    issue_str = f"{issue:02d}"
    log_pfx = f"[{magazine}][{year}/{issue_str}]"
    download_url = f"https://www.heise.de/select/{magazine}/archiv/{year}/{issue}/download"
    base_dir = Path(DOWNLOAD_DIR) / magazine_name / (magazine_name + " " + str(year))
    base_path = base_dir / f"{magazine_name}.{year}.{issue_str}.pdf"

    base_dir.mkdir(parents=True, exist_ok=True)

    for try_num in range(1, MAX_TRIES + 1):
        if verbose:
            logger.info(f"{log_pfx} [Try {try_num}/{MAX_TRIES}] Downloading...\r")

        try:
            content, final_url = fetch_pdf_content(session, download_url, log_pfx, logger, verbose)
            size = len(content)

            if size > MIN_PDF_SIZE:
                logger.info(f"\n{log_pfx} [\033[0;32mSUCCESS\033[0m] Done ({size // 1024 // 1024} MB)\n")
                base_path.write_bytes(content)

                # Log history
                history_log = Path(DOWNLOAD_DIR) / "heis-o-mat_download_history.log"
                with open(history_log, "a") as f:
                    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
                    f.write(f"{timestamp} - {log_pfx} Successfully downloaded: {base_path} - Source: {final_url}\n")

                send_apprise_notification(
                    title=f"Heise+ Download Success: {magazine.upper()} {year}/{issue:02d}",
                    body=f"Successfully downloaded magazine '{magazine.upper()}' issue {issue:02d} from {year}.\nFile size: {size // 1024 // 1024} MB\nSaved to: {base_path}",
                    msg_type="success",
                    logger=logger
                )
                return "success"
            else:
                logger.error(f"\n{log_pfx} Download failed or not a PDF (Size: {size} Bytes)\n")

        except Exception as e:
            logger.error(f"\n{log_pfx} Request exception: {e}\n")

        if try_num < MAX_TRIES:
            sleepbar(WAIT_TIME)

    logger.error(f"{log_pfx} [\033[0;31mERROR\033[0m] Download failed after {MAX_TRIES} attempts.\n")
    send_apprise_notification(
        title=f"Heise+ Download Error: {magazine.upper()} {year}/{issue:02d}",
        body=f"Failed to download magazine '{magazine.upper()}' issue {issue:02d} from {year} after {MAX_TRIES} attempts.",
        msg_type="error",
        logger=logger
    )
    return "fail"

def fetch_pdf_content(session, download_url, log_pfx, logger, verbose):
    current_url = download_url
    while True:
        if verbose:
            logger.debug(f"\n{log_pfx} Starting download ({current_url})..")

        pdf_res = session.get(current_url, verify=False, stream=True)
        pdf_res.raise_for_status()

        # Check if the server makes us wait
        if "wait_sec=" in pdf_res.url:
            wait_match = re.search(r'wait_sec=(\d+)', pdf_res.url)
            if wait_match:
                wait_seconds = int(wait_match.group(1))
                logger.info(f"{log_pfx} Server requested wait period of {wait_seconds} seconds. ({pdf_res.url})")
                sleepbar(wait_seconds + 2, prefix="Server-enforced wait (+2s)...")
                current_url = pdf_res.url # Use the new URL for the next request
                continue
            else:
                # If "wait_sec" is in the URL, but no number was found, break to avoid infinite loop
                raise IOError("Server responded with 'wait_sec' in URL but no value was found.")
        else:
            # No more "wait_sec" in the URL -> We probably reached the actual PDF!
            return pdf_res.content, pdf_res.url

def main():
    logger = setup_logger(False) # Initial setup, will be updated by args

    heise_username = os.environ.get("HEISE_USERNAME")
    heise_password = os.environ.get("HEISE_PASSWORD")

    if not heise_username or not heise_password:
        logger.error("HEISE_USERNAME or HEISE_PASSWORD not found in .env (or Environment)!")
        sys.exit(1)

    session, args = get_login_session(logger, heise_username, heise_password)
    logger = setup_logger(args.verbose) # Re-setup logger with correct verbosity

    masked_user = heise_username[:2] + "*" * (len(heise_username) - 4) + heise_username[-2:] if len(heise_username) > 4 else "***"
    logger.info("----------- Heis-O-Mat Starting Up -----------")
    logger.info(f"[SETTINGS] (DOWNLOAD_DIR) Target download directory : {DOWNLOAD_DIR}")
    logger.info(f"[SETTINGS] (APPRISE_URL) Apprise URL                : {APPRISE_URL is not None}")
    logger.info(f"[SETTINGS] (HEISE_USERNAME) Username for Login      : {masked_user}")

    count_success = 0
    count_fail = 0
    count_skip = 0

    magazine_key = args.magazine.upper()
    config = MAGAZINE_CONFIG.get(magazine_key, MAGAZINE_CONFIG["DEFAULT"])
    MAGAZINE_NAME = config["name"]
    MAX_ISSUES = config["max_issues"]

    logger.debug(f"Setting MAX_ISSUES to {MAX_ISSUES} for {magazine_key}..")

    end_year = args.end_year if args.end_year else args.start_year
    for year in range(args.start_year, end_year + 1):
        if args.verbose:
            logger.debug(f"Processing Year {year}")

        missing_consecutive = 0

        for i in range(1, MAX_ISSUES + 1):
            issue_str = f"{i:02d}"
            base_dir = Path(DOWNLOAD_DIR) / MAGAZINE_NAME / (MAGAZINE_NAME + " " + str(year))
            base_path = base_dir / f"{MAGAZINE_NAME}.{year}.{issue_str}.pdf"
            log_pfx = f"[{args.magazine}][{year}/{issue_str}]"

            if base_path.exists():
                count_skip += 1
                logger.info(f"[SKIP] {log_pfx} Already exists ({base_path}).")
                continue

            thumb_url = f"https://heise.cloudimg.io/v7/_www-heise-de_/select/thumbnail/{args.magazine}/{year}/{i}.jpg"
            thumb_res = session.get(thumb_url, verify=False)

            if thumb_res.status_code != 200:
                missing_consecutive += 1
                if args.verbose:
                    logger.warning(f"{log_pfx} Issue might not (yet) exist - Thumbnail ({thumb_url}) not found (HTTP {thumb_res.status_code}).")
                if missing_consecutive >= 3:
                    if args.verbose:
                        logger.info(f"Stopping year {year}: 3 consecutive issues missing.")
                    break
                continue

            missing_consecutive = 0
            if args.verbose:
                logger.debug(f"{log_pfx} Issue found. Starting download sequence.")

            result = download_issue(session, args.magazine, year, i, MAGAZINE_NAME, logger, args.verbose)
            if result == "success":
                count_success += 1
            else:
                count_fail += 1

    logger.info(f"----------- Heis-O-Mat has finished! {count_success} ok, {count_fail} failed, {count_skip} skipped. -----------")

if __name__ == "__main__":
    main()
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

    logger.info(f"----------- Heis-O-Mat has finished! {count_success} ok, {count_fail} failed, {count_skip} skipped. -----------")

if __name__ == "__main__":
    main()