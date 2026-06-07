module.exports.runtime = {
  handler: async function ({ to, subject, body, is_html }) {
    try {
      const recipient = (to || "").trim();
      const subj = (subject || "").trim();
      const content = (body || "").trim();

      if (!recipient) return "Error: `to` (recipient email) is required.";
      if (!subj) return "Error: `subject` is required.";
      if (!content) return "Error: `body` is required.";

      // Basic email format check
      if (!recipient.includes("@")) {
        return `Error: '${recipient}' doesn't look like a valid email address.`;
      }

      const html = (is_html || "").toLowerCase() === "true";

      const url = "http://100.106.180.101:5678/webhook/send-email";
      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          to: recipient,
          subject: subj,
          body: content,
          is_html: html,
        }),
      });

      if (!response.ok) {
        const txt = await response.text().catch(() => "");
        return `Error sending email: HTTP ${response.status} ${txt.slice(0, 200)}`;
      }

      const data = await response.json();
      return JSON.stringify(data, null, 2);
    } catch (error) {
      return `Send email failed: ${error.message}`;
    }
  },
};
