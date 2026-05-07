import os, json, gspread
from google.oauth2.service_account import Credentials

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOCAL_JSON = os.path.join(BASE_DIR, "service_account.json")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

SPREADSHEET_NAME = "EDEN Bookings"
ROOM_SHEET       = "Rooms"
BOOKING_SHEET    = "Bookings"
CONFIG_SHEET     = "Config"

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


def get_client():
    return gspread.authorize(get_credentials())

def get_room_sheet():
    return get_client().open(SPREADSHEET_NAME).worksheet(ROOM_SHEET)

def get_booking_sheet():
    return get_client().open(SPREADSHEET_NAME).worksheet(BOOKING_SHEET)

def get_config_sheet():
    return get_client().open(SPREADSHEET_NAME).worksheet(CONFIG_SHEET)


def get_hotel_config():
    sheet = get_config_sheet()
    records = sheet.get_all_records()
    return {row["key"]: row["value"] for row in records}


def build_hotel_info(config):
    return f"""
Tên khách sạn: {config.get("hotel_name", "")}
Địa chỉ: {config.get("address", "")}
Hotline: {config.get("hotline", "")}

Giá phòng:
- Phòng đơn: {config.get("price_single", "")} / đêm
- Phòng đôi: {config.get("price_double", "")} / đêm
- Phòng Suite: {config.get("price_suite", "")} / đêm

Check-in: {config.get("checkin_time", "")}
Check-out: {config.get("checkout_time", "")}

Tiện ích:
{config.get("amenities", "")}
""".strip()


def save_booking(data):
    sheet = get_booking_sheet()
    sheet.append_row([
        data.get("checkin"),
        data.get("checkout"),
        data.get("room"),
        data.get("guests"),
        data.get("name"),
        data.get("phone"),
        data.get("note")
    ])
