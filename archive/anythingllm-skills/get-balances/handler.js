module.exports.runtime = {
  handler: async function () {
    try {
      const url = "http://100.106.180.101:5678/webhook/balances";
      const response = await fetch(url);

      if (!response.ok) {
        return `Error fetching balances: HTTP ${response.status}`;
      }

      const data = await response.json();

      if (data.error) {
        return `Error: ${data.error}`;
      }

      // Calculate totals
      const accounts = data.accounts || [];
      const assets = accounts.filter((a) => a.balance > 0);
      const liabilities = accounts.filter((a) => a.balance < 0);
      const totalAssets = assets.reduce((sum, a) => sum + a.balance, 0);
      const totalLiabilities = liabilities.reduce(
        (sum, a) => sum + a.balance,
        0
      );
      const netWorth = totalAssets + totalLiabilities;

      const summary = {
        retrieved_at: data.retrieved_at,
        total_accounts: accounts.length,
        total_assets: Math.round(totalAssets * 100) / 100,
        total_liabilities: Math.round(totalLiabilities * 100) / 100,
        net_worth: Math.round(netWorth * 100) / 100,
        accounts: accounts.map((a) => ({
          name: a.name,
          org: a.org,
          balance: a.balance,
          as_of: a.as_of ? a.as_of.split("T")[0] : a.as_of,
        })),
      };

      return JSON.stringify(summary, null, 2);
    } catch (error) {
      return `Failed to fetch balances: ${error.message}`;
    }
  },
};
