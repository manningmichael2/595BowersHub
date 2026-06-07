module.exports.runtime = {
  handler: async function ({ start_date, end_date }) {
    try {
      const now = new Date();
      const defaultStart = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000)
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

      const transactions = data.transactions || [];

      // Exclude transfers from spending analysis
      const spending = transactions.filter(
        (t) => t.amount < 0 && !t.is_transfer
      );
      const income = transactions.filter(
        (t) => t.amount > 0 && !t.is_transfer
      );

      // Group spending by category
      const byCategory = {};
      for (const t of spending) {
        const cat = t.category || "Uncategorized";
        if (!byCategory[cat]) {
          byCategory[cat] = { total: 0, count: 0 };
        }
        byCategory[cat].total += t.amount;
        byCategory[cat].count += 1;
      }

      // Sort categories by total spending (most negative first)
      const sortedCategories = Object.entries(byCategory)
        .sort((a, b) => a[1].total - b[1].total)
        .map(([name, data]) => ({
          category: name,
          total: Math.round(data.total * 100) / 100,
          transaction_count: data.count,
        }));

      // Group spending by account
      const byAccount = {};
      for (const t of spending) {
        const acct = t.account || "Unknown";
        if (!byAccount[acct]) {
          byAccount[acct] = { total: 0, count: 0 };
        }
        byAccount[acct].total += t.amount;
        byAccount[acct].count += 1;
      }

      const sortedAccounts = Object.entries(byAccount)
        .sort((a, b) => a[1].total - b[1].total)
        .map(([name, data]) => ({
          account: name,
          total: Math.round(data.total * 100) / 100,
          transaction_count: data.count,
        }));

      const totalSpending = spending.reduce((sum, t) => sum + t.amount, 0);
      const totalIncome = income.reduce((sum, t) => sum + t.amount, 0);

      // Top 10 largest purchases
      const topPurchases = spending
        .sort((a, b) => a.amount - b.amount)
        .slice(0, 10)
        .map((t) => ({
          date: t.date ? t.date.split("T")[0] : t.date,
          amount: t.amount,
          description: t.description,
          account: t.account,
          category: t.category || "Uncategorized",
        }));

      const summary = {
        date_range: `${start} to ${end}`,
        total_spending: Math.round(totalSpending * 100) / 100,
        total_income: Math.round(totalIncome * 100) / 100,
        net: Math.round((totalIncome + totalSpending) * 100) / 100,
        transaction_count: spending.length,
        by_category: sortedCategories,
        by_account: sortedAccounts,
        top_10_purchases: topPurchases,
      };

      return JSON.stringify(summary, null, 2);
    } catch (error) {
      return `Failed to generate spending summary: ${error.message}`;
    }
  },
};
