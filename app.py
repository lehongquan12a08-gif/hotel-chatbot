from flask import Flask, render_template, request, jsonify, session
import os
from google_sheet import (
    save_booking,
    normalize_date,
    is_room_available,
    subtract_rooms
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

# ================== DATA ==================
HOTEL_INFO = """
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
"""

ROOM_PRICES = {
    "Phòng đơn": 800000,
    "Phòng đôi": 1200000,
    "Suite": 2000000
}

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

    # ================== FLOW ==================
    if "step" in session:
        step = session["step"]
        b = session.get("booking", {})

        # ===== CHECK-IN =====
        if step == "checkin":
            b["checkin"] = normalize_date(msg)
            session["booking"] = b
            session["step"] = "checkout"
            return jsonify({"reply": "Ngày trả phòng? (DD/MM/YYYY)"})

        # ===== CHECK-OUT =====
        if step == "checkout":
            b["checkout"] = normalize_date(msg)
            session["booking"] = b
            session["step"] = "room"
            return jsonify({
                "reply": "Chọn loại phòng:",
                "buttons": [
                    {"label": "🛏 Phòng đơn – 800k/đêm", "value": "Phòng đơn"},
                    {"label": "🛏🛏 Phòng đôi – 1.2tr/đêm", "value": "Phòng đôi"},
                    {"label": "👑 Suite – 2tr/đêm", "value": "Suite"}
                ]
            })

        # ===== ROOM =====
        if step == "room":
            b["room"] = msg
            session["booking"] = b
            session["step"] = "name"
            return jsonify({"reply": "Tên của quý khách?"})

        # ===== NAME =====
        if step == "name":
            b["name"] = msg
            session["booking"] = b
            session["step"] = "phone"
            return jsonify({"reply": "Số điện thoại liên hệ?"})

        # ===== PHONE =====
        if step == "phone":
            b["phone"] = msg
            session["booking"] = b
            session["step"] = "confirm"

            # Calculate nights
            from datetime import datetime
            try:
                checkin_dt = datetime.strptime(b["checkin"], "%d/%m/%Y")
                checkout_dt = datetime.strptime(b["checkout"], "%d/%m/%Y")
                nights = (checkout_dt - checkin_dt).days
                price_per_night = ROOM_PRICES.get(b["room"], 0)
                total = nights * price_per_night
                total_str = f"{total:,.0f}đ"
                nights_str = f"{nights} đêm"
            except:
                nights_str = "N/A"
                total_str = "N/A"

            summary = (
                f"📋 Xác nhận đặt phòng:\n"
                f"• Check-in: {b['checkin']}\n"
                f"• Check-out: {b['checkout']} ({nights_str})\n"
                f"• Phòng: {b['room']}\n"
                f"• Tên: {b['name']}\n"
                f"• SĐT: {b['phone']}\n"
                f"• Tổng tiền: {total_str}\n"
                f"• Đặt cọc 30%: {int(total * 0.3):,.0f}đ"
            )

            return jsonify({
                "reply": summary,
                "buttons": [
                    {"label": "✅ Xác nhận đặt phòng", "value": "confirm"},
                    {"label": "❌ Hủy", "value": "cancel"}
                ]
            })

        # ===== CONFIRM =====
        if step == "confirm":
            if msg_lower == "confirm":
                try:
                    if not is_room_available(b["checkin"], b["checkout"], b["room"]):
                        session.clear()
                        return jsonify({"reply": "❌ Phòng đã hết trong khoảng thời gian này. Vui lòng chọn ngày khác."})

                    b["guests"] = ""
                    b["note"] = ""
                    save_booking(b)
                    subtract_rooms(b["checkin"], b["checkout"], b["room"])

                except Exception as e:
                    print("ERROR:", e)
                    return jsonify({"reply": "❌ Có lỗi xảy ra khi đặt phòng. Vui lòng thử lại."})

                session.clear()
                return jsonify({
                    "reply": "🎉 Đặt phòng thành công!\nKhách sạn sẽ liên hệ xác nhận và hướng dẫn đặt cọc sớm nhất.\nCảm ơn quý khách! 🙏"
                })

            if msg_lower == "cancel":
                session.clear()
                return jsonify({"reply": "Đã hủy đặt phòng. Quý khách cần hỗ trợ gì thêm không? 😊"})

    # ================== START BOOKING ==================
    if any(k in msg_lower for k in ["đặt phòng", "dat phong", "booking", "book", "đặt"]):
        session.clear()
        session["step"] = "checkin"
        session["booking"] = {}
        return jsonify({"reply": "Ngày nhận phòng? (VD: 20/06/2026)"})

    # ================== GEMINI ==================
    try:
        reply = ask_gemini(f"""
Bạn là lễ tân khách sạn EDEN Regent Phú Quốc.
Trả lời ngắn gọn, lịch sự, thân thiện.
Không dùng markdown.

{HOTEL_INFO}

Khách hỏi: {msg}
""")
        return jsonify({"reply": reply})

    except Exception as e:
        print("Gemini error:", e)
        return jsonify({"reply": "Hệ thống đang bận, vui lòng thử lại sau."})

# ================== RUN ==================
if __name__ == "__main__":
    app.run(debug=True)
