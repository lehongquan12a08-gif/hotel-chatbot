from flask import Flask, render_template, request, jsonify, session
import os
from google_sheet import save_booking
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
- Lê tân xinh đẹp tuyệt trần
"""

# ================== ROUTES ==================
@app.route("/")
def home():
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    msg = request.json.get("message", "").strip()
    msg_lower = msg.lower()

    # ===== 1. CHẶN RỖNG =====
    if not msg:
        return jsonify({"reply": "Quý khách vui lòng nhập nội dung 😊"})

    # ===== 2. ĐANG TRONG FLOW ĐẶT PHÒNG =====
    if "step" in session:
        step = session["step"]
        b = session["booking"]

        # --- CHECK-IN ---
        if step == "checkin":
            b["checkin"] = msg
            session["step"] = "checkout"
            return jsonify({
                "reply": "Vui lòng cho biết ngày trả phòng?",
                "buttons": [
                    {"label": "📅 Ngày mai", "value": "ngày mai"},
                    {"label": "📅 Sau 2 ngày", "value": "sau 2 ngày"},
                    {"label": "✍️ Tự nhập:", "value": ""}
                ]
            })

        # --- CHECK-OUT ---
        if step == "checkout":
            b["checkout"] = msg
            session["step"] = "room"
            return jsonify({
                "reply": "Quý khách chọn loại phòng?",
                "buttons": [
                    {"label": "🛏️ Phòng đơn", "value": "Phòng đơn"},
                    {"label": "🛏️ Phòng đôi", "value": "Phòng đôi"},
                    {"label": "👑 Suite", "value": "Suite"}
                ]
            })

        # --- ROOM ---
        if step == "room":
            b["room"] = msg
            session["step"] = "guests"
            return jsonify({
                "reply": "Số lượng khách?",
                "buttons": [
                    {"label": "1–2 khách", "value": "1-2"},
                    {"label": "3–4 khách", "value": "3-4"},
                    {"label": "5+ khách", "value": "5+"}
                ]
            })

        # --- GUESTS ---
        if step == "guests":
            b["guests"] = msg
            session["step"] = "name"
            return jsonify({
                "reply": "Quý khách vui lòng cho biết tên?"
            })

        # --- NAME ---
        if step == "name":
            b["name"] = msg
            session["step"] = "phone"
            return jsonify({
                "reply": "Xin vui lòng cung cấp số điện thoại?"
            })

        # --- PHONE ---
        # --- PHONE ---
        if step == "phone":
            b["phone"] = msg
            session["step"] = "note"
            return jsonify({
                "reply": "Quý khách có ghi chú thêm không? (có thể bỏ qua)",
                "buttons": [
                    {"label": "✍️ Hãy ghi ở dưới:", "value": ""},
                    {"label": "⏭️ Bỏ qua", "value": "skip"}
        ]
            })
        
        # --- NOTE ---
        if step == "note":
            if msg_lower == "skip":
                b["note"] = "Không có"
            else:
                b["note"] = msg

            session["step"] = "confirm"

            summary = (
                "Xác nhận đặt phòng:\n"
                f"- Check-in: {b['checkin']}\n"
                f"- Check-out: {b['checkout']}\n"
                f"- Phòng: {b['room']}\n"
                f"- Số khách: {b['guests']}\n"
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

        # --- CONFIRM ---
        if step == "confirm":
            if msg_lower == "confirm":
                try:
                    save_booking(b)
                    print("✅ Saved booking:", b)
                except Exception as e:
                    print("❌ SAVE BOOKING ERROR:", e)
                    return jsonify({
                        "reply": "❌ Lỗi lưu đặt phòng. Lễ tân sẽ kiểm tra lại."
                    })

                session.clear()
                return jsonify({
                    "reply": "🎉 Đặt phòng thành công! Lễ tân sẽ liên hệ sớm."
                })


            if msg_lower == "cancel":
                session.clear()
                return jsonify({
                    "reply": "❌ Đặt phòng đã được hủy."
                })

            # ❗ gõ linh tinh → nhắc lại
            return jsonify({
                "reply": "Quý khách vui lòng chọn ✅ Xác nhận hoặc ❌ Hủy.",
                "buttons": [
                    {"label": "✅ Xác nhận", "value": "confirm"},
                    {"label": "❌ Hủy", "value": "cancel"}
                ]
            })


    # ===== 3. CHỈ GÕ 'đặt phòng' MỚI BẮT ĐẦU BOOKING =====
    if msg_lower in [
        "đặt phòng", "dat phong", "booking", "book",
        "tôi muốn đặt phòng", "toi muon dat phong","cho tôi đặt phòng","cho toi dat phong"
    ]:
        session.clear()
        session["step"] = "checkin"
        session["booking"] = {}

        return jsonify({
            "reply": "Quý khách vui lòng cho biết ngày nhận phòng?",
            "buttons": [
                {"label": "📅 Hôm nay", "value": "hôm nay"},
                {"label": "📅 Ngày mai", "value": "ngày mai"},
                {"label": "✍️ Tự nhập", "value": ""}
            ]
        })


    # ===== 4. TẤT CẢ CÒN LẠI → GEMINI =====
    try:
        reply = ask_gemini(f"""
Bạn là lễ tân khách sạn EDEN Regent Phú Quốc.
Trả lời lịch sự, ngắn gọn, tiếng Việt.

Thông tin khách sạn:
{HOTEL_INFO}

Khách hỏi: {msg}
""")

        return jsonify({"reply": reply})

    except Exception as e:
        print("Gemini error:", e)
        return jsonify({
            "reply": "Xin lỗi quý khách, hệ thống đang bận 😥\nQuý khách có thể thử lại sau hoặc gõ *đặt phòng*."
        })

# ================== RUN ==================
if __name__ == "__main__":
    app.run(debug=True)
