import os, json, gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta

# ================= CONFIG (multi-room support) =================
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


# ================= MULTI-ROOM HELPERS =================
ROOM_TYPES = ["Phòng đơn", "Phòng đôi", "Suite"]


def get_available_counts(checkin, checkout):
    """
    Tra cứu số phòng trống TỐI THIỂU của từng loại trên toàn dải ngày
    [checkin, checkout). Trả về dict, ví dụ: {"Phòng đơn": 3, "Phòng đôi": 2, "Suite": 1}.
    Nếu lỗi/không có dữ liệu thì trả 0 cho loại đó.
    """
    try:
        start = datetime.strptime(normalize_date(checkin), DATE_FORMAT)
        end = datetime.strptime(normalize_date(checkout), DATE_FORMAT)
        if end <= start:
            return {t: 0 for t in ROOM_TYPES}

        mins = {t: None for t in ROOM_TYPES}
        cur = start
        while cur < end:
            date_str = cur.strftime(DATE_FORMAT)
            rooms = get_room_by_date(date_str) or {}
            for t in ROOM_TYPES:
                val = int(rooms.get(t, 0) or 0)
                if mins[t] is None or val < mins[t]:
                    mins[t] = val
            cur += timedelta(days=1)

        return {t: (mins[t] if mins[t] is not None else 0) for t in ROOM_TYPES}

    except Exception as e:
        print("❌ get_available_counts:", e)
        return {t: 0 for t in ROOM_TYPES}


def are_rooms_available(checkin, checkout, rooms_dict):
    """
    Kiểm tra mọi loại phòng trong rooms_dict (dạng {type: qty}) đều còn đủ
    trên toàn dải ngày. Bỏ qua loại có qty <= 0.
    """
    try:
        wanted = {normalize_room_type(k): int(v) for k, v in (rooms_dict or {}).items()
                  if int(v or 0) > 0}
        if not wanted:
            return False

        avail = get_available_counts(checkin, checkout)
        for room_type, qty in wanted.items():
            if avail.get(room_type, 0) < qty:
                return False
        return True

    except Exception as e:
        print("❌ are_rooms_available:", e)
        return False


def subtract_multi_rooms(checkin, checkout, rooms_dict):
    """
    Trừ số phòng đã đặt cho mỗi loại trên toàn dải ngày [checkin, checkout).
    rooms_dict dạng {"Phòng đơn": 1, "Phòng đôi": 2, ...}.
    """
    try:
        start = datetime.strptime(normalize_date(checkin), DATE_FORMAT)
        end = datetime.strptime(normalize_date(checkout), DATE_FORMAT)

        wanted = {normalize_room_type(k): int(v) for k, v in (rooms_dict or {}).items()
                  if int(v or 0) > 0}
        if not wanted:
            return

        cur = start
        while cur < end:
            date_str = cur.strftime(DATE_FORMAT)
            for room_type, qty in wanted.items():
                for _ in range(qty):
                    update_room_after_booking(date_str, room_type)
            cur += timedelta(days=1)

    except Exception as e:
        print("❌ subtract_multi_rooms:", e)

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

        # Hỗ trợ cả chuỗi đa phòng dạng "1 Phòng đơn, 1 Suite" lẫn 1 loại đơn
        # (vd "Single", "đôi"). Nếu chuỗi bắt đầu bằng số hoặc có dấu phẩy, coi là
        # composite và ghi nguyên xi; ngược lại mới chuẩn hoá về 1 trong 3 loại.
        room_raw = str(data.get("room", "")).strip()
        if room_raw and (room_raw[0].isdigit() or "," in room_raw):
            room_value = room_raw
        else:
            room_value = normalize_room_type(room_raw)

        sheet.append_row([
            normalize_date(data.get("checkin")),
            normalize_date(data.get("checkout")),
            room_value,
            data.get("name"),
            data.get("phone"),
            note
        ])

        print("✅ BOOKING SAVED")

    except Exception as e:
        print("❌ save booking:", e)
        raise
