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
    client_lang = client_lang if client_lang in ("vi", "en") else "vi"
    if len(message.strip()) < 4:
        return client_lang
    if VI_DIACRITICS.search(message):
        return "vi"
    words = re.findall(r"[a-zA-Z]+", message.lower())
    en_hits = sum(1 for w in words if w in EN_KEYWORDS)
    if en_hits >= 2:
        return "en"
    return client_lang

# ================== I18N STRINGS ==================
T = {
    "vi": {
        "empty": "Quý khách vui lòng nhập nội dung 😊",
        "ask_checkin": "Ngày nhận phòng? (VD: 20/06/2026)",
        "ask_checkout": "Ngày trả phòng? (DD/MM/YYYY)",
        "ask_room": "Chọn loại phòng:",
        "ask_name": "Tên của quý khách?",
        "ask_phone": "Số điện thoại liên hệ?",
        "btn_single": "🛏 Phòng đơn – 800k/đêm",
        "btn_double": "🛏🛏 Phòng đôi – 1.2tr/đêm",
        "btn_suite": "👑 Suite – 2tr/đêm",
        "btn_confirm": "✅ Xác nhận đặt phòng",
        "btn_cancel": "❌ Hủy",
        "summary_title": "📋 Xác nhận đặt phòng:",
        "s_checkin": "Check-in",
        "s_checkout": "Check-out",
        "s_nights": "đêm",
        "s_room": "Phòng",
        "s_name": "Tên",
        "s_phone": "SĐT",
        "s_total": "Tổng tiền",
        "s_deposit": "Đặt cọc 30%",
        "no_room": "❌ Phòng đã hết trong khoảng thời gian này. Vui lòng chọn ngày khác.",
        "book_error": "❌ Có lỗi xảy ra khi đặt phòng. Vui lòng thử lại.",
        "book_success": "🎉 Đặt phòng thành công!\nKhách sạn sẽ liên hệ xác nhận và hướng dẫn đặt cọc sớm nhất.\nCảm ơn quý khách! 🙏",
        "book_cancel": "Đã hủy đặt phòng. Quý khách cần hỗ trợ gì thêm không? 😊",
        "system_busy": "Hệ thống đang bận, vui lòng thử lại sau.",
        "gemini_role": "Bạn là lễ tân khách sạn EDEN Regent Phú Quốc.\nTrả lời ngắn gọn, lịch sự, thân thiện bằng TIẾNG VIỆT.\nKhông dùng markdown.",
    },
    "en": {
        "empty": "Please type a message 😊",
        "ask_checkin": "Check-in date? (e.g. 20/06/2026)",
        "ask_checkout": "Check-out date? (DD/MM/YYYY)",
        "ask_room": "Choose a room type:",
        "ask_name": "Your name, please?",
        "ask_phone": "Contact phone number?",
        "btn_single": "🛏 Single – 800k/night",
        "btn_double": "🛏🛏 Double – 1.2M/night",
        "btn_suite": "👑 Suite – 2M/night",
        "btn_confirm": "✅ Confirm booking",
        "btn_cancel": "❌ Cancel",
        "summary_title": "📋 Booking confirmation:",
        "s_checkin": "Check-in",
        "s_checkout": "Check-out",
        "s_nights": "nights",
        "s_room": "Room",
        "s_name": "Name",
        "s_phone": "Phone",
        "s_total": "Total",
        "s_deposit": "30% deposit",
        "no_room": "❌ No rooms available for those dates. Please choose other dates.",
        "book_error": "❌ Something went wrong while booking. Please try again.",
        "book_success": "🎉 Booking successful!\nThe hotel will contact you shortly to confirm and guide the deposit.\nThank you! 🙏",
        "book_cancel": "Booking cancelled. Anything else I can help with? 😊",
        "system_busy": "The system is busy, please try again later.",
        "gemini_role": "You are the receptionist of EDEN Regent Phu Quoc hotel.\nReply briefly, politely and warmly in ENGLISH.\nDo not use markdown.",
    }
}

def tr(lang, key):
    return T.get(lang, T["vi"]).get(key, T["vi"].get(key, key))

# ================== DATA ==================
HOTEL_INFO = {
    "vi": """
Tên khách sạn: EDEN Regent Phu Quoc
Địa chỉ: Phú Quốc
Hotline: 0123 456 789

Giá phòng:
- Phòng đơn: 800.000đ / đêm
- Phòng đôi: 1.200.000đ / đêm
- Phòng Suite: 2.000.000đ / đêm

Check-in: 14:00
Check-out: 12:00

Tiện ích:
- Hồ bơi ngoài trời
- Phòng gym
- Spa
- Nhà hàng
- Wi-Fi miễn phí
- Lễ tân 24/7
- Quầy bar trên cao
- Xe điện di chuyển quanh khách sạn

Chính sách đặt cọc:
Để đảm bảo giữ phòng, quý khách vui lòng đặt cọc trước 30% tổng giá trị booking.

Thanh toán:
- 30% đặt cọc khi xác nhận đặt phòng
- 70% còn lại thanh toán khi nhận phòng

Chính sách hủy:
- Hủy trước 24 giờ: hoàn lại 100% tiền cọc
- Hủy trong vòng 24 giờ: không hoàn cọc

Lưu ý:
Đặt phòng chỉ được xác nhận sau khi khách sạn nhận được tiền cọc.
""",
    "en": """
Hotel name: EDEN Regent Phu Quoc
Address: Phu Quoc, Vietnam
Hotline: 0123 456 789

Room rates:
- Single room: 800,000 VND / night
- Double room: 1,200,000 VND / night
- Suite: 2,000,000 VND / night

Check-in: 14:00
Check-out: 12:00

Amenities:
- Outdoor swimming pool
- Gym
- Spa
- Restaurant
- Free Wi-Fi
- 24/7 reception
- Sky bar
- Electric shuttle around the resort

Deposit policy:
To secure the booking, please pay a 30% deposit of the total value in advance.

Payment:
- 30% deposit on booking confirmation
- 70% balance paid at check-in

Cancellation policy:
- Cancel more than 24 hours in advance: 100% deposit refund
- Cancel within 24 hours: deposit non-refundable

Note:
A booking is only confirmed after the hotel receives the deposit.
"""
}

ROOM_PRICES = {
    "Phòng đơn": 800000,
    "Phòng đôi": 1200000,
    "Suite": 2000000
}

def normalize_room(text):
    t_low = text.lower().strip()
    if any(k in t_low for k in ["suite", "👑"]):
        return "Suite"
    if any(k in t_low for k in ["đôi", "doi", "double", "🛏🛏"]):
        return "Phòng đôi"
    if any(k in t_low for k in ["đơn", "don", "single", "🛏"]):
        return "Phòng đơn"
    return text

ROOM_DISPLAY = {
    "vi": {"Phòng đơn": "Phòng đơn", "Phòng đôi": "Phòng đôi", "Suite": "Suite"},
    "en": {"Phòng đơn": "Single room", "Phòng đôi": "Double room", "Suite": "Suite"},
}

# ================== ROUTES ==================
@app.route("/")
def home():
    session.clear()
    return render_template("index.html")

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
        step = session["step"]
        b = session.get("booking", {})

        if step == "checkin":
            b["checkin"] = normalize_date(msg)
            session["booking"] = b
            session["step"] = "checkout"
            return jsonify({"reply": tr(lang, "ask_checkout"), "lang": lang})

        if step == "checkout":
            b["checkout"] = normalize_date(msg)
            session["booking"] = b
            session["step"] = "room"
            return jsonify({
                "reply": tr(lang, "ask_room"),
                "lang": lang,
                "buttons": [
                    {"label": tr(lang, "btn_single"), "value": "Phòng đơn"},
                    {"label": tr(lang, "btn_double"), "value": "Phòng đôi"},
                    {"label": tr(lang, "btn_suite"),  "value": "Suite"}
                ]
            })

        if step == "room":
            b["room"] = normalize_room(msg)
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
            session["step"] = "confirm"

            try:
                checkin_dt = datetime.strptime(b["checkin"], "%d/%m/%Y")
                checkout_dt = datetime.strptime(b["checkout"], "%d/%m/%Y")
                nights = (checkout_dt - checkin_dt).days
                price_per_night = ROOM_PRICES.get(b["room"], 0)
                total = nights * price_per_night
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

            room_display = ROOM_DISPLAY.get(lang, {}).get(b["room"], b["room"])

            summary = (
                f"{tr(lang, 'summary_title')}\n"
                f"• {tr(lang, 's_checkin')}: {b['checkin']}\n"
                f"• {tr(lang, 's_checkout')}: {b['checkout']} ({nights_str})\n"
                f"• {tr(lang, 's_room')}: {room_display}\n"
                f"• {tr(lang, 's_name')}: {b['name']}\n"
                f"• {tr(lang, 's_phone')}: {b['phone']}\n"
                f"• {tr(lang, 's_total')}: {total_str}\n"
                f"• {tr(lang, 's_deposit')}: {deposit_str}"
            )

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
                    if not is_room_available(b["checkin"], b["checkout"], b["room"]):
                        session.clear()
                        return jsonify({"reply": tr(lang, "no_room"), "lang": lang})

                    b["guests"] = ""
                    b["note"] = ""
                    save_booking(b)
                    subtract_rooms(b["checkin"], b["checkout"], b["room"])

                except Exception as e:
                    print("ERROR:", e)
                    return jsonify({"reply": tr(lang, "book_error"), "lang": lang})

                session.clear()
                return jsonify({"reply": tr(lang, "book_success"), "lang": lang})

            if msg_lower == "cancel":
                session.clear()
                return jsonify({"reply": tr(lang, "book_cancel"), "lang": lang})

    # ================== START BOOKING ==================
    booking_triggers = [
        "đặt phòng", "dat phong", "đặt", "booking", "book",
        "book a room", "book room", "reserve", "reservation"
    ]
    if any(k in msg_lower for k in booking_triggers):
        session.clear()
        session["step"] = "checkin"
        session["booking"] = {}
        session["lang"] = lang
        return jsonify({"reply": tr(lang, "ask_checkin"), "lang": lang})

    # ================== GEMINI ==================
    try:
        role = tr(lang, "gemini_role")
        info = HOTEL_INFO.get(lang, HOTEL_INFO["vi"])
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
