module.exports.runtime = {
  handler: async function ({ topic, fact }) {
    try {
      if (!topic || topic.trim().length === 0) {
        return "Please provide a topic (e.g., 'finance/accounts').";
      }
      if (!fact || fact.trim().length === 0) {
        return "Please provide a fact to remember.";
      }

      const url = "http://100.106.180.101:5678/webhook/remember";
      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ topic, fact }),
      });

      if (!response.ok) {
        return `Error from knowledge service: HTTP ${response.status}`;
      }

      const data = await response.json();
      return JSON.stringify(data, null, 2);
    } catch (error) {
      return `Failed to save fact: ${error.message}`;
    }
  },
};
