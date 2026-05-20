from flask import Flask, render_template, request, jsonify, session
import os
import re
from datetime import datetime
import google.generativeai as genai

# ================== IMPORT GOOGLE SHEET HELPERS (with fallbacks) ==================
# Render có thể đang chạy bản google_sheet.py cũ thiếu một vài hàm.
# Import từng hàm riêng và có fallback cục bộ để tránh ImportError làm sập app.
try:
    from google_sheet import save_booking
except Exception as _e:
    print("WARN: cannot import save_booking:", _e)
    def save_booking(*a, **k):
        raise RuntimeError("save_booking is not available on the server")

try:
    from google_sheet import is_room_available
except Exception as _e:
    print("WARN: cannot import is_room_available:", _e)
    def is_room_available(*a, **k):
        return True  # tạm cho phép đặt nếu không kiểm tra được

try:
    from google_sheet import subtract_rooms
except Exception as _e:
    print("WARN: cannot import subtract_rooms:", _e)
    def subtract_rooms(*a, **k):
        pass

try:
    from google_sheet import get_available_counts
except Exception as _e:
    print("WARN: cannot import get_available_counts:", _e)
    def get_available_counts(*a, **k):
        # Fallback: chấp nhận đặt nếu không tra được
        return {"Phòng đơn": 99, "Phòng đôi": 99, "Suite": 99}

try:
    from google_sheet import are_rooms_available
except Exception as _e:
    print("WARN: cannot import are_rooms_available:", _e)
    def are_rooms_available(checkin, checkout, rooms_dict):
        # Fallback: dựa vào is_room_available cho từng loại có qty > 0
        try:
            for t, q in (rooms_dict or {}).items():
                if int(q or 0) > 0 and not is_room_available(checkin, checkout, t):
                    return False
            return True
        except Exception:
            return True

try:
    from google_sheet import subtract_multi_rooms
except Exception as _e:
    print("WARN: cannot import subtract_multi_rooms:", _e)
    def subtract_multi_rooms(checkin, checkout, rooms_dict):
        # Fallback: gọi subtract_rooms từng loại, qty lần
        for t, q in (rooms_dict or {}).items():
            for _ in range(int(q or 0)):
                try:
                    subtract_rooms(checkin, checkout, t)
                except Exception:
                    pass

try:
    from google_sheet import normalize_date
except Exception as _e:
    print("WARN: cannot import normalize_date, using local fallback:", _e)
    def normalize_date(date_str):
        try:
            date_str = str(date_str).strip().split("T")[0].split(" ")[0]
            for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
                try:
                    return datetime.strptime(date_str, fmt).strftime("%d/%m/%Y")
                except Exception:
                    continue
            return date_str
        except Exception:
            return str(date_str)

try:
    from google_sheet import get_hotel_config
except Exception as _e:
    print("WARN: cannot import get_hotel_config:", _e)
    def get_hotel_config():
        return {}

try:
    from google_sheet import build_hotel_info as _build_hotel_info_vi
except Exception as _e:
    print("WARN: cannot import build_hotel_info, using local fallback:", _e)
    def _build_hotel_info_vi(config):
        def g(k, d=""): return str(config.get(k, d) or "").strip()
        def s(title, value):
            v = (value or "").strip()
            return f"\n{title}:\n{v}\n" if v else ""
        parts = [
            f"Tên khách sạn: {g('hotel_name')}",
            f"Địa chỉ: {g('address')}",
            f"Hotline: {g('hotline')}",
            "",
            "Giá phòng:",
            f"- Phòng đơn: {g('price_single')} / đêm",
            f"- Phòng đôi: {g('price_double')} / đêm",
            f"- Phòng Suite: {g('price_suite')} / đêm",
            "",
            f"Check-in: {g('checkin_time')}",
            f"Check-out: {g('checkout_time')}",
        ]
        body = "\n".join(parts)
        body += s("Tiện ích", g("amenities"))
        body += s("Phí dịch vụ tiện ích", g("amenity_fees"))
        body += s("Khu vui chơi & chụp ảnh gần khách sạn", g("nearby_attractions"))
        body += s("Sự kiện sắp tới ở Phú Quốc", g("upcoming_events"))
        body += s("Sự kiện trong khách sạn (lịch hát, hoạt động)", g("hotel_events"))
        body += s("Chính sách đặt cọc", g("deposit_policy"))
        body += s("Thanh toán", g("payment_policy"))
        body += s("Chính sách hủy", g("cancel_policy"))
        body += s("Lưu ý", g("note"))
        return body.strip()

app = Flask(__name__)
app.secret_key = "eden-secret-key"

# ================== GEMINI ==================
def ask_gemini(prompt):
    genai.configure(api_key=os.environ.get("GOOGLE_API_KEY"))
    model = genai.GenerativeModel("gemini-2.5-flash")
    response = model.generate_content(prompt)
    return response.text.strip()

# ================== LANGUAGE DETECTION ==================
VI_DIACRITICS = re.compile(
    r"[ăâđêôơưĂÂĐÊÔƠƯàáạảãằắặẳẵầấậẩẫèéẹẻẽềếệểễìíịỉĩòóọỏõồốộổỗờớợởỡùúụủũừứựửữỳýỵỷỹ]",
    re.IGNORECASE
)
VI_KEYWORDS = {
    "phong", "dat", "gia", "khach", "san", "tien", "ich", "huy",
    "thanh", "toan", "nhan", "tra", "dem", "nguoi", "ngay", "co",
    "khong", "duoc", "minh", "toi", "ban", "vui", "long"
}
EN_KEYWORDS = {
    "the", "a", "an", "is", "are", "you", "i", "we", "and", "or",
    "book", "room", "price", "night", "hotel", "check", "in", "out",
    "please", "thank", "thanks", "want", "need", "would", "like",
    "how", "what", "when", "where", "yes", "no", "available", "have",
    "single", "double", "suite", "deposit", "cancel", "confirm",
    "reserve", "reservation", "guest", "stay", "rate", "amenity",
    "amenities", "pool", "spa", "wifi", "breakfast"
}

def detect_lang(text, default="vi"):
    if not text:
        return default
    if VI_DIACRITICS.search(text):
        return "vi"
    words = re.findall(r"[a-zA-Z]+", text.lower())
    if not words:
        return default
    vi_hits = sum(1 for w in words if w in VI_KEYWORDS)
    en_hits = sum(1 for w in words if w in EN_KEYWORDS)
    if en_hits > vi_hits:
        return "en"
    if vi_hits > en_hits:
        return "vi"
    return default

def resolve_lang(client_lang, message):
    # Đảm bảo client_lang hợp lệ
    client_lang = client_lang if client_lang in ("vi", "en") else "vi"
    
    # Nếu tin nhắn quá ngắn (dưới 4 ký tự hoặc chỉ là 1-2 từ đơn), 
    # giữ nguyên ngôn ngữ hiện tại của client/session
    words = message.lower().split()
    if len(message.strip()) < 4 or len(words) <= 2:
        return client_lang

    # Chỉ chuyển sang tiếng Việt nếu có dấu đặc trưng và tin nhắn đủ dài
    if VI_DIACRITICS.search(message):
        return "vi"

    # Chỉ chuyển sang tiếng Anh nếu có từ khóa đặc trưng rõ rệt
    en_hits = sum(1 for w in words if w in EN_KEYWORDS)
    if en_hits >= 2:
        return "en"

    return client_lang

# ================== I18N STRINGS ==================
T = {
    "vi": {
        "empty": "Quý khách vui lòng nhập nội dung 😊",
        "ask_checkin": "Xin hãy cho biết ngày nhận phòng! (DD/MM/YYYY)",
        "ask_checkout": "Xin hãy cho biết ngày trả phòng! (DD/MM/YYYY)",
        "ask_rooms_qty": "Quý khách muốn đặt bao nhiêu phòng mỗi loại? (Bấm − / + để chọn rồi nhấn Xong)",
        "ask_name": "Hãy cho biết tên của quý khách",
        "ask_phone": "Số điện thoại liên hệ",
        "ask_note": "Quý khách có ghi chú gì thêm không? (gõ nội dung hoặc bấm Bỏ qua)",
        "btn_single": "🛏 Phòng đơn",
        "btn_double": "🛏🛏 Phòng đôi",
        "btn_suite": "👑 Suite",
        "btn_done": "✅ Xong",
        "btn_skip": "↪️ Bỏ qua",
        "btn_confirm": "✅ Xác nhận đặt phòng",
        "btn_cancel": "❌ Hủy",
        "available_left": "còn {n}",
        "sold_out": "hết phòng",
        "summary_title": "📋 Xác nhận đặt phòng:",
        "s_checkin": "Check-in",
        "s_checkout": "Check-out",
        "s_nights": "đêm",
        "s_room": "Phòng",
        "s_name": "Tên",
        "s_phone": "SĐT",
        "s_note": "Ghi chú",
        "s_total": "Tổng tiền",
        "s_deposit": "Đặt cọc 30%",
        "no_room": "❌ Phòng đã hết trong khoảng thời gian này. Vui lòng chọn ngày khác.",
        "no_room_selected": "Quý khách vui lòng chọn ít nhất 1 phòng.",
        "book_error": "❌ Có lỗi xảy ra khi đặt phòng. Vui lòng thử lại.",
        "book_success": "🎉 Đặt phòng thành công!\nKhách sạn sẽ liên hệ xác nhận và hướng dẫn đặt cọc sớm nhất.\nCảm ơn quý khách! 🙏",
        "book_cancel": "Đã hủy đặt phòng. Quý khách cần hỗ trợ gì thêm không? 😊",
        "system_busy": "Hệ thống đang bận, vui lòng thử lại sau.",
        "confirm_prompt": "Quý khách vui lòng xác nhận hoặc hủy đặt phòng.",
        "invalid_date_format": "Ngày không hợp lệ. Vui lòng nhập theo định dạng DD/MM/YYYY.",
        "invalid_dates": "Ngày trả phòng phải sau ngày nhận phòng. Vui lòng nhập lại ngày trả phòng.",
        "gemini_role": "Bạn là lễ tân khách sạn EDEN Regent Phú Quốc.\nTrả lời ngắn gọn, lịch sự, thân thiện bằng TIẾNG VIỆT.\nKhông dùng markdown.",
    },
    "en": {
        "empty": "Please type a message 😊",
        "ask_checkin": "Check-in date (DD/MM/YYYY)",
        "ask_checkout": "Check-out date (DD/MM/YYYY)",
        "ask_rooms_qty": "How many rooms of each type would you like? (Use − / + then press Done)",
        "ask_name": "Your name, please?",
        "ask_phone": "Contact phone number?",
        "ask_note": "Any extra notes? (Type a note or press Skip)",
        "btn_single": "🛏 Single",
        "btn_double": "🛏🛏 Double",
        "btn_suite": "👑 Suite",
        "btn_done": "✅ Done",
        "btn_skip": "↪️ Skip",
        "btn_confirm": "✅ Confirm booking",
        "btn_cancel": "❌ Cancel",
        "available_left": "{n} left",
        "sold_out": "sold out",
        "summary_title": "📋 Booking confirmation:",
        "s_checkin": "Check-in",
        "s_checkout": "Check-out",
        "s_nights": "nights",
        "s_room": "Room",
        "s_name": "Name",
        "s_phone": "Phone",
        "s_note": "Note",
        "s_total": "Total",
        "s_deposit": "30% deposit",
        "no_room": "❌ No rooms available for those dates. Please choose other dates.",
        "no_room_selected": "Please select at least one room.",
        "book_error": "❌ Something went wrong while booking. Please try again.",
        "book_success": "🎉 Booking successful!\nThe hotel will contact you shortly to confirm and guide the deposit.\nThank you! 🙏",
        "book_cancel": "Booking cancelled. Anything else I can help with? 😊",
        "system_busy": "The system is busy, please try again later.",
        "confirm_prompt": "Please confirm or cancel your booking.",
        "invalid_date_format": "Invalid date. Please enter in DD/MM/YYYY format.",
        "invalid_dates": "Check-out must be after check-in. Please enter a valid check-out date.",
        "gemini_role": "You are the receptionist of EDEN Regent Phu Quoc hotel.\nReply briefly, politely and warmly in ENGLISH.\nDo not use markdown.",
    }
}

def tr(lang, key):
    return T.get(lang, T["vi"]).get(key, T["vi"].get(key, key))

# ================== DATA (lấy động từ Sheet "Config") ==================
def build_hotel_info_en(config):
    """Build the English hotel info string from the Config dict.

    Reads English-specific keys (suffix `_en`) first; falls back to the
    Vietnamese key if the English one is missing or empty. This lets the
    user keep one Sheet with two parallel language columns.
    """
    def g(key_en, key_vi=None, default=""):
        v = str(config.get(key_en, "")).strip()
        if v:
            return v
        if key_vi:
            v = str(config.get(key_vi, "")).strip()
            if v:
                return v
        return default

    def s(title, value):
        v = (value or "").strip()
        return f"\n{title}:\n{v}\n" if v else ""

    parts = [
        f"Hotel name: {g('hotel_name_en', 'hotel_name')}",
        f"Address: {g('address_en', 'address')}",
        f"Hotline: {g('hotline')}",
        "",
        "Room rates:",
        f"- Single room: {g('price_single')} / night",
        f"- Double room: {g('price_double')} / night",
        f"- Suite: {g('price_suite')} / night",
        "",
        f"Check-in: {g('checkin_time')}",
        f"Check-out: {g('checkout_time')}",
    ]
    body = "\n".join(parts)
    body += s("Amenities", g("amenities_en", "amenities"))
    body += s("Amenity service fees", g("amenity_fees_en", "amenity_fees"))
    body += s("Nearby attractions & photo spots", g("nearby_attractions_en", "nearby_attractions"))
    body += s("Upcoming events in Phu Quoc", g("upcoming_events_en", "upcoming_events"))
    body += s("Hotel events (live music, activities)", g("hotel_events_en", "hotel_events"))
    body += s("Deposit policy", g("deposit_policy_en", "deposit_policy"))
    body += s("Payment", g("payment_policy_en", "payment_policy"))
    body += s("Cancellation policy", g("cancel_policy_en", "cancel_policy"))
    body += s("Note", g("note_en", "note"))
    return body.strip()


def _expand_newlines(config):
    """Convert literal '\\n' (and '\\r\\n') in cell values to real newlines.
    Lets the user type "\\n" inside a Google Sheet cell instead of Alt+Enter."""
    out = {}
    for k, v in (config or {}).items():
        if isinstance(v, str):
            out[k] = v.replace("\\r\\n", "\n").replace("\\n", "\n")
        else:
            out[k] = v
    return out


def _load_config():
    """Get the Config sheet as a dict, with \\n expanded to real newlines."""
    try:
        raw = get_hotel_config() or {}
    except Exception as e:
        print("WARN: get_hotel_config failed:", e)
        raw = {}
    return _expand_newlines(raw)


def get_hotel_info(lang):
    """Load the Config sheet on demand and build the info string in the requested language."""
    config = _load_config()
    if lang == "en":
        return build_hotel_info_en(config)
    return _build_hotel_info_vi(config)


def parse_price(value):
    """Parse a price string like '800.000đ' or '800,000 VND' to an integer."""
    if not value:
        return 0
    digits = re.sub(r"[^0-9]", "", str(value))
    return int(digits) if digits else 0


def get_room_prices():
    """Return room prices from the Config sheet, falling back to defaults."""
    try:
        config = get_hotel_config() or {}
    except Exception:
        config = {}
    return {
        "Phòng đơn": parse_price(config.get("price_single")) ,
        "Phòng đôi": parse_price(config.get("price_double")) ,
        "Suite":     parse_price(config.get("price_suite")),
    }

def normalize_room(text):
    t_low = text.lower().strip()
    # Kiểm tra Suite
    if any(k in t_low for k in ["suite", "👑"]):
        return "Suite"
    # Kiểm tra Double/Phòng đôi
    if any(k in t_low for k in ["đôi", "doi", "double", "🛏🛏"]):
        return "Phòng đôi"
    # Kiểm tra Single/Phòng đơn
    if any(k in t_low for k in ["đơn", "don", "single", "🛏"]):
        return "Phòng đơn"
    return text

ROOM_DISPLAY = {
    "vi": {"Phòng đơn": "Phòng đơn", "Phòng đôi": "Phòng đôi", "Suite": "Suite"},
    "en": {"Phòng đơn": "Single room", "Phòng đôi": "Double room", "Suite": "Suite"},
}

# Thứ tự cố định để truyền giữa frontend ↔ backend
ROOM_ORDER = ["Phòng đơn", "Phòng đôi", "Suite"]

ROOMS_PICK_PREFIX = "__rooms_pick__:"


def parse_rooms_pick(msg):
    """
    Parse chuỗi do frontend gửi sau khi khách bấm "Xong":
    "__rooms_pick__:1,2,0" → {"Phòng đơn": 1, "Phòng đôi": 2, "Suite": 0}
    Trả về None nếu không đúng format.
    """
    if not msg or not msg.startswith(ROOMS_PICK_PREFIX):
        return None
    try:
        raw = msg[len(ROOMS_PICK_PREFIX):]
        parts = [p.strip() for p in raw.split(",")]
        if len(parts) != len(ROOM_ORDER):
            return None
        qty = [max(0, int(p)) for p in parts]
        return {ROOM_ORDER[i]: qty[i] for i in range(len(ROOM_ORDER))}
    except Exception:
        return None


def format_rooms_summary(rooms, lang="vi"):
    """Chuyển dict rooms thành chuỗi hiển thị: '1 Phòng đơn, 2 Phòng đôi'."""
    parts = []
    display_map = ROOM_DISPLAY.get(lang, ROOM_DISPLAY["vi"])
    for room_type in ROOM_ORDER:
        qty = int((rooms or {}).get(room_type, 0) or 0)
        if qty > 0:
            parts.append(f"{qty} {display_map.get(room_type, room_type)}")
    return ", ".join(parts)


def total_rooms_count(rooms):
    return sum(int((rooms or {}).get(t, 0) or 0) for t in ROOM_ORDER)


def calc_rooms_total(rooms, nights):
    """Tổng tiền = Σ qty × giá × số đêm."""
    prices = get_room_prices()
    total = 0
    for room_type in ROOM_ORDER:
        qty = int((rooms or {}).get(room_type, 0) or 0)
        if qty > 0:
            total += qty * prices.get(room_type, 0) * nights
    return total


# ================== BOOKING INTENT DETECTION ==================
# Mục tiêu: phân biệt "muốn đặt phòng" (intent) với "đặt phòng có khuyến mãi không?" (Q&A).
# So với cách cũ (substring `in`), logic này:
#   1) Khớp chính xác giá trị nút  → trigger ngay
#   2) Có pattern intent mạnh (động từ + đặt/book) → trigger
#   3) Có từ "đặt/book" + dấu hiệu câu hỏi → KHÔNG trigger (đẩy qua Gemini)
#   4) Câu rất ngắn (≤4 từ) có từ đặt phòng & không phải hỏi → trigger
BOOKING_BUTTON_VALUES = {
    "đặt phòng", "dat phong", "booking", "book", "book a room",
    "book room", "reserve", "reservation", "make a booking",
    "make a reservation", "đặt", "i want to book", "i'd like to book",
}

BOOKING_INTENT_PATTERNS = [
    # VI: "muốn/mún/cần/định/tính/tôi/tui/mình/em/anh + (vài từ) + đặt phòng/book/reserve"
    re.compile(
        r"(muốn|mu[oôố]n|m[uú]n|cần|c[aâầ]n|định|đjnh|tính|t[uô]i|mình|mìn|em\b|anh\b|chị\b|cho)"
        r"\s+\w{0,16}\s*"
        r"(đặt\s*(phòng|chỗ|ph[oòóọ]ng)?|đ[aă]t\s*phong|book\w*|reserve\w*)",
        re.IGNORECASE
    ),
    # VI: "đặt giúp/cho/hộ/dùm"
    re.compile(r"\bđặt\s+(giúp|cho|hộ|dùm|du?m|hô)\b", re.IGNORECASE),
    # VI: "đặt 1 phòng / đặt 2 phòng / đặt phòng 2 đêm"
    re.compile(r"\bđặt\s+\d+\s*(phòng|ph[oò]ng)?", re.IGNORECASE),
    # VI: "đặt phòng đi/giúp/luôn/nhé/nha/với"
    re.compile(r"\bđặt\s*(phòng|ph[oò]ng)?\s+(đi|giúp|luôn|nhé|nha|với|dy|đy)\b", re.IGNORECASE),
    # EN: "i/we want|need|would like|'d like|wanna ... book|reserve|make a (booking|reservation)"
    re.compile(
        r"\b(i|we)\s+(want|need|would\s+like|'?d\s+like|wanna|gonna|plan\s+to|am\s+going\s+to)\s+to\s+"
        r"(book|reserve|make\s+a\s+(booking|reservation))",
        re.IGNORECASE
    ),
    # "book a room", "book me a single room", "reserve two nights"...
    re.compile(r"\b(book|reserve)\s+\w+(\s+\w+){0,4}\s+(room|rooms|night|nights|suite|stay)\b", re.IGNORECASE),
    re.compile(r"\bmake\s+(a|the)\s+(booking|reservation)", re.IGNORECASE),
    re.compile(r"\blet'?s\s+book\b", re.IGNORECASE),
    re.compile(r"\b(can|could|may)\s+(i|we)\s+book\s+(a|the|me|us)?\s*\w*\s*(room|night|suite)?", re.IGNORECASE),
]

# Dấu hiệu câu hỏi — nếu xuất hiện cùng từ booking, coi là Q&A info
QUESTION_MARKERS = (
    "?",
    # VI question words
    "thế nào", "the nao", "ra sao", "như nào", "nhu nao", "như thế nào",
    "làm sao", "lam sao", "làm thế nào", "có thể", "co the",
    "được không", "duoc khong", "có được", "co duoc", "có ko", "co ko",
    "đc không", "đc ko", "dc khong", "dc ko", "đk ko", "đk không",
    "được ko", "duoc ko",
    "là gì", "la gi", "là sao", "la sao", "bao nhiêu", "bao nhieu",
    "chính sách", "chinh sach", "quy trình", "quy trinh",
    "hướng dẫn", "huong dan", "có nhận", "co nhan",
    "có cho", "co cho", "tại sao", "tai sao", "khi nào", "khi nao",
    "ở đâu", "o dau",
    # EN question words
    "what ", "what's", "what is", "how ", "how's", "how to", "how do",
    "when ", "where ", "why ", "which ", "who ",
    "is it", "are you", "do you", "can i have info", "is there",
    "are there", "do i need", "should i", "would you mind",
    "tell me about", "explain",
)

# Pattern phủ định — nếu match thì câu KHÔNG phải intent đặt phòng,
# kể cả khi có "muốn đặt phòng" trong câu (vd "ko muốn đặt phòng").
NEGATION_PATTERNS = [
    # VI: "ko/không/đừng/chưa/chẳng + (vài từ) + muốn/cần/định + (vài từ) + đặt/book"
    re.compile(
        r"\b(không|khong|kh[ôố]ng|ko|đừng|dung|chưa|chua|chẳng|chang|chả\b|cha\b|hổng|hong)\s+"
        r"\w{0,12}\s*"
        r"(mu[oôố]n|m[uú]n|cần|c[âầ]n|định|đjnh|tính)\s+"
        r"\w{0,12}\s*"
        r"(đặt|d[aă]t\s*phong|book\w*|reserve\w*)",
        re.IGNORECASE
    ),
    # VI: "đừng/chưa + (0-5 từ) + đặt"
    re.compile(
        r"\b(đừng|chưa|chẳng|hổng|chả)\s+\w{0,16}\s*(đặt\s*(phòng|chỗ)?|book\w*|reserve\w*)",
        re.IGNORECASE
    ),
    # VI: "ko đặt phòng" / "không đặt phòng" trực tiếp
    re.compile(
        r"\b(không|khong|ko|hổng|chẳng)\s+\w{0,3}\s*(đặt\s*(phòng|chỗ)|book\w*|reserve\w*)",
        re.IGNORECASE
    ),
    # EN: "don't/do not/won't + (vài từ) + want|need|like|going + to + book/reserve"
    re.compile(
        r"\b(don'?t|do\s+not|won'?t|will\s+not|never|no\s+need\s+to)\s+\w{0,8}\s*"
        r"(want|need|like|going|plan|intend)\s+to\s+(book|reserve|make)",
        re.IGNORECASE
    ),
    # EN: "not booking", "not interested in booking"
    re.compile(
        r"\bnot\s+\w{0,8}\s*(book\w*|reserve\w*|reservation)\b",
        re.IGNORECASE
    ),
]
# Một vài từ booking cơ bản để check kết hợp với question marker
BOOKING_WORDS_VI = ("đặt phòng", "dat phong", "đặt chỗ")
BOOKING_WORDS_EN = ("book", "booking", "reserve", "reservation")


def is_booking_intent(msg_lower):
    """Phát hiện ý định đặt phòng. Logic 5 tầng (kiểm tra theo thứ tự):
       1) Exact button match              → trigger
       2) Match pattern PHỦ ĐỊNH          → KHÔNG trigger ("ko muốn đặt phòng")
       3) Có booking word + dấu hiệu hỏi  → KHÔNG trigger (Q&A)
       4) Match pattern intent mạnh       → trigger
       5) Câu ≤4 từ + có booking word     → trigger ("đặt phòng nhé")
    """
    msg = (msg_lower or "").strip()
    if not msg:
        return False

    # 1) Exact button match
    if msg in BOOKING_BUTTON_VALUES:
        return True

    # 2) Phủ định → reject ngay
    for pat in NEGATION_PATTERNS:
        if pat.search(msg):
            return False

    has_vi = any(w in msg for w in BOOKING_WORDS_VI)
    has_en = bool(re.search(r"\b(book|booking|reserve|reservation)\b", msg))
    has_booking_word = has_vi or has_en

    # 3) Câu hỏi đi kèm từ booking → Q&A
    if has_booking_word:
        for q in QUESTION_MARKERS:
            if q in msg:
                return False

    # 4) Pattern intent
    for pat in BOOKING_INTENT_PATTERNS:
        if pat.search(msg):
            return True

    # 5) Câu ngắn + có từ booking → trigger
    if has_booking_word:
        word_count = len(re.findall(r"\w+", msg))
        if word_count <= 4:
            return True

    return False


# Từ khoá thoát flow giữa chừng. Khi khách lỡ vào flow đặt phòng nhưng không muốn nữa,
# gõ một trong các cụm này sẽ huỷ flow và quay lại chế độ chat thường.
ABORT_TOKENS = {
    "hủy", "huỷ", "huy", "thôi", "thoi", "thoát", "thoat",
    "không", "khong", "ko", "kh", "không nữa", "khong nua", "ko nữa", "ko nua",
    "dừng", "dung lai", "dừng lại",
    "cancel", "exit", "quit", "stop", "nevermind", "never mind", "no thanks",
}


def is_abort(msg_lower):
    """Khách gõ chính xác từ thoát (tránh false positive với câu chứa 'không' chung chung)."""
    m = (msg_lower or "").strip().rstrip("!.?")
    return m in ABORT_TOKENS


def build_rooms_picker(lang, avail):
    """Tạo payload quantity_picker cho frontend dựa trên số phòng còn trống."""
    label_map = {
        "Phòng đơn": tr(lang, "btn_single"),
        "Phòng đôi": tr(lang, "btn_double"),
        "Suite":     tr(lang, "btn_suite"),
    }
    items = []
    for room_type in ROOM_ORDER:
        n = int((avail or {}).get(room_type, 0) or 0)
        if n > 0:
            avail_text = tr(lang, "available_left").format(n=n)
        else:
            avail_text = tr(lang, "sold_out")
        items.append({
            "key": room_type,
            "label": label_map.get(room_type, room_type),
            "available": n,
            "max": n,
            "available_text": avail_text,
        })
    return {
        "items": items,
        "submit_label": tr(lang, "btn_done"),
        "submit_prefix": ROOMS_PICK_PREFIX,
    }

# ================== ROUTES ==================
@app.route("/")
def home():
    session.clear()
    return render_template("index.html")

@app.route("/reset", methods=["POST"])
def reset_session():
    session.clear()
    return jsonify({"ok": True})

@app.route("/chat", methods=["POST"])
def chat():
    payload = request.json or {}
    msg = (payload.get("message") or "").strip()
    client_lang = payload.get("lang", "vi")
    msg_lower = msg.lower()

    lang = resolve_lang(client_lang, msg)
    session["lang"] = lang

    if not msg:
        return jsonify({"reply": tr(lang, "empty"), "lang": lang})

    # ================== FLOW ==================
    if "step" in session:
        # Cho phép thoát flow giữa chừng (vd khách lỡ trigger nhầm)
        if is_abort(msg_lower):
            session.clear()
            return jsonify({"reply": tr(lang, "book_cancel"), "lang": lang})

        step = session["step"]
        b = session.get("booking", {})

        if step == "checkin":
            checkin_str = normalize_date(msg)
            try:
                datetime.strptime(checkin_str, "%d/%m/%Y")
            except ValueError:
                return jsonify({"reply": tr(lang, "invalid_date_format") + " " + tr(lang, "ask_checkin"), "lang": lang})
            b["checkin"] = checkin_str
            session["booking"] = b
            session["step"] = "checkout"
            return jsonify({"reply": tr(lang, "ask_checkout"), "lang": lang})

        if step == "checkout":
            checkout_str = normalize_date(msg)
            try:
                checkin_dt = datetime.strptime(b["checkin"], "%d/%m/%Y")
                checkout_dt = datetime.strptime(checkout_str, "%d/%m/%Y")
                if checkout_dt <= checkin_dt:
                    return jsonify({"reply": tr(lang, "invalid_dates"), "lang": lang})
            except ValueError:
                return jsonify({"reply": tr(lang, "invalid_date_format") + " " + tr(lang, "ask_checkout"), "lang": lang})
            b["checkout"] = checkout_str
            session["booking"] = b
            session["step"] = "rooms"

            # Lấy số phòng trống tối thiểu trên dải ngày để hiển thị
            try:
                avail = get_available_counts(b["checkin"], b["checkout"]) or {}
            except Exception as _e:
                print("WARN: get_available_counts:", _e)
                avail = {t: 0 for t in ROOM_ORDER}

            return jsonify({
                "reply": tr(lang, "ask_rooms_qty"),
                "lang": lang,
                "quantity_picker": build_rooms_picker(lang, avail),
            })

        if step == "rooms":
            rooms = parse_rooms_pick(msg)
            if rooms is None:
                # Khách gõ tay thay vì bấm nút — hiện lại picker
                try:
                    avail = get_available_counts(b.get("checkin"), b.get("checkout")) or {}
                except Exception:
                    avail = {t: 0 for t in ROOM_ORDER}
                return jsonify({
                    "reply": tr(lang, "ask_rooms_qty"),
                    "lang": lang,
                    "quantity_picker": build_rooms_picker(lang, avail),
                })

            if total_rooms_count(rooms) <= 0:
                try:
                    avail = get_available_counts(b.get("checkin"), b.get("checkout")) or {}
                except Exception:
                    avail = {t: 0 for t in ROOM_ORDER}
                return jsonify({
                    "reply": tr(lang, "no_room_selected"),
                    "lang": lang,
                    "quantity_picker": build_rooms_picker(lang, avail),
                })

            b["rooms"] = rooms
            session["booking"] = b
            session["step"] = "name"
            return jsonify({"reply": tr(lang, "ask_name"), "lang": lang})

        if step == "name":
            b["name"] = msg
            session["booking"] = b
            session["step"] = "phone"
            return jsonify({"reply": tr(lang, "ask_phone"), "lang": lang})

        if step == "phone":
            b["phone"] = msg
            session["booking"] = b
            session["step"] = "note"
            return jsonify({
                "reply": tr(lang, "ask_note"),
                "lang": lang,
                "buttons": [
                    {"label": tr(lang, "btn_skip"), "value": "skip"}
                ]
            })

        if step == "note":
            note = "" if msg_lower in ("skip", "bỏ qua", "bo qua") else msg
            b["note"] = note
            session["booking"] = b
            session["step"] = "confirm"

            try:
                checkin_dt = datetime.strptime(b["checkin"], "%d/%m/%Y")
                checkout_dt = datetime.strptime(b["checkout"], "%d/%m/%Y")
                nights = (checkout_dt - checkin_dt).days
                total = calc_rooms_total(b.get("rooms", {}), nights)
                if lang == "en":
                    total_str = f"{total:,.0f} VND"
                    deposit_str = f"{int(total * 0.3):,.0f} VND"
                else:
                    total_str = f"{total:,.0f}đ"
                    deposit_str = f"{int(total * 0.3):,.0f}đ"
                nights_str = f"{nights} {tr(lang, 's_nights')}"
            except Exception:
                nights_str = "N/A"
                total_str = "N/A"
                deposit_str = "N/A"

            rooms_display = format_rooms_summary(b.get("rooms", {}), lang)

            lines = [
                f"{tr(lang, 'summary_title')}",
                f"• {tr(lang, 's_checkin')}: {b['checkin']}",
                f"• {tr(lang, 's_checkout')}: {b['checkout']} ({nights_str})",
                f"• {tr(lang, 's_room')}: {rooms_display}",
                f"• {tr(lang, 's_name')}: {b['name']}",
                f"• {tr(lang, 's_phone')}: {b['phone']}",
            ]
            if note:
                lines.append(f"• {tr(lang, 's_note')}: {note}")
            lines.append(f"• {tr(lang, 's_total')}: {total_str}")
            lines.append(f"• {tr(lang, 's_deposit')}: {deposit_str}")
            summary = "\n".join(lines)

            return jsonify({
                "reply": summary,
                "lang": lang,
                "buttons": [
                    {"label": tr(lang, "btn_confirm"), "value": "confirm"},
                    {"label": tr(lang, "btn_cancel"),  "value": "cancel"}
                ]
            })

        if step == "confirm":
            if msg_lower == "confirm":
                try:
                    rooms = b.get("rooms", {})
                    if not are_rooms_available(b["checkin"], b["checkout"], rooms):
                        session.clear()
                        return jsonify({"reply": tr(lang, "no_room"), "lang": lang})

                    # Lưu chuỗi "1 Phòng đơn, 2 Phòng đôi" vào ô Loại phòng (luôn VI để
                    # đồng bộ dữ liệu trên sheet).
                    save_payload = dict(b)
                    save_payload["room"] = format_rooms_summary(rooms, "vi")
                    save_payload["note"] = b.get("note", "")
                    save_booking(save_payload)
                    subtract_multi_rooms(b["checkin"], b["checkout"], rooms)

                except Exception as e:
                    print("ERROR:", e)
                    return jsonify({"reply": tr(lang, "book_error"), "lang": lang})

                session.clear()
                return jsonify({"reply": tr(lang, "book_success"), "lang": lang})

            if msg_lower == "cancel":
                session.clear()
                return jsonify({"reply": tr(lang, "book_cancel"), "lang": lang})

            # Fallback: any other message in confirm step → re-show buttons
            return jsonify({
                "reply": tr(lang, "confirm_prompt"),
                "lang": lang,
                "buttons": [
                    {"label": tr(lang, "btn_confirm"), "value": "confirm"},
                    {"label": tr(lang, "btn_cancel"),  "value": "cancel"}
                ]
            })

    # ================== START BOOKING ==================
    if is_booking_intent(msg_lower):
        session.clear()
        session["step"] = "checkin"
        session["booking"] = {}
        session["lang"] = lang
        return jsonify({"reply": tr(lang, "ask_checkin"), "lang": lang})

    # ================== GEMINI ==================
    try:
        role = tr(lang, "gemini_role")
        info = get_hotel_info(lang)
        guest_label = "Guest asks" if lang == "en" else "Khách hỏi"
        reply = ask_gemini(f"""{role}

{info}

{guest_label}: {msg}
""")
        return jsonify({"reply": reply, "lang": lang})

    except Exception as e:
        print("Gemini error:", e)
        return jsonify({"reply": tr(lang, "system_busy"), "lang": lang})

# ================== RUN ==================
if __name__ == "__main__":
    app.run(debug=True)
