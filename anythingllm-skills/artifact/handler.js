module.exports.runtime = {
  handler: async function ({ title, html }) {
    try {
      const t = (title || "").trim();
      if (!t) return "Error: `title` is required.";

      let content = (html || "").trim();
      if (!content) return "Error: `html` is required.";

      // If the content doesn't look like a full HTML document, wrap it
      if (!content.toLowerCase().includes("<!doctype") && !content.toLowerCase().includes("<html")) {
        content = `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>${t.replace(/</g, "&lt;")}</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 900px; margin: 2rem auto; padding: 0 1rem; line-height: 1.6; color: #1a1a1a; background: #fafafa; }
        h1, h2, h3 { color: #111; }
        table { border-collapse: collapse; width: 100%; margin: 1rem 0; }
        th, td { border: 1px solid #ddd; padding: 0.5rem 0.75rem; text-align: left; }
        th { background: #f0f0f0; font-weight: 600; }
        tr:nth-child(even) { background: #f9f9f9; }
        pre { background: #1e1e1e; color: #d4d4d4; padding: 1rem; border-radius: 6px; overflow-x: auto; }
        code { font-family: 'Fira Code', 'Consolas', monospace; font-size: 0.9em; }
        .mermaid { text-align: center; margin: 1.5rem 0; }
        canvas { max-width: 100%; }
        .meta { color: #666; font-size: 0.85rem; margin-bottom: 1.5rem; }
    </style>
</head>
<body>
    <h1>${t.replace(/</g, "&lt;")}</h1>
    <div class="meta">Generated ${new Date().toLocaleString()}</div>
    ${content}
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
    <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
    <script>if(window.mermaid) mermaid.initialize({startOnLoad:true});</script>
</body>
</html>`;
      }

      // Generate slug for filename
      const slug = t.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 60) || "artifact";
      const filename = `${slug}.html`;
      const path = `/files/artifacts/${filename}`;

      // Write via filewriter (base64 to support any content, overwrite existing)
      const b64 = Buffer.from(content, "utf-8").toString("base64");
      const url = "http://100.106.180.101:5001/write-base64";
      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path, base64: b64, overwrite: true }),
      });

      if (!response.ok) {
        const txt = await response.text().catch(() => "");
        return `Error writing artifact: HTTP ${response.status} ${txt.slice(0, 200)}`;
      }

      const viewUrl = `http://100.106.180.101:5002/files/artifacts/${filename}`;

      return JSON.stringify({
        ok: true,
        title: t,
        filename,
        url: viewUrl,
        message: `Artifact created. View at: ${viewUrl}`
      }, null, 2);
    } catch (error) {
      return `Artifact creation failed: ${error.message}`;
    }
  },
};
