import os, json, gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta

# ================= CONFIG =================
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

SPREADSHEET_NAME = "EDEN Bookings"
ROOM_SHEET = "Rooms"
BOOKING_SHEET = "Bookings"
CONFIG_SHEET = "Config"  # 👈 Sheet mới

DATE_FORMAT = "%d/%m/%Y"

# ================= AUTH =================
def get_credentials():
    if "GOOGLE_SERVICE_ACCOUNT_JSON" in os.environ:
        service_account_info = json.loads(
            os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
        )
        return Credentials.from_service_account_info(
            service_account_info, scopes=SCOPES
        )

    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(BASE_DIR, "service_account.json")
    return Credentials.from_service_account_file(path, scopes=SCOPES)


def get_client():
    return gspread.authorize(get_credentials())

# ================= SHEETS =================
def get_room_sheet():
    return get_client().open(SPREADSHEET_NAME).worksheet(ROOM_SHEET)


def get_booking_sheet():
    return get_client().open(SPREADSHEET_NAME).worksheet(BOOKING_SHEET)


def get_config_sheet():
    return get_client().open(SPREADSHEET_NAME).worksheet(CONFIG_SHEET)

# ================= HOTEL CONFIG =================
def get_hotel_config():
    """
    Đọc sheet Config và trả về dict {key: value}.
    Sheet Config có 2 cột: key | value
    """
    try:
        sheet = get_config_sheet()
        records = sheet.get_all_records()

        config = {}
        for row in records:
            row = clean_row(row)
            key = str(row.get("key", "")).strip()
            value = str(row.get("value", "")).strip()
            if key:
                config[key] = value

        return config

    except Exception as e:
        print("❌ get_hotel_config:", e)
        return {}


def build_hotel_info(config):
    """
    Xây dựng chuỗi HOTEL_INFO từ config dict để truyền vào AI prompt.
    """
    def g(key, default=""):
        return config.get(key, default)

    return f"""
Tên khách sạn: {g("hotel_name")}
Địa chỉ: {g("address")}
Hotline: {g("hotline")}

Giá phòng:
- Phòng đơn: {g("price_single")} / đêm
- Phòng đôi: {g("price_double")} / đêm
- Phòng Suite: {g("price_suite")} / đêm

Check-in: {g("checkin_time")}
Check-out: {g("checkout_time")}

Tiện ích:
{g("amenities")}

Chính sách đặt cọc:
{g("deposit_policy")}

Thanh toán:
{g("payment_policy")}

Chính sách hủy:
{g("cancel_policy")}

Lưu ý:
{g("note")}
""".strip()

# ================= UTILS =================
def normalize_date(date_str):
    try:
        date_str = str(date_str).strip()
        date_str = date_str.split("T")[0].split(" ")[0]

        for fmt in ["%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"]:
            try:
                d = datetime.strptime(date_str, fmt)
                return d.strftime(DATE_FORMAT)
            except:
                continue

        return date_str
    except:
        return str(date_str)


def normalize_room_type(room):
    room = str(room).lower()
    if "đơn" in room:
        return "Phòng đơn"
    if "đôi" in room:
        return "Phòng đôi"
    if "suite" in room:
        return "Suite"
    return room


def clean_row(row):
    return {str(k).strip(): v for k, v in row.items()}

# ================= GET ROOM =================
def get_room_by_date(date):
    try:
        sheet = get_room_sheet()
        records = sheet.get_all_records()
        input_date = normalize_date(date)

        for row in records:
            row = clean_row(row)
            sheet_date = normalize_date(row.get("date"))

            if sheet_date == input_date:
                return {
                    "Phòng đơn": int(row.get("Phòng đơn", 0)),
                    "Phòng đôi": int(row.get("Phòng đôi", 0)),
                    "Suite": int(row.get("Suite", 0))
                }

        return None

    except Exception as e:
        print("❌ get_room_by_date:", e)
        return None

# ================= CHECK AVAILABLE =================
def is_room_available(checkin, checkout, room_type):
    try:
        room_type = normalize_room_type(room_type)
        start = datetime.strptime(normalize_date(checkin), DATE_FORMAT)
        end = datetime.strptime(normalize_date(checkout), DATE_FORMAT)

        while start < end:
            date_str = start.strftime(DATE_FORMAT)
            rooms = get_room_by_date(date_str)

            if not rooms or rooms.get(room_type, 0) <= 0:
                return False

            start += timedelta(days=1)

        return True

    except Exception as e:
        print("❌ check availability:", e)
        return False

# ================= UPDATE ROOM =================
def update_room_after_booking(date, room_type):
    try:
        sheet = get_room_sheet()
        records = sheet.get_all_records()

        date = normalize_date(date)
        room_type = normalize_room_type(room_type)

        for i, row in enumerate(records, start=2):
            row = clean_row(row)
            sheet_date = normalize_date(row.get("date"))

            if sheet_date == date:
                current = int(row.get(room_type, 0))
                new_value = max(current - 1, 0)
                col_index = list(row.keys()).index(room_type) + 1
                sheet.update_cell(i, col_index, new_value)
                print(f"📉 {room_type} {date}: {current} → {new_value}")
                return

    except Exception as e:
        print("❌ update_room:", e)

# ================= TRỪ NHIỀU NGÀY =================
def subtract_rooms(checkin, checkout, room_type):
    room_type = normalize_room_type(room_type)
    start = datetime.strptime(normalize_date(checkin), DATE_FORMAT)
    end = datetime.strptime(normalize_date(checkout), DATE_FORMAT)

    while start < end:
        update_room_after_booking(start.strftime(DATE_FORMAT), room_type)
        start += timedelta(days=1)

# ================= SAVE BOOKING =================
def save_booking(data):
    try:
        sheet = get_booking_sheet()

        note = data.get("note")
        if not note or note == "skip":
            note = ""

        sheet.append_row([
            normalize_date(data.get("checkin")),
            normalize_date(data.get("checkout")),
            normalize_room_type(data.get("room")),
            data.get("name"),
            data.get("phone"),
            note
        ])

        print("✅ BOOKING SAVED")

    except Exception as e:
        print("❌ save booking:", e)
        raise
