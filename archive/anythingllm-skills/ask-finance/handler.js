module.exports.runtime = {
  handler: async function ({ question }) {
    try {
      if (!question || question.trim().length === 0) {
        return "Please provide a question.";
      }

      const url = "http://100.106.180.101:5678/webhook/finance-query";
      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      });

      if (!response.ok) {
        return `Error from finance query service: HTTP ${response.status}`;
      }

      const data = await response.json();

      if (data.error) {
        return `Error: ${data.error}`;
      }

      // Return a clean summary for the agent to work with
      const summary = {
        question: data.question,
        sql_generated: data.sql_generated,
        row_count: data.row_count,
        results: data.results,
      };

      return JSON.stringify(summary, null, 2);
    } catch (error) {
      return `Failed to answer finance question: ${error.message}`;
    }
  },
};
