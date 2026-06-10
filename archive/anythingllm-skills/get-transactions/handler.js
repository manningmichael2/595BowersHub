module.exports.runtime = {
  handler: async function ({ start_date, end_date }) {
    try {
      const now = new Date();
      const defaultStart = new Date(now.getTime() - 90 * 24 * 60 * 60 * 1000)
        .toISOString()
        .split("T")[0];
      const defaultEnd = now.toISOString().split("T")[0];

      const start = start_date || defaultStart;
      const end = end_date || defaultEnd;

      const url = `http://100.106.180.101:5678/webhook/transactions?start=${start}&end=${end}`;
      const response = await fetch(url);

      if (!response.ok) {
        return `Error fetching transactions: HTTP ${response.status}`;
      }

      const data = await response.json();

      if (data.error) {
        return `Error: ${data.error}`;
      }

      // Return a clean summary string the agent can work with
      const summary = {
        date_range: `${start} to ${end}`,
        total_transactions: data.count,
        transactions: data.transactions.map((t) => ({
          date: t.date ? t.date.split("T")[0] : t.date,
          amount: t.amount,
          description: t.description,
          account: t.account,
          category: t.category || "Uncategorized",
          is_transfer: t.is_transfer,
        })),
      };

      return JSON.stringify(summary, null, 2);
    } catch (error) {
      return `Failed to fetch transactions: ${error.message}`;
    }
  },
};
