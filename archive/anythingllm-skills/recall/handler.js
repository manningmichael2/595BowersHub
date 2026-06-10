module.exports.runtime = {
  handler: async function ({ query }) {
    try {
      if (!query || query.trim().length === 0) {
        return "Please provide a query to search for.";
      }

      const url = "http://100.106.180.101:5678/webhook/recall";
      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query }),
      });

      if (!response.ok) {
        return `Error from knowledge service: HTTP ${response.status}`;
      }

      const data = await response.json();
      return JSON.stringify(data, null, 2);
    } catch (error) {
      return `Failed to search knowledge: ${error.message}`;
    }
  },
};
