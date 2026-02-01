<script>
const chatBtn = document.getElementById("chat-btn");
const chatBox = document.getElementById("chat-box");
const messages = document.getElementById("messages");
const input = document.getElementById("text");

let greeted = false;

/* ===== TOGGLE CHAT ===== */
chatBtn.onclick = () => {
  const isOpen = chatBox.style.display === "flex";
  chatBox.style.display = isOpen ? "none" : "flex";

  if (!isOpen && !greeted) {
    addMessage(
      "REGENT",
      "- Chào quý khách.\n- Tôi là lễ tân khách sạn EDEN Regent Phú Quốc.\n- Tôi có thể hỗ trợ quý khách điều gì ạ?"
    );
    greeted = true;
  }
};

/* ===== ENTER TO SEND ===== */
input.addEventListener("keydown", e => {
  if (e.key === "Enter") send();
});

/* ===== ADD MESSAGE + BUTTON ===== */
function addMessage(sender, text, buttons = []) {
  const msg = document.createElement("div");
  msg.className = "msg";
  msg.style.whiteSpace = "pre-line";
  msg.innerHTML = `<b>${sender}:</b>\n${text}`;
  messages.appendChild(msg);

  if (buttons.length > 0) {
    const wrap = document.createElement("div");
    wrap.style.display = "flex";
    wrap.style.flexWrap = "wrap";
    wrap.style.gap = "8px";
    wrap.style.margin = "6px 0 12px";

    buttons.forEach(b => {
      const btn = document.createElement("button");
      btn.textContent = b.label;
      btn.style.padding = "6px 14px";
      btn.style.borderRadius = "18px";
      btn.style.border = "none";
      btn.style.cursor = "pointer";
      btn.style.background = "#8a5a00";
      btn.style.color = "white";

      btn.onclick = () => send(b.value);
      wrap.appendChild(btn);
    });

    messages.appendChild(wrap);
  }

  messages.scrollTop = messages.scrollHeight;
}

/* ===== SEND ===== */
async function send(textOverride = null) {
  const text = textOverride || input.value.trim();
  if (!text) return;

  addMessage("Bạn", text);
  input.value = "";

  const res = await fetch("/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message: text })
  });

  const data = await res.json();
  addMessage("REGENT", data.reply, data.buttons || []);
}
</script>
