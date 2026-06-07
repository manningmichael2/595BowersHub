// Simple per-session call counter to prevent runaway loops.
// Resets when the module is re-loaded (i.e., new agent session / restart).
let callCount = 0;
const MAX_CALLS_PER_SESSION = 15;

module.exports.runtime = {
  handler: async function ({ question }) {
    try {
      if (!question || question.trim().length === 0) {
        return "Please provide a question.";
      }

      callCount++;
      if (callCount > MAX_CALLS_PER_SESSION) {
        return JSON.stringify({
          error: "RATE_LIMIT",
          message: `You have made ${callCount} database queries this session (limit: ${MAX_CALLS_PER_SESSION}). This usually means you're querying one row at a time instead of writing a single query that returns everything you need. Please write ONE comprehensive SQL question (e.g., "show all tools with their brand, model, condition, and current_value_estimate") instead of asking about each item individually. If you genuinely need more queries, ask the user to start a new chat.`,
          calls_made: callCount,
          limit: MAX_CALLS_PER_SESSION,
        });
      }

      const url = "http://100.106.180.101:5678/webhook/finance-query";
      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      });

      if (!response.ok) {
        return `Error from database query service: HTTP ${response.status}`;
      }

      const data = await response.json();

      if (data.error) {
        return `Error: ${data.error}`;
      }

      const summary = {
        question: data.question,
        sql_generated: data.sql_generated,
        row_count: data.row_count,
        results: data.results,
        _calls_remaining: MAX_CALLS_PER_SESSION - callCount,
      };

      return JSON.stringify(summary, null, 2);
    } catch (error) {
      return `Failed to query database: ${error.message}`;
    }
  },
};
