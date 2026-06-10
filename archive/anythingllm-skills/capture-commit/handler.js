module.exports.runtime = {
  handler: async function ({ domain, payload, asset_id, extract_token }) {
    try {
      const d = (domain || "").trim().toLowerCase();
      if (!d) {
        return "Error: `domain` is required.";
      }

      // AnythingLLM sometimes serializes object params as JSON strings depending
      // on the model. Accept either an object or a JSON-string payload.
      let p = payload;
      if (typeof p === "string") {
        try { p = JSON.parse(p); }
        catch (e) { return `Error: payload was a string and not valid JSON (${e.message}).`; }
      }
      if (!p || typeof p !== "object" || Array.isArray(p)) {
        return "Error: `payload` must be an object whose shape depends on the domain.";
      }

      const token = (extract_token || "").trim();
      if (!token) {
        return "Error: `extract_token` is required. You MUST call the `capture` skill first to get an extract_token. Do NOT call capture-commit without a successful capture response.";
      }

      const body = { domain: d, payload: p, source: "anythingllm", extract_token: token };
      const aid = (asset_id || "").trim();
      if (aid) body.asset_id = aid;

      const url = "http://100.106.180.101:5678/webhook/smart-capture/commit";
      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      if (!response.ok) {
        const txt = await response.text().catch(() => "");
        return `Error from Smart Capture commit: HTTP ${response.status} ${txt.slice(0, 200)}`;
      }

      const data = await response.json();
      return JSON.stringify(data, null, 2);
    } catch (error) {
      return `Smart Capture commit failed: ${error.message}`;
    }
  },
};
