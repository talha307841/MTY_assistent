const DAEMON_URL = "http://127.0.0.1:7799";

async function sendBrowserContext(payload) {
  try {
    await fetch(`${DAEMON_URL}/context/browser`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch (err) {
    console.debug("FOCUS daemon unreachable", err);
  }
}

async function onTabActivity(tabId) {
  try {
    const tab = await chrome.tabs.get(tabId);
    if (!tab || !tab.url) return;

    const [result] = await chrome.scripting.executeScript({
      target: { tabId },
      func: () => {
        const selected_text = window.getSelection ? String(window.getSelection()) : "";
        const headings = Array.from(document.querySelectorAll("h1, h2, h3"))
          .slice(0, 20)
          .map((h) => h.textContent?.trim())
          .filter(Boolean);
        const meta = document.querySelector("meta[name='description']")?.getAttribute("content") || "";
        return {
          selected_text,
          page_summary: [meta, ...headings].filter(Boolean).join(" | "),
          title: document.title || "",
          url: location.href,
        };
      },
    });

    if (result && result.result) {
      await sendBrowserContext(result.result);
    }
  } catch (err) {
    console.debug("Failed to read tab context", err);
  }
}

chrome.tabs.onActivated.addListener(async ({ tabId }) => {
  await onTabActivity(tabId);
});

chrome.tabs.onUpdated.addListener(async (tabId, changeInfo) => {
  if (changeInfo.status === "complete") {
    await onTabActivity(tabId);
  }
});
