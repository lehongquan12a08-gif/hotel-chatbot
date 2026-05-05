from flask import Flask, render_template, request, jsonify, session
import os
from google_sheet import (
    save_booking,
    get_room_by_date,
    normalize_date,
    is_room_available,
    subtract_rooms,
    get_hotel_config,   # 👈 Mới
    build_hotel_info    # 👈 Mới
)
import google.generativeai as genai

app = Flask(__name__)
app.secret_key = "eden-secret-key"

# ================== GEMINI ==================
def ask_gemini(prompt):
    genai.configure(api_key=os.environ.get("GOOGLE_API_KEY"))
    model = genai.GenerativeModel("gemini-2.5-flash")
    response = model.generate_content(prompt)
    return response.text.strip()

# ================== HOTEL INFO (dynamic) ==================
# Fallback nếu Google Sheet lỗi
HOTEL_INFO_FALLBACK = """
Tên khách sạn: EDEN Regent Phu Quoc
Địa chỉ: Phú Quốc
Hotline: 0123 456 789
Giá phòng: Phòng đơn 800.000đ, Phòng đôi 1.200.000đ, Suite 2.000.000đ
Check-in: 14:00 | Check-out: 12:00
"""

def get_hotel_info():
    """Đọc thông tin khách sạn từ Google Sheet Config. Fallback nếu lỗi."""
    try:
        config = get_hotel_config()
        if config:
            return build_hotel_info(config)
    except Exception as e:
        print("⚠️ Không đọc được Config sheet:", e)
    return HOTEL_INFO_FALLBACK

# ================== ROUTES ==================
@app.route("/")
def home():
    session.clear()
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    msg = request.json.get("message", "").strip()
    msg_lower = msg.lower()

    if not msg:
        return jsonify({"reply": "Quý khách vui lòng nhập nội dung 😊"})

    # ================== CHECK PHÒNG ==================
    if "còn phòng" in msg_lower or "phòng trống" in msg_lower:
        session.clear()
        session["step"] = "check_date"
        return jsonify({
            "reply": "Bạn muốn kiểm tra ngày nào? (VD: 20/04/2026)"
        })

    # ================== FLOW ==================
    if "step" in session:
        step = session["step"]
        b = session.get("booking", {})

        # ===== CHECK DATE =====
        if step == "check_date":
            date = normalize_date(msg)
            rooms = get_room_by_date(date)
            session.clear()

            if not rooms:
                return jsonify({"reply": "❌ Không có dữ liệu ngày này"})

            msg_text = f"📅 Ngày {date} còn:\n"
            for r, q in rooms.items():
                msg_text += f"- {r}: {q} phòng\n"

            return jsonify({
                "reply": msg_text,
                "buttons": [
                    {"label": "👉 Đặt phòng", "value": "đặt phòng"}
                ]
            })

        # ===== CHECK-IN =====
        if step == "checkin":
            b["checkin"] = normalize_date(msg)
            session["booking"] = b
            session["step"] = "checkout"
            return jsonify({"reply": "Ngày trả phòng? (DD/MM/YYYY)"})

        # ===== CHECK-OUT =====
        if step == "checkout":
            b["checkout"] = normalize_date(msg)
            rooms = get_room_by_date(b["checkin"])

            if not rooms:
                session.clear()
                return jsonify({"reply": "❌ Không có dữ liệu phòng ngày này"})

            session["booking"] = b
            session["step"] = "room"

            return jsonify({
                "reply": "Chọn loại phòng:",
                "buttons": [
                    {"label": f"{r} ({q} phòng)", "value": r}
                    for r, q in rooms.items()
                ]
            })

        # ===== ROOM =====
        if step == "room":
            rooms = get_room_by_date(b["checkin"])

            if not rooms or rooms.get(msg, 0) <= 0:
                return jsonify({"reply": "❌ Phòng này đã hết"})

            b["room"] = msg
            session["booking"] = b
            session["step"] = "guests"

            return jsonify({
                "reply": "Số khách?",
                "buttons": [
                    {"label": "1–2 khách", "value": "1-2"},
                    {"label": "3–4 khách", "value": "3-4"},
                    {"label": "5+ khách", "value": "5+"}
                ]
            })

        # ===== GUESTS =====
        if step == "guests":
            b["guests"] = msg
            session["booking"] = b
            session["step"] = "name"
            return jsonify({"reply": "Tên của bạn?"})

        # ===== NAME =====
        if step == "name":
            b["name"] = msg
            session["booking"] = b
            session["step"] = "phone"
            return jsonify({"reply": "Số điện thoại?"})

        # ===== PHONE =====
        if step == "phone":
            b["phone"] = msg
            session["booking"] = b
            session["step"] = "note"
            return jsonify({
                "reply": "Có ghi chú thêm không?",
                "buttons": [{"label": "Bỏ qua", "value": "skip"}]
            })

        # ===== NOTE =====
        if step == "note":
            b["note"] = "" if msg_lower == "skip" else msg
            session["booking"] = b
            session["step"] = "confirm"

            summary = (
                "📋 Xác nhận đặt phòng:\n"
                f"- Check-in: {b['checkin']}\n"
                f"- Check-out: {b['checkout']}\n"
                f"- Phòng: {b['room']}\n"
                f"- Khách: {b['guests']}\n"
                f"- Tên: {b['name']}\n"
                f"- SĐT: {b['phone']}\n"
                f"- Ghi chú: {b['note']}"
            )

            return jsonify({
                "reply": summary,
                "buttons": [
                    {"label": "✅ Xác nhận", "value": "confirm"},
                    {"label": "❌ Hủy", "value": "cancel"}
                ]
            })

        # ===== CONFIRM =====
        if step == "confirm":
            if msg_lower == "confirm":
                try:
                    if not is_room_available(b["checkin"], b["checkout"], b["room"]):
                        session.clear()
                        return jsonify({
                            "reply": "❌ Phòng đã hết trong khoảng thời gian này"
                        })

                    save_booking(b)
                    subtract_rooms(b["checkin"], b["checkout"], b["room"])

                except Exception as e:
                    print("ERROR:", e)
                    return jsonify({"reply": "❌ Lỗi đặt phòng"})

                session.clear()
                return jsonify({"reply": "🎉 Đặt phòng thành công!"})

            if msg_lower == "cancel":
                session.clear()
                return jsonify({"reply": "❌ Đã hủy đặt phòng"})

    # ================== START BOOKING ==================
    if msg_lower in ["đặt phòng", "dat phong", "booking", "book"]:
        session.clear()
        session["step"] = "checkin"
        session["booking"] = {}
        return jsonify({"reply": "Ngày nhận phòng? (VD: 20/04/2026)"})

    # ================== GEMINI (với hotel info từ Sheet) ==================
    try:
        hotel_info = get_hotel_info()  # 👈 Đọc real-time từ Google Sheet

        reply = ask_gemini(f"""
Bạn là lễ tân khách sạn EDEN.
Trả lời ngắn gọn, lịch sự.

{hotel_info}

Khách hỏi: {msg}
""")
        return jsonify({"reply": reply})

    except Exception as e:
        print("Gemini error:", e)
        return jsonify({
            "reply": "Hệ thống đang bận, vui lòng thử lại sau."
        })

# ================== RUN ==================
if __name__ == "__main__":
    app.run(debug=True)
