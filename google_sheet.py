import os, json, gspread
from google.oauth2.service_account import Credentials

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOCAL_JSON = os.path.join(BASE_DIR, "service_account.json")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

def get_credentials():
    # ===== 1. ENV (Render) =====
    if "GOOGLE_SERVICE_ACCOUNT_JSON" in os.environ:
        print("✅ Using GOOGLE_SERVICE_ACCOUNT_JSON from ENV")
        service_account_info = json.loads(
            os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
        )
        return Credentials.from_service_account_info(
            service_account_info,
            scopes=SCOPES
        )

    # ===== 2. LOCAL FILE (ABSOLUTE PATH) =====
    if os.path.exists(LOCAL_JSON):
        print("✅ Using local service_account.json:", LOCAL_JSON)
        return Credentials.from_service_account_file(
            LOCAL_JSON,
            scopes=SCOPES
        )

    # ===== 3. DEBUG INFO =====
    raise RuntimeError(
        f"❌ Không tìm thấy credential\n"
        f"- ENV GOOGLE_SERVICE_ACCOUNT_JSON: {'Có' if 'GOOGLE_SERVICE_ACCOUNT_JSON' in os.environ else 'Không'}\n"
        f"- File local: {LOCAL_JSON}"
    )


def save_booking(data):
    creds = get_credentials()
    client = gspread.authorize(creds)

    sheet = client.open("EDEN Bookings").sheet1

    sheet.append_row([
        data.get("checkin"),
        data.get("checkout"),
        data.get("room"),
        data.get("guests"),
        data.get("name"),
        data.get("phone"),
        data.get("note")
    ])
