(() => {
  function collectPageContext() {
    const selected_text = window.getSelection ? String(window.getSelection()) : "";
    const headings = Array.from(document.querySelectorAll("h1, h2, h3"))
      .slice(0, 20)
      .map((h) => h.textContent?.trim())
      .filter(Boolean);
    const meta = document.querySelector("meta[name='description']")?.getAttribute("content") || "";

    return {
      title: document.title || "",
      url: location.href,
      selected_text,
      page_summary: [meta, ...headings].filter(Boolean).join(" | "),
    };
  }

  chrome.runtime.onMessage.addListener((message, _, sendResponse) => {
    if (message?.type === "FOCUS_COLLECT_PAGE") {
      sendResponse(collectPageContext());
    }
    if (message?.type === "FOCUS_READ_PAGE") {
      const bodyText = (document.body?.innerText || "").slice(0, 25000);
      sendResponse({ text: bodyText, ...collectPageContext() });
    }
    return true;
  });
})();
