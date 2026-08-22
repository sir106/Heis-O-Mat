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
import traceback

import requests
import urllib3

# Try to import dotenv, but don't fail if not present (can rely on env vars)
try:
    from dotenv import load_dotenv
    # Find .env in current directory or parent directories
    load_dotenv()
except ImportError:
    pass

# Configuration constants
MIN_PDF_SIZE = 5000000  # 5MB
WAIT_TIME = 80
MAX_TRIES = 3
MAX_WAIT_CYCLES = 10
DEFAULT_TIMEOUT = 30

# Default download directory: prefer env var, then writable /downloads, else ./downloads
ENV_DOWNLOAD_DIR = os.environ.get("DOWNLOAD_DIR")
if ENV_DOWNLOAD_DIR:
    DOWNLOAD_DIR = ENV_DOWNLOAD_DIR
elif os.path.exists("/downloads") and os.access("/downloads", os.W_OK):
    DOWNLOAD_DIR = "/downloads"
else:
    DOWNLOAD_DIR = "./downloads"

APPRISE_URL = os.environ.get("APPRISE_URL")
HEALTHCHECK_URL = os.environ.get("HEALTHCHECK_URL") or os.environ.get("HEALTHCHECKS_URL") or os.environ.get("HEALTHCHECKS_IO_URL")
DEFAULT_VERIFY_SSL = os.environ.get("VERIFY_SSL", "true").lower() not in ("false", "0", "no")

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
        'WARNING': '\033[0;33m',  # Used for SKIP / warnings
        'ERROR': '\033[0;31m',
        'DEBUG': '\033[0;36m',
        'RESET': '\033[0m'
    }

    def format(self, record):
        level_name = record.levelname
        color = self.COLORS.get(level_name, self.COLORS['RESET'])

        # Use INFO for DEBUG level for cleaner output
        display_name = 'INFO' if level_name == 'DEBUG' else level_name

        if hasattr(record, 'no_prefix') and record.no_prefix:
            record.levelname = ""
            return record.getMessage()

        record.levelname = f"[{color}{display_name}{self.COLORS['RESET']}]"
        return super().format(record)


def setup_logger(verbose):
    logger = logging.getLogger('Heis-O-Mat')
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)

    if logger.hasHandlers():
        logger.handlers.clear()

    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG if verbose else logging.INFO)

    formatter = ColoredFormatter('%(levelname)s %(message)s')
    ch.setFormatter(formatter)

    logger.addHandler(ch)
    return logger


def mask_username(username):
    if not username:
        return "***"
    if len(username) > 4:
        return username[:2] + "*" * (len(username) - 4) + username[-2:]
    return "***"


def sleepbar(wait_seconds, prefix="Waiting", logger=None):
    log = logger or logging.getLogger('Heis-O-Mat')
    log.info(f"{prefix} started ({wait_seconds}s)...")
    time.sleep(wait_seconds)
    log.info(f"{prefix} finished.")


def send_apprise_notification(title, body, msg_type="info", logger=None, verify_ssl=True):
    if not APPRISE_URL:
        return

    # Map "error" to "failure" because Apprise API expects "failure" for errors.
    apprise_type = "failure" if msg_type == "error" else msg_type

    payload = {
        "title": title,
        "body": body,
        "type": apprise_type,
        "format": "text"
    }

    try:
        res = requests.post(APPRISE_URL, json=payload, timeout=DEFAULT_TIMEOUT, verify=verify_ssl)
        res.raise_for_status()
    except Exception as e:
        if logger:
            logger.debug(f"Failed to send Apprise notification: {e}")


def ping_healthcheck(status, body=None, logger=None, verify_ssl=True):
    if not HEALTHCHECK_URL:
        return

    url = HEALTHCHECK_URL.rstrip('/')
    if status == "start":
        url = f"{url}/start"
    elif status == "fail":
        url = f"{url}/fail"

    try:
        data_payload = body.encode('utf-8') if isinstance(body, str) else body
        res = requests.post(url, data=data_payload, timeout=DEFAULT_TIMEOUT, verify=verify_ssl)
        res.raise_for_status()
    except Exception as e:
        if logger:
            logger.debug(f"Failed to send Healthchecks.io ping ({status}): {e}")


def parse_arguments():
    current_year = datetime.now().year

    parser = argparse.ArgumentParser(
        description="Download Heise+ magazines as PDF files.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument('magazine', help='Magazine identifier (e.g., ct, ix, tr, make, mac-and-i, ct-foto)')
    parser.add_argument('start_year', type=int, nargs='?', default=current_year,
                        help=f'Start year (default: {current_year})')
    parser.add_argument('end_year', type=int, nargs='?', default=None,
                        help='End year (optional, defaults to start_year)')
    parser.add_argument('-v', '--verbose', action='store_true', help='Enable verbose output')
    parser.add_argument('--download-dir', type=str, default=None,
                        help=f'Target download directory (default: {DOWNLOAD_DIR})')
    parser.add_argument('--insecure', action='store_true',
                        help='Disable SSL certificate verification (not recommended)')

    args = parser.parse_args()

    # Determine end_year
    if args.end_year is None:
        args.end_year = args.start_year

    if args.start_year > args.end_year:
        parser.error(f"start_year ({args.start_year}) cannot be greater than end_year ({args.end_year}).")

    return args


def get_login_session(logger, heise_username, heise_password, verbose=False, verify_ssl=True):
    session = requests.Session()
    session.headers.update({"User-Agent": UA})

    masked_user = mask_username(heise_username)

    if verbose:
        logger.info(f"Sending login request as User {masked_user} to heise.de...")

    login_data = {
        "username": heise_username,
        "password": heise_password,
        "ajax": "1"
    }

    try:
        login_res = session.post(
            "https://www.heise.de/sso/login/login",
            data=login_data,
            verify=verify_ssl,
            timeout=DEFAULT_TIMEOUT
        )
        login_res.raise_for_status()
    except Exception as e:
        msg = f"Login request failed: {e}"
        logger.error(msg)
        send_apprise_notification("Heise+ Login Error", msg, "error", logger, verify_ssl=verify_ssl)
        sys.exit(1)

    # Extract tokens: check JSON payload first, fallback to regex
    tokens = []
    login_data_json = {}
    try:
        data = login_res.json()
        if isinstance(data, dict):
            login_data_json = data
            if "token" in data and isinstance(data["token"], str):
                tokens.append(data["token"])
            if "tokens" in data and isinstance(data["tokens"], list):
                tokens.extend(str(t) for t in data["tokens"] if t)
            if "error" in data:
                msg = f"Login failed: {data.get('error')}"
                logger.error(msg)
                send_apprise_notification("Heise+ Login Error", msg, "error", logger, verify_ssl=verify_ssl)
                sys.exit(1)
    except Exception:
        pass

    if not tokens:
        tokens = re.findall(r'"token"\s*:\s*"([^"]+)"', login_res.text)

    if not tokens:
        msg = "Login failed (Token could not be extracted). Please check your credentials."
        logger.error(msg)
        send_apprise_notification("Heise+ Login Error", msg, "error", logger, verify_ssl=verify_ssl)
        sys.exit(1)

    token1 = tokens[0]
    token2 = tokens[1] if len(tokens) > 1 else None

    if verbose:
        logger.info("Login successful. Extracted tokens, performing SSO remote logins...")

    try:
        remote_login_urls = login_data_json.get("remote_login_urls", [])
        if remote_login_urls:
            for item in remote_login_urls:
                url = item.get("url")
                payload = item.get("data")
                if url and payload:
                    if verbose:
                        logger.info(f"Performing SSO remote login to {url}...")
                    res = session.post(
                        url,
                        data=payload,
                        verify=verify_ssl,
                        timeout=DEFAULT_TIMEOUT
                    )
                    res.raise_for_status()
        else:
            if verbose:
                logger.info("No remote login URLs found in JSON response, using fallback...")
            res1 = session.post(
                "https://www.heise.de/sso/login/remote-login",
                data={"token": token1},
                verify=verify_ssl,
                timeout=DEFAULT_TIMEOUT
            )
            res1.raise_for_status()

            if token2 and token2 != token1:
                if verbose:
                    logger.info("Performing secondary SSO shop login...")
                res2 = session.post(
                    "https://shop.heise.de/customer/account/loginRemote",
                    data={"token": token2},
                    verify=verify_ssl,
                    timeout=DEFAULT_TIMEOUT
                )
                res2.raise_for_status()
    except Exception as e:
        msg = f"SSO remote login failed: {e}"
        logger.error(msg)
        send_apprise_notification("Heise+ Login Error", msg, "error", logger, verify_ssl=verify_ssl)
        sys.exit(1)

    return session


def fetch_pdf_content(session, download_url, log_pfx, logger, verbose, verify_ssl=True):
    current_url = download_url
    wait_cycles = 0

    while wait_cycles < MAX_WAIT_CYCLES:
        if verbose:
            logger.debug(f"{log_pfx} Requesting ({current_url})...")

        pdf_res = session.get(current_url, verify=verify_ssl, stream=True, timeout=DEFAULT_TIMEOUT)
        pdf_res.raise_for_status()

        # Check if the server makes us wait
        if "wait_sec=" in pdf_res.url:
            wait_match = re.search(r'wait_sec=(\d+)', pdf_res.url)
            pdf_res.close()  # Close stream before sleeping to avoid connection leak

            if wait_match:
                wait_cycles += 1
                wait_seconds = int(wait_match.group(1))
                logger.info(f"{log_pfx} Server requested wait period of {wait_seconds} seconds (cycle {wait_cycles}/{MAX_WAIT_CYCLES}).")
                sleepbar(wait_seconds + 2, prefix="Server-enforced wait (+2s)", logger=logger)
                continue
            else:
                raise IOError("Server responded with 'wait_sec' in URL but no numeric value was found.")
        else:
            try:
                content = pdf_res.content
                final_url = pdf_res.url
                return content, final_url
            finally:
                pdf_res.close()

    raise IOError(f"Exceeded maximum server wait cycles ({MAX_WAIT_CYCLES}).")


def download_issue(session, magazine, year, issue, magazine_name, target_dir, logger, verbose, verify_ssl=True):
    issue_str = f"{issue:02d}"
    log_pfx = f"[{magazine}][{year}/{issue_str}]"
    download_url = f"https://www.heise.de/select/{magazine}/archiv/{year}/{issue}/download"
    base_dir = Path(target_dir) / magazine_name / f"{magazine_name} {year}"
    base_path = base_dir / f"{magazine_name}.{year}.{issue_str}.pdf"

    base_dir.mkdir(parents=True, exist_ok=True)

    for try_num in range(1, MAX_TRIES + 1):
        if verbose:
            logger.info(f"{log_pfx} [Try {try_num}/{MAX_TRIES}] Downloading...")

        try:
            content, final_url = fetch_pdf_content(session, download_url, log_pfx, logger, verbose, verify_ssl=verify_ssl)
            size = len(content)

            if size > MIN_PDF_SIZE:
                logger.info(f"{log_pfx} [\033[0;32mSUCCESS\033[0m] Done ({size // 1024 // 1024} MB)")
                base_path.write_bytes(content)

                # Log history
                history_log = Path(target_dir) / "heis-o-mat_download_history.log"
                try:
                    with open(history_log, "a", encoding="utf-8") as f:
                        timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
                        f.write(f"{timestamp} - {log_pfx} Successfully downloaded: {base_path} - Source: {final_url}\n")
                except Exception as log_err:
                    if verbose:
                        logger.warning(f"Could not write to history log: {log_err}")

                send_apprise_notification(
                    title=f"Heise+ Download Success: {magazine.upper()} {year}/{issue:02d}",
                    body=f"Successfully downloaded magazine '{magazine.upper()}' issue {issue:02d} from {year}.\nFile size: {size // 1024 // 1024} MB\nSaved to: {base_path}",
                    msg_type="success",
                    logger=logger,
                    verify_ssl=verify_ssl
                )
                return "success"
            else:
                logger.error(f"{log_pfx} Download failed or not a valid PDF (Size: {size} Bytes)")

        except Exception as e:
            logger.warning(f"{log_pfx} Request exception during attempt {try_num}: {e}")

        if try_num < MAX_TRIES:
            sleepbar(WAIT_TIME, prefix="Retry delay", logger=logger)

    logger.error(f"{log_pfx} [\033[0;31mERROR\033[0m] Download failed after {MAX_TRIES} attempts.")
    send_apprise_notification(
        title=f"Heise+ Download Error: {magazine.upper()} {year}/{issue:02d}",
        body=f"Failed to download magazine '{magazine.upper()}' issue {issue:02d} from {year} after {MAX_TRIES} attempts.",
        msg_type="error",
        logger=logger,
        verify_ssl=verify_ssl
    )
    return "fail"


def main():
    args = parse_arguments()

    verify_ssl = False if args.insecure else DEFAULT_VERIFY_SSL
    if not verify_ssl:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    logger = setup_logger(args.verbose)

    target_download_dir = args.download_dir or DOWNLOAD_DIR
    try:
        Path(target_download_dir).mkdir(parents=True, exist_ok=True)
    except Exception as dir_err:
        logger.error(f"Cannot create or access target download directory '{target_download_dir}': {dir_err}")
        sys.exit(1)

    heise_username = os.environ.get("HEISE_USERNAME")
    heise_password = os.environ.get("HEISE_PASSWORD")

    if not heise_username or not heise_password:
        logger.error("HEISE_USERNAME or HEISE_PASSWORD not found in .env or environment variables!")
        sys.exit(1)

    ping_healthcheck("start", logger=logger, verify_ssl=verify_ssl)

    masked_user = mask_username(heise_username)
    logger.info("----------- Heis-O-Mat Starting Up -----------")
    logger.info(f"[SETTINGS] (DOWNLOAD_DIR) Target download directory : {target_download_dir}")
    logger.info(f"[SETTINGS] (APPRISE_URL) Apprise notifications      : {'Enabled' if APPRISE_URL else 'Disabled'}")
    logger.info(f"[SETTINGS] (HEALTHCHECK_URL) Healthchecks.io ping   : {'Enabled' if HEALTHCHECK_URL else 'Disabled'}")
    logger.info(f"[SETTINGS] (SSL_VERIFICATION) Certificate validation: {'Enabled' if verify_ssl else 'Disabled (Insecure)'}")
    logger.info(f"[SETTINGS] (HEISE_USERNAME) Username for Login      : {masked_user}")

    session = get_login_session(
        logger=logger,
        heise_username=heise_username,
        heise_password=heise_password,
        verbose=args.verbose,
        verify_ssl=verify_ssl
    )

    count_success = 0
    count_fail = 0
    count_skip = 0

    magazine_key = args.magazine.upper()
    config = MAGAZINE_CONFIG.get(magazine_key, MAGAZINE_CONFIG["DEFAULT"])
    magazine_name = config["name"]
    max_issues = config["max_issues"]

    if args.verbose:
        logger.debug(f"Configured max issues: {max_issues} for magazine '{magazine_key}' ({magazine_name})")

    for year in range(args.start_year, args.end_year + 1):
        if args.verbose:
            logger.debug(f"Processing Year {year}")

        missing_consecutive = 0

        for i in range(1, max_issues + 1):
            issue_str = f"{i:02d}"
            base_dir = Path(target_download_dir) / magazine_name / f"{magazine_name} {year}"
            base_path = base_dir / f"{magazine_name}.{year}.{issue_str}.pdf"
            log_pfx = f"[{args.magazine}][{year}/{issue_str}]"

            if base_path.exists():
                count_skip += 1
                logger.info(f"[SKIP] {log_pfx} Already exists ({base_path}).")
                continue

            thumb_url = f"https://heise.cloudimg.io/v7/_www-heise-de_/select/thumbnail/{args.magazine}/{year}/{i}.jpg"
            try:
                thumb_res = session.get(thumb_url, verify=verify_ssl, timeout=DEFAULT_TIMEOUT)
                thumb_status = thumb_res.status_code
            except Exception as e:
                if args.verbose:
                    logger.warning(f"{log_pfx} Error fetching thumbnail: {e}")
                thumb_status = None

            if thumb_status != 200:
                missing_consecutive += 1
                if args.verbose:
                    logger.warning(f"{log_pfx} Issue might not (yet) exist - Thumbnail ({thumb_url}) status: {thumb_status}.")
                if missing_consecutive >= 3:
                    if args.verbose:
                        logger.info(f"Stopping year {year}: 3 consecutive issues missing.")
                    break
                continue

            missing_consecutive = 0
            if args.verbose:
                logger.debug(f"{log_pfx} Issue found. Starting download sequence.")

            result = download_issue(
                session=session,
                magazine=args.magazine,
                year=year,
                issue=i,
                magazine_name=magazine_name,
                target_dir=target_download_dir,
                logger=logger,
                verbose=args.verbose,
                verify_ssl=verify_ssl
            )
            if result == "success":
                count_success += 1
            else:
                count_fail += 1

    summary_message = f"Heis-O-Mat has finished! {count_success} ok, {count_fail} failed, {count_skip} skipped."
    logger.info(f"----------- {summary_message} -----------")

    if count_fail > 0:
        ping_healthcheck("fail", body=summary_message, logger=logger, verify_ssl=verify_ssl)
    else:
        ping_healthcheck("success", body=summary_message, logger=logger, verify_ssl=verify_ssl)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[INFO] Cancellation requested by user. Shutting down.")
        ping_healthcheck("fail", body="Process cancelled by user (KeyboardInterrupt).")
        sys.exit(130)
    except SystemExit as e:
        if e.code != 0:
            ping_healthcheck("fail", body=f"Process exited with code {e.code}")
        sys.exit(e.code)
    except Exception as e:
        tb_str = traceback.format_exc()
        print(f"\n[ERROR] An unexpected error occurred: {e}", file=sys.stderr)
        ping_healthcheck("fail", body=f"Process crashed with exception:\n{tb_str}")
        sys.exit(1)
