"""
RFQ Intelligence Processor
Migrated from Google Apps Script (code.gs) to Python for deployment on Google Cloud Run.
Runs as a Cloud Run Job triggered by Cloud Scheduler.
"""

import os
import re
import sys
import json
import base64
import logging
import time
from io import BytesIO
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

# Load .env file automatically when running locally.
# In Cloud Run, env vars are injected by Secret Manager — dotenv is a no-op there.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import google.generativeai as genai

# ---------------------------------------------------------------------------
# LOGGING
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# Suppress noisy "file_cache is only supported with oauth2client<4.0.0" warning
logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.ERROR)

# ---------------------------------------------------------------------------
# CONFIGURATION (from environment variables)
# ---------------------------------------------------------------------------
PARENT_FOLDER_ID        = os.environ.get("PARENT_FOLDER_ID", "")
SHEET_ID                = os.environ.get("SHEET_ID", "")
GEMINI_API_KEY          = os.environ.get("GEMINI_API_KEY", "")
SEARCH_QUERY            = os.environ.get("SEARCH_QUERY", "subject:RFQ -label:PROCESSED_BY_BOT")
PROCESSED_LABEL_NAME    = os.environ.get("PROCESSED_LABEL_NAME", "PROCESSED_BY_BOT")
BATCH_SIZE              = int(os.environ.get("BATCH_SIZE", "20"))
GMAIL_USER_EMAIL        = os.environ.get("GMAIL_USER_EMAIL", "")
SLEEP_BETWEEN_THREADS   = int(os.environ.get("SLEEP_BETWEEN_THREADS", "30"))
# Domain used to distinguish internal (your team) vs external (customer) emails for TAT calculation.
# Mirrors the hardcoded "@orbee.com.qa" check in code.gs updateTimelineSheet().
INTERNAL_DOMAIN         = os.environ.get("INTERNAL_DOMAIN", "@orbee.com.qa")

# Auth — three supported methods (checked in priority order):
#   1. OAUTH_TOKEN_PATH  — path to a saved OAuth2 token JSON (local personal Gmail)
#   2. SERVICE_ACCOUNT_KEY_PATH — path to a SA key JSON file (local Workspace testing)
#   3. SERVICE_ACCOUNT_JSON — inline SA JSON string (Cloud Run / Secret Manager)
SERVICE_ACCOUNT_JSON    = os.environ.get("SERVICE_ACCOUNT_JSON", "")
SERVICE_ACCOUNT_KEY_PATH = os.environ.get("SERVICE_ACCOUNT_KEY_PATH", "")
OAUTH_TOKEN_PATH        = os.environ.get("OAUTH_TOKEN_PATH", "token.json")
OAUTH_CREDENTIALS_PATH  = os.environ.get("OAUTH_CREDENTIALS_PATH", "credentials.json")

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
]

# ---------------------------------------------------------------------------
# AUTHENTICATION
# ---------------------------------------------------------------------------

def build_credentials():
    """
    Load credentials using one of three methods (checked in priority order):

    1. OAuth2 token file  — OAUTH_TOKEN_PATH exists (local personal Gmail use)
       Created once by running: python auth_setup.py
       Refreshes automatically using the stored refresh_token.

    2. SA key file        — SERVICE_ACCOUNT_KEY_PATH is set (local Workspace testing)
       Point to a downloaded service account JSON key file.

    3. SA JSON string     — SERVICE_ACCOUNT_JSON is set (Cloud Run / Secret Manager)
       The full JSON content as a single-line string env var.

    Methods 2 and 3 require GMAIL_USER_EMAIL for Domain-Wide Delegation.
    Method 1 does not (it acts directly as the authenticated user).
    """
    # --- Method 1: OAuth2 token (personal Gmail or any Google account) ---
    if os.path.exists(OAUTH_TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(OAUTH_TOKEN_PATH, SCOPES)
        if creds.expired and creds.refresh_token:
            log.info("Refreshing OAuth2 access token...")
            creds.refresh(Request())
            # Persist the refreshed token
            with open(OAUTH_TOKEN_PATH, "w") as f:
                f.write(creds.to_json())
        if creds.valid:
            log.info("Auth: using OAuth2 token from '%s'", OAUTH_TOKEN_PATH)
            return creds

    # --- Method 2: SA key file (local path) ---
    if SERVICE_ACCOUNT_KEY_PATH:
        if not os.path.exists(SERVICE_ACCOUNT_KEY_PATH):
            raise RuntimeError(f"SERVICE_ACCOUNT_KEY_PATH file not found: {SERVICE_ACCOUNT_KEY_PATH}")
        if not GMAIL_USER_EMAIL:
            raise RuntimeError("GMAIL_USER_EMAIL must be set when using a Service Account.")
        creds = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_KEY_PATH, scopes=SCOPES
        )
        log.info("Auth: using Service Account key file '%s'", SERVICE_ACCOUNT_KEY_PATH)
        return creds.with_subject(GMAIL_USER_EMAIL)

    # --- Method 3: SA JSON string (Cloud Run) ---
    if SERVICE_ACCOUNT_JSON:
        if not GMAIL_USER_EMAIL:
            raise RuntimeError("GMAIL_USER_EMAIL must be set when using a Service Account.")
        info = json.loads(SERVICE_ACCOUNT_JSON)
        creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        log.info("Auth: using Service Account JSON string (Cloud Run mode)")
        return creds.with_subject(GMAIL_USER_EMAIL)

    raise RuntimeError(
        "No authentication credentials found. Provide one of:\n"
        "  - Run 'python auth_setup.py' to create a local OAuth2 token (personal Gmail)\n"
        "  - Set SERVICE_ACCOUNT_KEY_PATH to a SA key file (Google Workspace)\n"
        "  - Set SERVICE_ACCOUNT_JSON with the SA JSON string (Cloud Run)"
    )


def build_api_clients():
    """Build and return Gmail, Drive, and Sheets API clients."""
    creds = build_credentials()
    gmail  = build("gmail",  "v1", credentials=creds)
    drive  = build("drive",  "v3", credentials=creds)
    sheets = build("sheets", "v4", credentials=creds)
    return gmail, drive, sheets


# ---------------------------------------------------------------------------
# UTILITIES
# ---------------------------------------------------------------------------

def extract_rfq_id(text: str) -> str | None:
    """
    Extract RFQ ID from subject line.
    Matches patterns like RFQ-GEN-PRP-1317, RFQ-1234, RFQ GEN 1234 etc.
    Mirrors the Apps Script extractRfqId() regex exactly.
    """
    match = re.search(r"(RFQ[-a-zA-Z\s]+\d+)", text, re.IGNORECASE)
    if match:
        # Normalise: uppercase, collapse spaces, collapse duplicate hyphens
        return re.sub(r"-+", "-", match.group(0).upper().replace(" ", ""))
    return None


def sanitize_name(name: str, max_len: int = 50) -> str:
    """Strip characters illegal in Drive/Sheets names and truncate."""
    sanitized = re.sub(r'[\\/:*?"<>|]', "_", name)
    return sanitized[:max_len]


def now_timestamp() -> str:
    """Return current UTC time as YYYY-MM-DD HH:MM:SS — mirrors Apps Script currentTimestamp format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def parse_email_date(date_header: str) -> datetime:
    """Parse an RFC 2822 email Date header into a datetime object."""
    try:
        return parsedate_to_datetime(date_header)
    except Exception:
        return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# GMAIL HELPERS
# ---------------------------------------------------------------------------

def search_gmail_threads(gmail, query: str, max_results: int) -> list:
    """Return a list of thread stubs matching the query."""
    result = gmail.users().threads().list(
        userId="me", q=query, maxResults=max_results
    ).execute()
    return result.get("threads", [])


def get_thread_full(gmail, thread_id: str) -> dict:
    """Fetch full thread data including all messages."""
    return gmail.users().threads().get(
        userId="me", id=thread_id, format="full"
    ).execute()


def get_header(message: dict, name: str) -> str:
    """Extract a specific header value from a Gmail message."""
    headers = message.get("payload", {}).get("headers", [])
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def decode_part_body(part: dict) -> bytes:
    """Base64url-decode the body data of a message part."""
    data = part.get("body", {}).get("data", "")
    if not data:
        return b""
    # Add padding if needed
    return base64.urlsafe_b64decode(data + "==")


def extract_text_from_payload(payload: dict, mime_type: str) -> str:
    """
    Recursively walk the MIME payload tree to find text of the given mime_type.
    Email MIME trees can be deeply nested: multipart/mixed > multipart/alternative > text/html
    """
    if payload.get("mimeType") == mime_type:
        return decode_part_body(payload).decode("utf-8", errors="replace")
    for part in payload.get("parts", []):
        result = extract_text_from_payload(part, mime_type)
        if result:
            return result
    return ""


def get_message_attachments(message: dict) -> list:
    """
    Return a list of part dicts that represent attachments.
    Handles both referenced attachments (attachmentId) and inline data.
    """
    results = []

    def walk(parts):
        for part in parts:
            filename = part.get("filename", "")
            body = part.get("body", {})
            # It's an attachment if it has a filename AND either an attachmentId or inline data
            if filename and (body.get("attachmentId") or body.get("data")):
                results.append(part)
            walk(part.get("parts", []))

    walk(message.get("payload", {}).get("parts", []))
    return results


def fetch_attachment(gmail, message_id: str, part: dict) -> tuple:
    """
    Download attachment bytes. Returns (bytes, filename, mime_type, size_bytes).
    Large attachments come via attachmentId; small ones may have inline data.
    """
    filename = part.get("filename", "Unnamed")
    mime_type = part.get("mimeType", "application/octet-stream")
    body = part.get("body", {})
    attachment_id = body.get("attachmentId")

    if attachment_id:
        att = gmail.users().messages().attachments().get(
            userId="me", messageId=message_id, id=attachment_id
        ).execute()
        data = att.get("data", "")
    else:
        data = body.get("data", "")

    att_bytes = base64.urlsafe_b64decode(data + "==") if data else b""
    return att_bytes, filename, mime_type, len(att_bytes)


def get_or_create_label(gmail, name: str) -> str:
    """Return the label ID for the given name, creating it if it doesn't exist."""
    labels = gmail.users().labels().list(userId="me").execute().get("labels", [])
    for label in labels:
        if label.get("name") == name:
            return label["id"]
    new_label = gmail.users().labels().create(
        userId="me", body={"name": name}
    ).execute()
    return new_label["id"]


def label_thread(gmail, thread_id: str, label_id: str):
    """Apply a label to a Gmail thread."""
    gmail.users().threads().modify(
        userId="me",
        id=thread_id,
        body={"addLabelIds": [label_id]}
    ).execute()


# ---------------------------------------------------------------------------
# DRIVE HELPERS
# ---------------------------------------------------------------------------

def search_drive_folders(drive, parent_id: str, query: str) -> list:
    """Search for folders inside parent_id matching the query string."""
    q = f"mimeType='application/vnd.google-apps.folder' and '{parent_id}' in parents and trashed=false and {query}"
    result = drive.files().list(q=q, fields="files(id, name)").execute()
    return result.get("files", [])


def create_drive_folder(drive, name: str, parent_id: str) -> str:
    """Create a new Drive folder inside parent_id. Returns the new folder ID."""
    file_meta = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    folder = drive.files().create(body=file_meta, fields="id").execute()
    return folder["id"]


def find_or_create_rfq_folder(drive, rfq_id: str | None, subject: str) -> str:
    """
    Mirrors the Apps Script smart folder finding logic:
    1. Search for existing folder by RFQ ID substring
    2. Fall back to exact name match of the sanitized subject
    3. Create only if truly not found
    Returns the folder ID.
    """
    # Step 1: Search by RFQ ID
    if rfq_id:
        safe_rfq = rfq_id.replace("'", "\\'")
        folders = search_drive_folders(drive, PARENT_FOLDER_ID, f"name contains '{safe_rfq}'")
        if folders:
            return folders[0]["id"]

    # Step 2: Build the fallback name
    if rfq_id:
        temp_name = sanitize_name(rfq_id + " - " + subject)
    else:
        temp_name = sanitize_name(subject)

    # Step 3: Exact name match to prevent duplicates
    safe_name = temp_name.replace("'", "\\'")
    folders = search_drive_folders(drive, PARENT_FOLDER_ID, f"name = '{safe_name}'")
    if folders:
        return folders[0]["id"]

    # Step 4: Create new
    return create_drive_folder(drive, temp_name, PARENT_FOLDER_ID)


def file_exists_in_folder(drive, filename: str, folder_id: str) -> str | None:
    """Return the file ID if a file with this name exists in the folder, else None."""
    safe_name = filename.replace("'", "\\'")
    q = f"name='{safe_name}' and '{folder_id}' in parents and trashed=false"
    result = drive.files().list(q=q, fields="files(id)").execute()
    files = result.get("files", [])
    return files[0]["id"] if files else None


def upload_file_to_drive(drive, data: BytesIO, filename: str, mime_type: str, folder_id: str) -> str:
    """Upload a file to Drive. Returns the new file ID."""
    file_meta = {"name": filename, "parents": [folder_id]}
    media = MediaIoBaseUpload(data, mimetype=mime_type, resumable=False)
    uploaded = drive.files().create(
        body=file_meta, media_body=media, fields="id"
    ).execute()
    return uploaded["id"]


def rename_drive_folder(drive, folder_id: str, rfq_id: str, client_name: str):
    """
    Rename a Drive folder to 'RFQ-ID - CLIENT NAME'.
    Mirrors code.gs: only renames if the name has actually changed (avoids unnecessary API call).
    """
    clean_client = re.sub(r'[\\/:*?"<>|]', "", client_name.upper())
    new_name = rfq_id + " - " + clean_client
    current = drive.files().get(fileId=folder_id, fields="name").execute().get("name", "")
    if current != new_name:
        drive.files().update(fileId=folder_id, body={"name": new_name}).execute()
        log.info(f"Renamed folder to: {new_name}")


def _html_to_pdf_bytes(html: str) -> bytes:
    """
    Convert an HTML string to PDF bytes.
    Tries weasyprint first (best quality, used in Docker/Linux).
    Falls back to xhtml2pdf (pure Python, works on Windows without system libraries).
    """
    import io

    # Try weasyprint (requires GTK/Pango/Cairo — available in Docker, not on bare Windows).
    # Redirect stderr to suppress the "could not import external libraries" banner it prints
    # to stderr before raising OSError on Windows.
    try:
        import sys
        _stderr, sys.stderr = sys.stderr, io.StringIO()
        try:
            from weasyprint import HTML
            result = HTML(string=html).write_pdf()
        finally:
            sys.stderr = _stderr
        if result:
            return result
    except Exception:
        # Catch all exceptions (ImportError, OSError, ValueError, etc.)
        # Some email HTML may cause weasyprint to crash unexpectedly
        pass

    # Fall back to xhtml2pdf (pure Python, no system dependencies).
    # Suppress its verbose cid: image and attribute warnings — they are expected because
    # email HTML uses Content-ID image references that can't be resolved without the raw parts.
    try:
        from xhtml2pdf import pisa
        logging.getLogger("xhtml2pdf").setLevel(logging.CRITICAL)
        logging.getLogger("xhtml2pdf.context").setLevel(logging.CRITICAL)
        buf = BytesIO()
        pisa.CreatePDF(html, dest=buf)
        pdf_data = buf.getvalue()
        if pdf_data:
            return pdf_data
    except Exception:
        # Catch all exceptions, not just ImportError
        pass

    raise RuntimeError("No PDF library available. Install weasyprint (Linux) or xhtml2pdf (Windows).")


def save_email_body_as_pdf(drive, message: dict, folder_id: str, index: int) -> str | None:
    """
    Convert the HTML body of a Gmail message to a PDF and save to Drive.
    Uses weasyprint on Linux/Docker, xhtml2pdf on Windows as fallback.
    Returns the Drive file ID, or None on failure.
    """
    subject = get_header(message, "Subject")
    date_str = parse_email_date(get_header(message, "Date")).strftime("%Y-%m-%d")
    safe_subject = sanitize_name(subject)
    filename = f"Email_{date_str}_{safe_subject}_{index}.pdf"

    existing_id = file_exists_in_folder(drive, filename, folder_id)
    if existing_id:
        return existing_id

    html_body = extract_text_from_payload(message["payload"], "text/html")
    if not html_body:
        plain = extract_text_from_payload(message["payload"], "text/plain")
        html_body = f"<pre>{plain}</pre>"

    full_html = f"<h3>{subject}</h3>{html_body}"
    try:
        pdf_bytes = _html_to_pdf_bytes(full_html)
        return upload_file_to_drive(drive, BytesIO(pdf_bytes), filename, "application/pdf", folder_id)
    except Exception as e:
        log.error(f"PDF generation failed for '{filename}': {e}")
        return None


def save_attachment_to_drive(drive, att_bytes: bytes, att_name: str, mime_type: str,
                              folder_id: str, message: dict, index: int) -> str:
    """
    Save an email attachment to Drive with a date-prefixed deduplicated name.
    Mirrors Apps Script saveAttachment().
    """
    subject = get_header(message, "Subject")
    date_str = parse_email_date(get_header(message, "Date")).strftime("%Y-%m-%d")
    safe_subject = sanitize_name(subject)

    original_name = att_name[:100] if len(att_name) > 100 else att_name
    new_name = f"Att_{date_str}_{safe_subject}_{index}_{original_name}"

    existing_id = file_exists_in_folder(drive, new_name, folder_id)
    if existing_id:
        return existing_id

    return upload_file_to_drive(drive, BytesIO(att_bytes), new_name, mime_type, folder_id)


def save_log_file(drive, folder_id: str, subject: str, error_message: str | None, skipped_files: list):
    """
    Save an error log or audit log as a plain text file to Drive.
    Mirrors Apps Script saveErrorLogFile().
    """
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
    if error_message:
        filename = f"ErrorLog_{date_str}.txt"
        content = (
            "=========================================\n"
            "ERROR LOG - RFQ AUTOMATION SYSTEM\n"
            "=========================================\n"
            f"Timestamp: {datetime.now(timezone.utc)}\n"
            f"Subject: {subject}\n\n"
            f"Error Details:\n{error_message}\n"
            "=========================================\n"
            "Note: The bot skipped labeling this thread and will retry automatically.\n\n"
        )
    else:
        filename = f"AuditLog_SkippedFiles_{date_str}.txt"
        content = (
            "=========================================\n"
            "AUDIT LOG - SKIPPED FILES\n"
            "=========================================\n"
            f"Timestamp: {datetime.now(timezone.utc)}\n"
            f"Subject: {subject}\n\n"
        )

    if skipped_files:
        content += "Skipped Inline Images (Likely Signatures/Logos):\n"
        for f in skipped_files:
            content += f"- {f}\n"
        content += "\n=========================================\n"

    upload_file_to_drive(
        drive, BytesIO(content.encode("utf-8")), filename, "text/plain", folder_id
    )


# ---------------------------------------------------------------------------
# SHEETS HELPERS
# ---------------------------------------------------------------------------

def get_existing_row_data(sheets_svc, rfq_id: str) -> dict | None:
    """
    Find an existing row in the master sheet by RFQ ID (column B).
    Mirrors Apps Script getExistingRowData().
    Returns a dict of the row data, or None if not found.
    """
    result = sheets_svc.spreadsheets().values().get(
        spreadsheetId=SHEET_ID, range="Sheet1!B:B"
    ).execute()
    rows = result.get("values", [])

    for i, row in enumerate(rows):
        if row and rfq_id in row[0]:
            row_num = i + 1  # 1-based
            full = sheets_svc.spreadsheets().values().get(
                spreadsheetId=SHEET_ID,
                range=f"Sheet1!A{row_num}:P{row_num}"
            ).execute().get("values", [[]])[0]
            # Pad to 16 columns (A–P, column P is avg_tat)
            full += [""] * (16 - len(full))
            return {
                "system_created_date": full[0],
                "rfq_id":              full[1],
                "client_name":         full[2],
                "insurer":             full[3],
                "premium":             full[4],
                "status":              full[5],
                "policy_type":         full[6],
                "sentiment":           full[7],
                "urgency":             full[8],
                "missing_docs":        full[9],
                "avg_tat":             full[15],
            }
    return None


def update_or_append_sheet_row(sheets_svc, data: dict, folder_url: str,
                                original_id: str | None, existing_context: dict | None,
                                calculated_avg_tat: str = ""):
    """
    Upsert a 16-column row (A–P) in the master sheet.
    Column P is avg_tat, computed by update_timeline_sheet() and passed in.
    Mirrors Apps Script updateOrAppendSheetRow() including the calculatedAvgTat parameter.
    """
    today = now_timestamp()
    final_id = data.get("rfq_id") or original_id or "N/A"
    created_date = (existing_context or {}).get("system_created_date") or today
    # Preserve existing avg_tat if this run didn't produce a new one
    avg_tat = calculated_avg_tat or (existing_context or {}).get("avg_tat", "")

    row_data = [[
        created_date,
        final_id,
        data.get("client_name", "Unknown"),
        data.get("insurer", "Unknown"),
        data.get("premium", 0),
        data.get("status", "Pending"),
        data.get("policy_type", "General"),
        data.get("sentiment", "Neutral"),
        data.get("urgency", "Low"),
        data.get("missing_docs", "None"),
        data.get("competitor", "None"),
        folder_url,
        today,
        data.get("thread_created_date", "Unknown"),
        data.get("thread_last_modified_date", "Unknown"),
        avg_tat,
    ]]

    # Find existing row index
    b_col = sheets_svc.spreadsheets().values().get(
        spreadsheetId=SHEET_ID, range="Sheet1!B:B"
    ).execute().get("values", [])

    row_number = None
    if final_id != "N/A":
        for i, row in enumerate(b_col):
            if row and final_id in row[0]:
                row_number = i + 1
                break

    if row_number:
        sheets_svc.spreadsheets().values().update(
            spreadsheetId=SHEET_ID,
            range=f"Sheet1!A{row_number}:P{row_number}",
            valueInputOption="USER_ENTERED",
            body={"values": row_data},
        ).execute()
    else:
        sheets_svc.spreadsheets().values().append(
            spreadsheetId=SHEET_ID,
            range="Sheet1!A:P",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": row_data},
        ).execute()


def _calculate_tat(rows: list, internal_domain: str) -> tuple[list, str]:
    """
    Sort timeline rows chronologically, then compute Turnaround Time (Hrs) for each
    internal response that follows a customer email.
    Mirrors Apps Script TAT logic in updateTimelineSheet():
      - Identifies internal emails by INTERNAL_DOMAIN or 'orbee' in the sender address.
      - TAT = time from first customer email to next internal reply.
      - Returns the sorted rows (each a 5-element list) and the average TAT string.
    """
    # Parse dates for sorting; rows are 5-element lists [date, sender, summary, tat, avg_tat]
    parsed = []
    for r in rows:
        date_val = r[0]
        try:
            d = datetime.strptime(str(date_val), "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            try:
                d = datetime.strptime(str(date_val).replace("-", "/"), "%Y/%m/%d %H:%M:%S")
            except Exception:
                d = datetime.min
        parsed.append((d, r))

    parsed.sort(key=lambda x: x[0])

    first_customer_time = None
    total_tat = 0.0
    tat_count = 0

    for row_date, row in parsed:
        sender = str(row[1]).lower()
        is_internal = internal_domain.lower() in sender or "orbee" in sender

        row[3] = ""  # reset TAT column
        row[4] = ""  # reset avg TAT column

        if not is_internal:
            if first_customer_time is None:
                first_customer_time = row_date
        else:
            if first_customer_time is not None:
                diff_hours = (row_date - first_customer_time).total_seconds() / 3600
                row[3] = f"{diff_hours:.2f}"
                total_tat += diff_hours
                tat_count += 1
                first_customer_time = None

    avg_tat = f"{total_tat / tat_count:.2f}" if tat_count > 0 else ""
    sorted_rows = [r for _, r in parsed]

    # Write average TAT on the first data row (mirrors code.gs: rows[0][4] = avgTat)
    if sorted_rows:
        sorted_rows[0][4] = avg_tat

    return sorted_rows, avg_tat


def update_timeline_sheet(drive, sheets_svc, rfq_folder_id: str, rfq_id: str,
                           client_name: str | None, timeline_data: list) -> str:
    """
    Create or update the per-RFQ Timeline Dossier spreadsheet inside the RFQ folder.
    5 columns: Date | Sender | Summary | Turnaround Time (Hrs) | Average TAT (Hrs)
    Deduplicates rows using a date+sender+summary_prefix key.
    Calculates TAT using INTERNAL_DOMAIN to identify internal vs customer emails.
    Returns the computed average TAT string (empty string if not calculable).
    Mirrors Apps Script updateTimelineSheet() including TAT logic.
    """
    safe_client = re.sub(r'[\\/:*?"<>|]', "", (client_name or "Unknown").upper())
    ss_name = f"Timeline_{rfq_id}_{safe_client}"

    # Search by RFQ ID prefix only (not full name) so we find the sheet even if the
    # client name was updated/extended by a later email in the same thread chain.
    safe_rfq = rfq_id.replace("'", "\\'")
    q = f"name contains 'Timeline_{safe_rfq}' and '{rfq_folder_id}' in parents and trashed=false"
    existing = drive.files().list(q=q, fields="files(id, name)").execute().get("files", [])

    if existing:
        ss_id = existing[0]["id"]
        # Rename the sheet if the client name has become more accurate
        if existing[0]["name"] != ss_name:
            drive.files().update(fileId=ss_id, body={"name": ss_name}).execute()
            log.info(f"Renamed timeline sheet to: {ss_name}")
    else:
        # Create via Sheets API (lands in My Drive root)
        ss = sheets_svc.spreadsheets().create(
            body={"properties": {"title": ss_name}}
        ).execute()
        ss_id = ss["spreadsheetId"]

        # Move into RFQ folder using Drive API
        file_meta = drive.files().get(fileId=ss_id, fields="parents").execute()
        old_parents = ",".join(file_meta.get("parents", []))
        drive.files().update(
            fileId=ss_id,
            addParents=rfq_folder_id,
            removeParents=old_parents,
            fields="id, parents",
        ).execute()

        # Write 5-column header with bold + grey background.
        # Mirrors code.gs: ["Date","Sender","Summary","Turnaround Time (Hrs)","Average TAT (Hrs)"]
        sheets_svc.spreadsheets().values().update(
            spreadsheetId=ss_id,
            range="Sheet1!A1:E1",
            valueInputOption="RAW",
            body={"values": [["Date", "Sender", "Summary", "Turnaround Time (Hrs)", "Average TAT (Hrs)"]]},
        ).execute()
        sheets_svc.spreadsheets().batchUpdate(
            spreadsheetId=ss_id,
            body={"requests": [
                # Bold + grey background on header row (A:E)
                {"repeatCell": {
                    "range": {"sheetId": 0, "startRowIndex": 0, "endRowIndex": 1,
                               "startColumnIndex": 0, "endColumnIndex": 5},
                    "cell": {"userEnteredFormat": {
                        "textFormat": {"bold": True},
                        "backgroundColor": {"red": 0.953, "green": 0.953, "blue": 0.953}
                    }},
                    "fields": "userEnteredFormat(textFormat,backgroundColor)"
                }},
                # Column A width: 150px
                {"updateDimensionProperties": {
                    "range": {"sheetId": 0, "dimension": "COLUMNS",
                               "startIndex": 0, "endIndex": 1},
                    "properties": {"pixelSize": 150},
                    "fields": "pixelSize"
                }},
                # Column B width: 250px
                {"updateDimensionProperties": {
                    "range": {"sheetId": 0, "dimension": "COLUMNS",
                               "startIndex": 1, "endIndex": 2},
                    "properties": {"pixelSize": 250},
                    "fields": "pixelSize"
                }},
                # Column C width: 600px
                {"updateDimensionProperties": {
                    "range": {"sheetId": 0, "dimension": "COLUMNS",
                               "startIndex": 2, "endIndex": 3},
                    "properties": {"pixelSize": 600},
                    "fields": "pixelSize"
                }},
                # Column D width: 150px (Turnaround Time)
                {"updateDimensionProperties": {
                    "range": {"sheetId": 0, "dimension": "COLUMNS",
                               "startIndex": 3, "endIndex": 4},
                    "properties": {"pixelSize": 150},
                    "fields": "pixelSize"
                }},
                # Column E width: 150px (Average TAT)
                {"updateDimensionProperties": {
                    "range": {"sheetId": 0, "dimension": "COLUMNS",
                               "startIndex": 4, "endIndex": 5},
                    "properties": {"pixelSize": 150},
                    "fields": "pixelSize"
                }},
            ]}
        ).execute()

    # Fetch all existing rows (5 columns) for deduplication
    existing_rows = sheets_svc.spreadsheets().values().get(
        spreadsheetId=ss_id, range="Sheet1!A:E"
    ).execute().get("values", [])

    existing_keys: set[str] = set()
    all_data_rows: list[list] = []
    for row in existing_rows[1:]:  # skip header
        row += [""] * (5 - len(row))  # pad to 5 cols
        if len(row) >= 3:
            key = f"{row[0]}_{row[1]}_{str(row[2])[:30]}"
            existing_keys.add(key)
        all_data_rows.append(row[:5])

    # Merge in any new rows from this run
    for item in timeline_data:
        key = f"{item.get('date','')}_{item.get('sender','')}_{str(item.get('summary',''))[:30]}"
        if key not in existing_keys:
            all_data_rows.append([
                item.get("date", ""),
                item.get("sender", ""),
                item.get("summary", ""),
                "",  # TAT — will be computed below
                "",  # Avg TAT — will be computed below
            ])
            existing_keys.add(key)

    if not all_data_rows:
        return ""

    # Recalculate TAT for the full dataset (sorts chronologically, computes per-response TAT)
    sorted_rows, avg_tat = _calculate_tat(all_data_rows, INTERNAL_DOMAIN)

    # Rewrite the entire sheet (header + all data) so TAT values stay consistent
    output = [["Date", "Sender", "Summary", "Turnaround Time (Hrs)", "Average TAT (Hrs)"]]
    output.extend(sorted_rows)
    sheets_svc.spreadsheets().values().update(
        spreadsheetId=ss_id,
        range=f"Sheet1!A1:E{len(output)}",
        valueInputOption="USER_ENTERED",
        body={"values": output},
    ).execute()

    return avg_tat


# ---------------------------------------------------------------------------
# GEMINI AI
# ---------------------------------------------------------------------------

def call_gemini_stateful(email_text: str, pdf_attachments: list, existing_context: dict | None) -> dict | None:
    """
    Call Gemini 2.5 Flash with the full email history, optional PDF attachments,
    and existing sheet context for stateful merging.
    Mirrors Apps Script callGeminiStateful().
    Returns a parsed dict of extracted fields, or None on failure.
    """
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-2.5-flash")

    if existing_context:
        context_prompt = (
            f"CURRENT DATABASE RECORD (What we already know):\n{json.dumps(existing_context)}\n\n"
            "INSTRUCTION: Compare the New Email Data below with the Current Database Record.\n"
            "- If the new email adds info (e.g., new price, changed status), UPDATE the record.\n"
            "- If the new email is vague/generic, KEEP the old values from the Database Record.\n\n"
        )
    else:
        context_prompt = "CURRENT DATABASE RECORD: None (New Entry)\n\n"

    task_text = (
        "Analyze this Insurance RFQ.\n\n"
        + context_prompt
        + f"NEW EMAIL HISTORY:\n{email_text}\n\n"
        + "TASK: Return the final, merged JSON for this deal:\n"
        + "- rfq_id\n"
        + "- client_name (Extract the full official company name)\n"
        + "- insurer\n"
        + "- premium (Number only)\n"
        + "- status\n"
        + "- policy_type\n"
        + "- sentiment\n"
        + "- urgency\n"
        + "- missing_docs\n"
        + "- competitor\n"
        + "- thread_created_date (Format strictly as YYYY-MM-DD HH:MM:SS)\n"
        + "- thread_last_modified_date (Format strictly as YYYY-MM-DD HH:MM:SS)\n"
        + "- interaction_timeline (Array of objects for EACH email in the NEW EMAIL HISTORY. "
        + "Each object must have 'date' [Format strictly as YYYY-MM-DD HH:MM:SS], "
        + "'sender' [MUST extract the exact email address containing the @ symbol from the FROM line. Do not just return the person's name.], "
        + "and 'summary' [1-line summary of that specific email])\n"
        + "Return ONLY valid JSON."
    )

    # Build content parts: text prompt first, then PDFs
    content_parts = [task_text]
    for pdf_bytes, mime_type in pdf_attachments:
        content_parts.append({"mime_type": mime_type, "data": pdf_bytes})

    try:
        response = model.generate_content(content_parts)
        raw = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(raw)
    except json.JSONDecodeError as e:
        # Gemini responded but returned malformed JSON — include the raw response in the error
        # so the Drive ErrorLog captures exactly what Gemini sent back.
        raise RuntimeError(
            f"Gemini returned invalid JSON.\n"
            f"JSON parse error: {e}\n"
            f"Raw Gemini response (first 1000 chars):\n{response.text[:1000]}"
        ) from e
    except Exception as e:
        # Covers quota errors (429 ResourceExhausted), server errors (503), auth errors, etc.
        # Re-raise with the original error type and message preserved so the Drive ErrorLog
        # captures the real HTTP status code and error description.
        error_type = type(e).__name__
        raise RuntimeError(
            f"Gemini API call failed.\n"
            f"Error type: {error_type}\n"
            f"Details: {e}"
        ) from e


# ---------------------------------------------------------------------------
# MAIN PROCESSING LOOP
# ---------------------------------------------------------------------------

def process_rfqs():
    """
    Main entry point. Searches Gmail for unprocessed RFQ threads and processes each one.
    Sleeps SLEEP_BETWEEN_THREADS seconds between threads to avoid Gemini quota limits.
    """
    # Validate required config
    missing = [v for v in ["PARENT_FOLDER_ID", "SHEET_ID", "GEMINI_API_KEY"] if not os.environ.get(v)]
    if missing:
        log.critical(f"Missing required environment variables: {missing}")
        sys.exit(1)

    try:
        gmail, drive, sheets_svc = build_api_clients()
    except Exception as e:
        log.critical(f"Failed to build API clients: {e}")
        sys.exit(1)

    # Verify Drive parent folder is accessible
    try:
        drive.files().get(fileId=PARENT_FOLDER_ID, fields="id").execute()
    except Exception as e:
        log.critical(f"Cannot access PARENT_FOLDER_ID '{PARENT_FOLDER_ID}': {e}")
        sys.exit(1)

    label_id = get_or_create_label(gmail, PROCESSED_LABEL_NAME)
    threads = search_gmail_threads(gmail, SEARCH_QUERY, BATCH_SIZE)

    if not threads:
        log.info("No new RFQs found.")
        return

    log.info(f"Found {len(threads)} new thread(s) to process.")

    for thread_stub in threads:
        thread_id = thread_stub["id"]
        rfq_folder_id = None
        skipped_files = []
        subject = "(unknown)"

        try:
            thread_data = get_thread_full(gmail, thread_id)
            messages = thread_data.get("messages", [])
            if not messages:
                continue

            subject = get_header(messages[0], "Subject")
            log.info(f"Processing: '{subject}'")

            # 1. FIND OR CREATE FOLDER
            rfq_id = extract_rfq_id(subject)
            rfq_folder_id = find_or_create_rfq_folder(drive, rfq_id, subject)

            # 2. FETCH EXISTING CONTEXT
            existing_context = get_existing_row_data(sheets_svc, rfq_id) if rfq_id else None

            # 3. GATHER EMAIL DATA
            full_email_history = f"SUBJECT: {subject}\n\n"
            ai_attachments = []  # list of (bytes, mime_type) for PDFs to send to Gemini

            for idx, message in enumerate(messages):
                msg_from = get_header(message, "From")
                msg_date = get_header(message, "Date")
                msg_body = extract_text_from_payload(message["payload"], "text/plain")

                full_email_history += f"--- EMAIL {idx + 1} ---\n"
                full_email_history += f"FROM: {msg_from}\n"
                full_email_history += f"DATE: {msg_date}\n"
                full_email_history += f"BODY: {msg_body}\n\n"

                save_email_body_as_pdf(drive, message, rfq_folder_id, idx)

                for att_part in get_message_attachments(message):
                    att_bytes, att_name, att_mime, att_size = fetch_attachment(
                        gmail, message["id"], att_part
                    )

                    # JUNK FILTER: skip tiny inline images (< 20KB) — email signatures/logos
                    if att_mime.startswith("image/") and att_size < 20480:
                        skipped_files.append(
                            f"Email {idx + 1}: {att_name or 'Unnamed_Image'} ({att_size // 1024} KB)"
                        )
                        log.info(f"Skipped tiny inline image: {att_name}")
                        continue

                    saved_id = save_attachment_to_drive(
                        drive, att_bytes, att_name, att_mime, rfq_folder_id, message, idx
                    )

                    if att_mime == "application/pdf":
                        ai_attachments.append((att_bytes, att_mime))

            # 4. CALL GEMINI
            result = call_gemini_stateful(full_email_history, ai_attachments, existing_context)
            if not result:
                raise RuntimeError("Gemini API failed or returned empty response.")

            # 5. UPDATE TIMELINE DOSSIER FIRST (to get avg_tat), then master sheet.
            # Mirrors code.gs step order: updateTimelineSheet() → calculatedAvgTat → updateOrAppendSheetRow()
            folder_url = f"https://drive.google.com/drive/folders/{rfq_folder_id}"
            client_name = result.get("client_name", "Unknown")
            calculated_avg_tat = ""

            if rfq_id and isinstance(result.get("interaction_timeline"), list):
                calculated_avg_tat = update_timeline_sheet(
                    drive, sheets_svc, rfq_folder_id, rfq_id,
                    client_name, result["interaction_timeline"]
                )

            # 6. UPDATE MASTER SHEET (with avg_tat included)
            update_or_append_sheet_row(
                sheets_svc, result, folder_url, rfq_id, existing_context, calculated_avg_tat
            )

            if rfq_id and client_name and client_name != "Unknown":
                rename_drive_folder(drive, rfq_folder_id, rfq_id, client_name)

            # 7. LABEL THREAD AS PROCESSED
            label_thread(gmail, thread_id, label_id)
            log.info(f"Successfully processed and labeled: '{subject}'")

            # Save audit log if any files were skipped
            if skipped_files:
                save_log_file(drive, rfq_folder_id, subject, None, skipped_files)

        except Exception as err:
            log.error(f"Error processing thread '{subject}': {err}", exc_info=True)
            # Thread is NOT labeled — it will automatically retry on the next run
            if rfq_folder_id:
                save_log_file(drive, rfq_folder_id, subject, str(err), skipped_files)

        # Sleep between threads (not after the last one) to avoid hitting Gemini quota limits.
        # Mirrors the original Apps Script: if (i < threads.length - 1) Utilities.sleep(30000)
        if thread_stub is not threads[-1] and SLEEP_BETWEEN_THREADS > 0:
            log.info(f"Sleeping {SLEEP_BETWEEN_THREADS}s before next thread...")
            time.sleep(SLEEP_BETWEEN_THREADS)


# ---------------------------------------------------------------------------
# ENTRY POINT
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    try:
        process_rfqs()
        log.info("Run complete.")
        sys.exit(0)
    except SystemExit:
        raise
    except Exception as e:
        log.critical(f"Unhandled exception: {e}", exc_info=True)
        sys.exit(1)
