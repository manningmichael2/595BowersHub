module.exports.runtime = {
  handler: async function ({
    account,
    category,
    description,
    min_amount,
    max_amount,
    house_tag,
    start_date,
    end_date,
  }) {
    try {
      const params = new URLSearchParams();

      if (account) params.append("account", account);
      if (category) params.append("category", category);
      if (description) params.append("description", description);
      if (min_amount) params.append("min_amount", min_amount);
      if (max_amount) params.append("max_amount", max_amount);
      if (house_tag) params.append("house_tag", house_tag);
      if (start_date) params.append("start", start_date);
      if (end_date) params.append("end", end_date);

      const url = `http://100.106.180.101:5678/webhook/filter?${params.toString()}`;
      const response = await fetch(url);

      if (!response.ok) {
        return `Error fetching filtered transactions: HTTP ${response.status}`;
      }

      const data = await response.json();

      // Handle "no items" response from n8n
      if (data.code === 0 && data.message) {
        return JSON.stringify({
          filters_applied: Object.fromEntries(params),
          total_transactions: 0,
          transactions: [],
          note: "No transactions matched the given filters.",
        });
      }

      if (data.error) {
        return `Error: ${data.error}`;
      }

      const summary = {
        filters_applied: data.filters_applied || Object.fromEntries(params),
        total_transactions: data.count,
        transactions: data.transactions.map((t) => ({
          date: t.date ? t.date.split("T")[0] : t.date,
          amount: t.amount,
          description: t.description,
          account: t.account,
          category: t.category || "Uncategorized",
          is_transfer: t.is_transfer,
          house_tag: t.house_tag,
        })),
      };

      return JSON.stringify(summary, null, 2);
    } catch (error) {
      return `Failed to fetch filtered transactions: ${error.message}`;
    }
  },
};
