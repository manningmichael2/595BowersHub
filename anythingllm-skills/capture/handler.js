module.exports.runtime = {
  handler: async function ({ text, image_path, domain_hint }) {
    try {
      const t = (text || "").trim();
      const img = (image_path || "").trim();
      const hint = (domain_hint || "").trim();

      if (!t && !img) {
        return "Error: provide at least one of `text` or `image_path`.";
      }

      const body = {};
      if (t) body.text = t;
      if (img) body.image_path = img;
      if (hint) body.domain_hint = hint;

      const url = "http://100.106.180.101:5678/webhook/smart-capture/extract";
      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      if (!response.ok) {
        const txt = await response.text().catch(() => "");
        return `Error from Smart Capture extract: HTTP ${response.status} ${txt.slice(0, 200)}`;
      }

      const data = await response.json();

      // Caller (the agent) gets the full extraction. The agent is then expected
      // to present it to the user, gather any corrections/clarifications, and
      // call `capture-commit` per intent to persist.
      return JSON.stringify(data, null, 2);
    } catch (error) {
      return `Smart Capture failed: ${error.message}`;
    }
  },
};
