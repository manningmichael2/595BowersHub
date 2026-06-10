module.exports.runtime = {
  handler: async function ({ path }) {
    try {
      const dirPath = (path || "/files/inbox").trim();
      if (!dirPath.startsWith("/files")) {
        return "Error: path must start with '/files'. Example: '/files/inbox'";
      }

      const url = "http://100.106.180.101:5001/list";
      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: dirPath }),
      });

      if (!response.ok) {
        const txt = await response.text().catch(() => "");
        return `Error listing files: HTTP ${response.status} ${txt.slice(0, 200)}`;
      }

      const data = await response.json();
      if (!data.ok) {
        return `Error: ${data.error}`;
      }

      if (!data.files || data.files.length === 0) {
        return `Directory '${dirPath}' is empty.`;
      }

      // Format as a readable list
      const lines = data.files.map(f => {
        if (f.is_dir) return `📁 ${f.name}/`;
        const kb = f.size ? `${(f.size / 1024).toFixed(1)}KB` : "";
        return `  ${f.name} (${kb})`;
      });

      return `Files in ${dirPath}:\n${lines.join("\n")}`;
    } catch (error) {
      return `List files failed: ${error.message}`;
    }
  },
};
