/**
 * Pakistan Law Bot — Web Application Client Logic
 * Handles interactive chat, multi-turn history, statutory citations, and language toggles.
 */

document.addEventListener("DOMContentLoaded", () => {
  // DOM References
  const chatContainer = document.getElementById("chat-container");
  const welcomeHero = document.getElementById("welcome-hero");
  const messagesStream = document.getElementById("messages-stream");
  const chatForm = document.getElementById("chat-form");
  const chatInput = document.getElementById("chat-input");
  const sendBtn = document.getElementById("send-btn");
  const clearChatBtn = document.getElementById("clear-chat-btn");
  const lawList = document.getElementById("law-list");
  const chunkCountEl = document.getElementById("chunk-count");
  const lawCountEl = document.getElementById("law-count");
  const coverageBadgeEl = document.getElementById("coverage-badge");
  const statusDot = document.getElementById("status-dot");
  const statusText = document.getElementById("status-text");

  // Mobile Drawer Toggle
  const sidebar = document.getElementById("sidebar");
  const menuToggleBtn = document.getElementById("menu-toggle-btn");
  const sidebarCloseBtn = document.getElementById("sidebar-close-btn");

  // Language buttons
  const langEn = document.getElementById("lang-en");
  const langRo = document.getElementById("lang-ro");
  const langUr = document.getElementById("lang-ur");

  // Session State
  let conversationHistory = [];
  let isSubmitting = false;
  let activeLanguage = "en";

  // --------------------------------------------------------------------------
  // Auto-resize textarea
  // --------------------------------------------------------------------------
  chatInput.addEventListener("input", () => {
    chatInput.style.height = "auto";
    chatInput.style.height = Math.min(chatInput.scrollHeight, 140) + "px";
  });

  chatInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (!isSubmitting && chatInput.value.trim()) {
        chatForm.dispatchEvent(new Event("submit"));
      }
    }
  });

  // --------------------------------------------------------------------------
  // Mobile Sidebar Toggle
  // --------------------------------------------------------------------------
  if (menuToggleBtn) {
    menuToggleBtn.addEventListener("click", () => sidebar.classList.add("open"));
  }
  if (sidebarCloseBtn) {
    sidebarCloseBtn.addEventListener("click", () => sidebar.classList.remove("open"));
  }

  // --------------------------------------------------------------------------
  // Language Selector
  // --------------------------------------------------------------------------
  function setLanguage(lang) {
    activeLanguage = lang;
    [langEn, langRo, langUr].forEach(b => b.classList.remove("active"));

    if (lang === "en") {
      langEn.classList.add("active");
      chatInput.dir = "ltr";
      chatInput.placeholder = "Ask a legal question in English... (e.g. Can landlord cutoff amenities?)";
      chatInput.classList.remove("rtl-text");
    } else if (lang === "ro") {
      langRo.classList.add("active");
      chatInput.dir = "ltr";
      chatInput.placeholder = "Roman Urdu mein sawaal poochein... (e.g. Agar landlord bina notice ke nikale?)";
      chatInput.classList.remove("rtl-text");
    } else if (lang === "ur") {
      langUr.classList.add("active");
      chatInput.dir = "rtl";
      chatInput.placeholder = "اردو میں قانونی سوال پوچھیے... (مثلاً: کرایہ دار کو بے دخل کرنے کا کیا طریقہ ہے؟)";
      chatInput.classList.add("rtl-text");
    }
  }

  langEn.addEventListener("click", () => setLanguage("en"));
  langRo.addEventListener("click", () => setLanguage("ro"));
  langUr.addEventListener("click", () => setLanguage("ur"));

  // --------------------------------------------------------------------------
  // Fetch System Stats & Loaded Laws
  // --------------------------------------------------------------------------
  async function initKnowledgeBase() {
    try {
      const [statsRes, lawsRes] = await Promise.all([
        fetch("/api/stats"),
        fetch("/api/laws")
      ]);

      if (statsRes.ok) {
        const stats = await statsRes.json();
        chunkCountEl.textContent = stats.indexed_chunks.toLocaleString();
        lawCountEl.textContent = stats.loaded_laws_count;
        coverageBadgeEl.textContent = `${stats.loaded_laws_count} Laws`;
        statusText.textContent = "Knowledge Base Active";
        statusDot.classList.remove("pulse");
      }

      if (lawsRes.ok) {
        const data = await lawsRes.json();
        renderLawCards(data.laws || []);
      }
    } catch (err) {
      console.error("Failed to load knowledge base metadata:", err);
      statusText.textContent = "Offline / Connection Error";
      statusDot.style.backgroundColor = "#ef4444";
    }
  }

  function renderLawCards(laws) {
    lawList.innerHTML = "";
    laws.forEach(law => {
      const card = document.createElement("div");
      card.className = "law-card";
      const jurClass = (law.jurisdiction || "").toLowerCase().includes("punjab") ? "punjab" : "federal";
      card.innerHTML = `
        <div class="law-header">
          <span class="law-short-title" title="${law.title}">${escapeHtml(law.short_title || law.title)}</span>
          <span class="law-badge ${jurClass}">${law.jurisdiction || "Federal"}</span>
        </div>
        <div class="law-meta-row">
          <span>Category: ${law.category || "General"}</span>
          <span class="law-sections">${law.expected_section_count ? law.expected_section_count + ' Secs' : 'Active'}</span>
        </div>
      `;
      lawList.appendChild(card);
    });
  }

  // --------------------------------------------------------------------------
  // Starter Prompts Click Handler
  // --------------------------------------------------------------------------
  document.querySelectorAll(".prompt-card").forEach(card => {
    card.addEventListener("click", () => {
      const query = card.getAttribute("data-query");
      if (query) {
        chatInput.value = query;
        chatForm.dispatchEvent(new Event("submit"));
      }
    });
  });

  // --------------------------------------------------------------------------
  // Clear Conversation
  // --------------------------------------------------------------------------
  clearChatBtn.addEventListener("click", () => {
    conversationHistory = [];
    messagesStream.innerHTML = "";
    welcomeHero.style.display = "flex";
    chatInput.value = "";
    chatInput.focus();
  });

  // --------------------------------------------------------------------------
  // Message Rendering with Markdown & Citations
  // --------------------------------------------------------------------------
  function appendUserMessage(text) {
    welcomeHero.style.display = "none";

    const msgWrapper = document.createElement("div");
    msgWrapper.className = "message-wrapper user";
    const isUrdu = isUrduText(text);

    msgWrapper.innerHTML = `
      <div class="message-header">You</div>
      <div class="message-bubble ${isUrdu ? 'rtl-text' : ''}">${escapeHtml(text)}</div>
    `;

    messagesStream.appendChild(msgWrapper);
    scrollToBottom();
  }

  function appendTypingIndicator() {
    const wrapper = document.createElement("div");
    wrapper.className = "message-wrapper assistant";
    wrapper.id = "typing-indicator";
    wrapper.innerHTML = `
      <div class="message-header">Pakistan Law Bot</div>
      <div class="message-bubble">
        <div class="typing-skeleton">
          <div class="typing-dot"></div>
          <div class="typing-dot"></div>
          <div class="typing-dot"></div>
        </div>
      </div>
    `;
    messagesStream.appendChild(wrapper);
    scrollToBottom();
    return wrapper;
  }

  function appendAssistantMessage(data) {
    const indicator = document.getElementById("typing-indicator");
    if (indicator) indicator.remove();

    const msgWrapper = document.createElement("div");
    msgWrapper.className = "message-wrapper assistant";

    const rawAnswer = data.answer || "No response received.";
    const isUrdu = isUrduText(rawAnswer);
    const formattedHtml = formatLegalMarkdown(rawAnswer);

    const citationsCount = (data.citations && data.citations.citation_count) || 0;
    const sourceSections = (data.source_sections || []).join(", ");

    msgWrapper.innerHTML = `
      <div class="message-header">
        <span>🏛️ Pakistan Law Bot</span>
        ${citationsCount > 0 ? `<span class="badge-count">${citationsCount} Statutory Citations</span>` : ''}
      </div>
      <div class="message-bubble ${isUrdu ? 'rtl-text' : ''}">
        ${formattedHtml}
        <div class="message-footer">
          <div class="cited-laws-tag">
            <span>Sections:</span>
            <span>${sourceSections || 'Statutory review'}</span>
          </div>
          <button class="copy-btn" title="Copy answer to clipboard">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
            <span>Copy</span>
          </button>
        </div>
      </div>
    `;

    // Copy to clipboard listener
    const copyBtn = msgWrapper.querySelector(".copy-btn");
    copyBtn.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(rawAnswer);
        copyBtn.innerHTML = `
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>
          <span style="color: #10b981;">Copied!</span>
        `;
        setTimeout(() => {
          copyBtn.innerHTML = `
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
            <span>Copy</span>
          `;
        }, 2200);
      } catch (e) {
        console.error("Clipboard copy failed:", e);
      }
    });

    messagesStream.appendChild(msgWrapper);
    scrollToBottom();
  }

  // --------------------------------------------------------------------------
  // Form Submission & API Query
  // --------------------------------------------------------------------------
  chatForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const question = chatInput.value.trim();
    if (!question || isSubmitting) return;

    isSubmitting = true;
    sendBtn.disabled = true;
    chatInput.value = "";
    chatInput.style.height = "auto";

    appendUserMessage(question);
    appendTypingIndicator();

    try {
      const response = await fetch("/api/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: question,
          history: conversationHistory,
        })
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || "Failed to process question.");
      }

      appendAssistantMessage(data);

      // Keep multi-turn conversation memory
      if (data.in_scope && !data.answer.startsWith("Error:")) {
        conversationHistory.push({ role: "user", content: question });
        conversationHistory.push({ role: "assistant", content: data.answer });
      }

    } catch (err) {
      const indicator = document.getElementById("typing-indicator");
      if (indicator) indicator.remove();

      appendAssistantMessage({
        answer: `**Error:** ${escapeHtml(err.message || "An unexpected error occurred. Please check server logs.")}\n\nPlease try again.`,
        citations: { citation_count: 0 },
        source_sections: []
      });
    } finally {
      isSubmitting = false;
      sendBtn.disabled = false;
      chatInput.focus();
    }
  });

  // --------------------------------------------------------------------------
  // Utility Functions
  // --------------------------------------------------------------------------
  function scrollToBottom() {
    chatContainer.scrollTo({
      top: chatContainer.scrollHeight,
      behavior: "smooth"
    });
  }

  function isUrduText(text) {
    const urduPattern = /[\u0600-\u06FF]/;
    return urduPattern.test(text);
  }

  function escapeHtml(str) {
    return (str || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function formatLegalMarkdown(raw) {
    let text = escapeHtml(raw);

    // Format statutory citations [Act Name - Section X]
    text = text.replace(
      /\[([A-Za-z0-9\s,\.\-—–]+?\s*-\s*Section\s+\d+[A-Za-z]?(?:\([^)]*\))*)\]/g,
      '<span class="citation-badge">§ $1</span>'
    );

    // Headings
    text = text.replace(/^### (.*$)/gim, '<h3>$1</h3>');
    text = text.replace(/^## (.*$)/gim, '<h3>$1</h3>');

    // Bold text
    text = text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');

    // Bullet points
    text = text.replace(/^\s*\*\s+(.*$)/gim, '<li>$1</li>');
    text = text.replace(/^\s*-\s+(.*$)/gim, '<li>$1</li>');
    text = text.replace(/(<li>.*<\/li>)/gims, '<ul>$1</ul>');
    text = text.replace(/<\/ul>\s*<ul>/g, '');

    // Numbered lists
    text = text.replace(/^\s*(\d+)\.\s+(.*$)/gim, '<li><strong>$1.</strong> $2</li>');

    // Paragraph breaks
    text = text.replace(/\n\n+/g, '</p><p>');
    text = '<p>' + text + '</p>';
    text = text.replace(/<p><\/p>/g, '');
    text = text.replace(/<p><h3>/g, '<h3>');
    text = text.replace(/<\/h3><\/p>/g, '</h3>');
    text = text.replace(/<p><ul>/g, '<ul>');
    text = text.replace(/<\/ul><\/p>/g, '</ul>');

    return text;
  }

  // Initialize
  initKnowledgeBase();
});
