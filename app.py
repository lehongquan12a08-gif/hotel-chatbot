from flask import Flask, render_template, request, jsonify, session
import os, random
from google_sheet import save_booking
from google import genai

app = Flask(__name__)
app.secret_key = "eden-secret-key"

# ================== GEMINI MULTI KEY ==================
def get_gemini_client():
    keys = [
        os.environ.get("GEMINI_API_KEY"),
        os.environ.get("GOOGLE_API_KEY"),
    ]
    keys = [k for k in keys if k]
    if not keys:
        raise ValueError("No Gemini API keys found")
    return genai.Client(api_key=random.choice(keys))

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
Tiện ích khách sạn:
- Hồ bơi ngoài trời
- Phòng gym hiện đại
- Spa & massage
- Nhà hàng buffet sáng
- Quầy bar rooftop
- Dịch vụ đưa đón sân bay
- Wi-Fi miễn phí toàn khách sạn
- Lễ tân 24/7
"""

# ================== ROUTES ==================
@app.route("/")
def home():
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    msg = request.json.get("message", "").strip()

    # ===== KÍCH HOẠT ĐẶT PHÒNG =====
    if any(k in msg.lower() for k in ["đặt phòng", "dat phong", "book", "booking"]):
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

    # ===== FLOW ĐẶT PHÒNG =====
    if "step" in session:
        step = session["step"]
        b = session.get("booking", {})

        if step == "checkin":
            b["checkin"] = msg
            session["booking"] = b
            session["step"] = "checkout"
            return jsonify({
                "reply": "Vui lòng cho biết ngày trả phòng?",
                "buttons": [
                    {"label": "📅 Ngày mai", "value": "ngày mai"},
                    {"label": "📅 Sau 2 ngày", "value": "sau 2 ngày"},
                    {"label": "✍️ Tự nhập", "value": ""}
                ]
            })

        if step == "checkout":
            b["checkout"] = msg
            session["booking"] = b
            session["step"] = "room"
            return jsonify({
                "reply": "Quý khách vui lòng chọn loại phòng:",
                "buttons": [
                    {"label": "Phòng đơn", "value": "Phòng đơn"},
                    {"label": "Phòng đôi", "value": "Phòng đôi"},
                    {"label": "Phòng Suite", "value": "Phòng Suite"},
                ]
            })

        if step == "room":
            b["room"] = msg
            session["booking"] = b
            session["step"] = "guests"
            return jsonify({
                "reply": "Số lượng khách:",
                "buttons": [
                    {"label": "1", "value": "1"},
                    {"label": "2", "value": "2"},
                    {"label": "3", "value": "3"},
                    {"label": "4+", "value": "4+"},
                ]
            })

        if step == "guests":
            b["guests"] = msg
            session["booking"] = b
            session["step"] = "name"
            return jsonify({"reply": "Quý khách vui lòng cho biết tên?"})

        if step == "name":
            b["name"] = msg
            session["booking"] = b
            session["step"] = "phone"
            return jsonify({"reply": "Xin vui lòng cung cấp số điện thoại?"})

        if step == "phone":
            b["phone"] = msg
            session["booking"] = b
            session["step"] = "confirm"

            summary = (
                "Xác nhận đặt phòng:\n"
                f"- Check-in: {b.get('checkin')}\n"
                f"- Check-out: {b.get('checkout')}\n"
                f"- Phòng: {b.get('room')}\n"
                f"- Số khách: {b.get('guests')}\n"
                f"- Tên: {b.get('name')}\n"
                f"- SĐT: {b.get('phone')}"
            )

            return jsonify({
                "reply": summary,
                "buttons": [
                    {"label": "✅ Xác nhận", "value": "Đặt phòng thành công !\n Lễ tân sẽ liên hệ lại sớm nhất cho quý khách !"},
                    {"label": "❌ Hủy", "value": "cancel"},
                ]
            })

        if step == "confirm":
            if msg == "confirm":
                save_booking(session["booking"])
                session.clear()
                return jsonify({
                    "reply": "🎉 Đặt phòng thành công! Lễ tân sẽ liên hệ xác nhận."
                })
            else:
                session.clear()
                return jsonify({"reply": "❌ Đặt phòng đã được hủy."})

    # ===== FAQ GEMINI =====
    try:
        client = get_gemini_client()
        response = client.models.generate_content(
            model="models/gemini-2.5-flash",
            contents=f"{HOTEL_INFO}\n\nKhách hỏi: {msg}"
        )
        reply = response.text.strip()
    except Exception as e:
        print("Gemini error:", e)
        reply = "Xin lỗi, hệ thống đang bận. Vui lòng thử lại sau."

    return jsonify({"reply": reply})


# ================== RUN ==================
if __name__ == "__main__":
    print("🚀 Flask starting...")
    app.run(debug=True)