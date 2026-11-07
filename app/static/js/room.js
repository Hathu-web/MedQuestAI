/* Chỉ điều khiển UI xem trước. Không thay thế service AI/Scenario Engine. */
(() => {
  "use strict";
  const room = document.getElementById("simulation-room");
  if (!room) return;
  const input = document.getElementById("message-input");
  const form = document.getElementById("chat-form");
  const send = document.getElementById("send-button");
  const log = document.getElementById("chat-log");
  const error = document.getElementById("chat-error");
  const summaryButton = document.getElementById("summary-button");
  const maxTurns = Number(room.dataset.maxTurns);
  const maxLength = Number(room.dataset.maxLength);
  const csrfToken = document.querySelector('meta[name="csrf-token"]').content;
  const facts = new Set();
  const sampleButtons = [...document.querySelectorAll("[data-question]")];
  let turnCount = 0;
  let hintCount = 0;
  let busy = false;
  let completed = false;

  function updateControls() {
    input.disabled = busy || completed || turnCount >= maxTurns;
    send.disabled = input.disabled;
    sampleButtons.forEach(button => { button.disabled = input.disabled; });
    summaryButton.disabled = busy || completed;
    document.getElementById("focus-chat").disabled = input.disabled;
    document.getElementById("hint-button").disabled = busy || completed || hintCount >= 2;
    document.getElementById("reset-button").disabled = busy;
    document.getElementById("turn-count").textContent = `${turnCount} / ${maxTurns} lượt thử`;
    document.getElementById("conversation-status").textContent = busy ? "Đang lấy phản hồi mẫu…" : completed ? "Đã kết thúc xem trước" : turnCount >= maxTurns ? "Đã đủ lượt thử · Mời tổng kết" : "Phản hồi mẫu";
    form.setAttribute("aria-busy", String(busy));
  }

  function countCharacters() {
    document.getElementById("character-count").textContent = `${input.value.length} / ${maxLength}`;
  }

  function addMessage(role, text) {
    const entry = document.createElement("div");
    entry.className = `chat-entry ${role === "patient" ? "patient-message" : "learner-message"}`;
    const avatar = document.createElement("span");
    avatar.className = "chat-avatar";
    avatar.setAttribute("aria-hidden", "true");
    avatar.textContent = role === "patient" ? room.dataset.patientInitials : "Bạn";
    const body = document.createElement("div");
    const name = document.createElement("span");
    name.className = "speaker-name";
    name.textContent = role === "patient" ? "Bệnh nhân · phản hồi mẫu" : "Bạn";
    const bubble = document.createElement("p");
    bubble.className = "message-bubble";
    // textContent giúp nội dung người dùng không trở thành HTML/script.
    bubble.textContent = text;
    body.append(name, bubble);
    entry.append(avatar, body);
    log.append(entry);
    log.scrollTop = log.scrollHeight;
  }

  function addActivity(text) {
    const item = document.createElement("li");
    const dot = document.createElement("span");
    dot.className = "activity-dot";
    dot.setAttribute("aria-hidden", "true");
    item.append(dot, document.createTextNode(text));
    const activity = document.getElementById("activity-log");
    activity.prepend(item);
    while (activity.children.length > 6) activity.lastElementChild.remove();
  }

  function revealFact(fact) {
    if (!fact || facts.has(fact.key)) return;
    facts.add(fact.key);
    document.getElementById("facts-empty").hidden = true;
    const block = document.createElement("div");
    block.className = "info-block";
    const label = document.createElement("span");
    label.textContent = fact.label;
    const value = document.createElement("p");
    value.textContent = fact.value;
    block.append(label, value);
    document.getElementById("facts-list").append(block);
    document.getElementById("fact-count").textContent = String(facts.size);
    addActivity(`Đã ghi nhận: ${fact.label.toLowerCase()}`);
  }

  form.addEventListener("submit", async event => {
    event.preventDefault();
    const text = input.value.trim();
    if (busy || completed || turnCount >= maxTurns || !text) return;
    error.hidden = true;
    busy = true;
    updateControls();
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);
    try {
      const response = await fetch(room.dataset.messageUrl, {
        method: "POST", credentials: "same-origin", signal: controller.signal,
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken },
        body: JSON.stringify({ text, patient_key: room.dataset.patientKey })
      });
      let payload;
      try {
        payload = await response.json();
      } catch {
        throw new Error("Máy chủ chưa trả về dữ liệu hợp lệ. Câu hỏi vẫn được giữ lại.");
      }
      if (!response.ok || !payload.ok) throw new Error(payload.error?.message || "Không nhận được phản hồi.");
      if (typeof payload.data?.text !== "string" || payload.data.preview_only !== true) throw new Error("Phản hồi mẫu chưa hợp lệ.");
      addMessage("learner", text);
      addMessage("patient", payload.data.text);
      revealFact(payload.data.fact);
      turnCount += 1;
      input.value = "";
      countCharacters();
    } catch (failure) {
      error.textContent = failure.name === "AbortError" ? "Hết thời gian chờ. Câu hỏi vẫn được giữ lại; bạn có thể gửi lại." : failure instanceof TypeError ? "Không kết nối được máy chủ. Câu hỏi vẫn được giữ lại." : failure.message;
      error.hidden = false;
    } finally {
      clearTimeout(timeout);
      busy = false;
      updateControls();
      if (!input.disabled) input.focus();
    }
  });
  input.addEventListener("input", countCharacters);
  input.addEventListener("keydown", event => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      form.requestSubmit();
    }
  });
  sampleButtons.forEach(button => button.addEventListener("click", () => {
    input.value = button.dataset.question;
    countCharacters();
    input.focus();
  }));
  document.getElementById("focus-chat").addEventListener("click", () => input.focus());

  const tabs = [...document.querySelectorAll('[role="tab"]')];
  function activateTab(tab) {
    tabs.forEach(other => {
      const selected = other === tab;
      other.setAttribute("aria-selected", String(selected));
      document.getElementById(other.getAttribute("aria-controls")).hidden = !selected;
    });
  }
  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => activateTab(tab));
    tab.addEventListener("keydown", event => {
      if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
        event.preventDefault();
        const next = tabs[(index + (event.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
        activateTab(next); next.focus();
      }
    });
  });

  document.querySelectorAll("[data-open-dialog]").forEach(button => button.addEventListener("click", () => {
    document.getElementById(button.dataset.openDialog).showModal();
  }));
  document.querySelectorAll("[data-close-dialog]").forEach(button => button.addEventListener("click", () => button.closest("dialog").close()));
  document.getElementById("reset-button").addEventListener("click", () => document.getElementById("reset-dialog").showModal());
  document.getElementById("confirm-reset").addEventListener("click", () => window.location.reload());

  const hints = ["Thử mở đầu bằng câu hỏi rộng để bệnh nhân kể lại điều họ đang trải qua.", "Hãy làm rõ thời điểm bắt đầu và điều bệnh nhân lo lắng; diễn đạt bằng từ ngữ dễ hiểu."];
  document.getElementById("hint-button").addEventListener("click", () => {
    if (hintCount >= hints.length || completed) return;
    const hint = document.getElementById("hint-content");
    hint.textContent = `Gợi ý mẫu: ${hints[hintCount]}`;
    hint.hidden = false;
    hintCount += 1;
    document.getElementById("hint-count").textContent = `${hintCount} / 2 gợi ý mẫu`;
    addActivity("Đã xem một gợi ý mẫu");
    updateControls();
  });
  document.getElementById("summary-form").addEventListener("submit", event => {
    event.preventDefault();
    if (busy || completed) return;
    completed = true;
    document.getElementById("summary-dialog").close();
    document.getElementById("tutor-status").textContent = "Đã hoàn tất xem trước · Chưa chấm AI, chưa lưu bản tổng kết";
    addActivity("Đã hoàn tất bản xem trước");
    updateControls();
    document.getElementById("reset-button").focus();
  });
  updateControls();
})();
