module.exports.runtime = {
  handler: async function ({
    transaction_id,
    category_name,
    create_if_missing,
    confirm_retroactive,
  }) {
    try {
      if (!transaction_id || transaction_id.trim().length === 0) {
        return "Missing transaction_id. Get one from get-transactions, filter-transactions, or ask-db first.";
      }
      if (!category_name || category_name.trim().length === 0) {
        return "Missing category_name. Provide the new category to assign.";
      }

      const toBool = (v) =>
        v === true || v === "true" || v === "yes" || v === "1";

      const payload = {
        transaction_id: transaction_id.trim(),
        category_name: category_name.trim(),
        create_if_missing: toBool(create_if_missing),
        confirm_retroactive: toBool(confirm_retroactive),
      };

      const url = "http://100.106.180.101:5678/webhook/update-category";
      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        return `Error from category update service: HTTP ${response.status}`;
      }

      const data = await response.json();
      return JSON.stringify(data, null, 2);
    } catch (error) {
      return `Failed to update category: ${error.message}`;
    }
  },
};
