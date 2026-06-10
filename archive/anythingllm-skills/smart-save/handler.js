module.exports.runtime = {
  handler: async function ({ category, title, content }) {
    try {
      if (!title || !title.trim()) {
        return "Error: A title is required to save content.";
      }
      if (!content || !content.trim()) {
        return "Error: No content provided to save.";
      }

      // Normalize category
      const validCategories = {
        recipe: "cooking/recipes",
        project: "woodshop/projects",
        tool: "woodshop/tools",
        household: "household",
        finance: "finance",
        general: "general"
      };

      const cat = (category || "general").toLowerCase().trim();
      const subdir = validCategories[cat] || "general";

      // Create a filename slug from the title
      const slug = title
        .toLowerCase()
        .trim()
        .replace(/[^a-z0-9]+/g, "-")
        .replace(/^-|-$/g, "");

      if (!slug) {
        return "Error: Could not generate a valid filename from the title.";
      }

      const filePath = `/knowledge/${subdir}/${slug}.md`;

      // Add a header and date stamp to the content
      const now = new Date().toISOString().split("T")[0];
      const fullContent = `# ${title.trim()}\n\n_Saved: ${now}_\n\n${content.trim()}\n`;

      // Ensure the directory exists via filewriter
      const dirPath = `/knowledge/${subdir}`;
      await fetch("http://100.106.180.101:5001/mkdir", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: dirPath })
      });

      // Check if file already exists
      const checkResponse = await fetch("http://100.106.180.101:5001/read-text", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: filePath })
      });

      let status = "saved";
      let writeContent = fullContent;

      if (checkResponse.ok) {
        const existing = await checkResponse.json();
        if (existing.exists && existing.content && existing.content.trim().length > 0) {
          // File exists — append with a separator
          writeContent = `\n\n---\n\n_Updated: ${now}_\n\n${content.trim()}\n`;
          status = "updated";
        }
      }

      // Use /append for both new and existing files.
      // For new files, /append creates the file and parent dirs automatically.
      const writeResponse = await fetch("http://100.106.180.101:5001/append", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: filePath, content: writeContent })
      });

      if (!writeResponse.ok) {
        return `Error writing file: HTTP ${writeResponse.status}`;
      }

      return JSON.stringify({
        status: status,
        message: `${status === "updated" ? "Updated" : "Saved to"} ${filePath}`,
        category: cat,
        title: title.trim(),
        path: filePath
      });
    } catch (error) {
      return `Failed to save: ${error.message}`;
    }
  },
};
