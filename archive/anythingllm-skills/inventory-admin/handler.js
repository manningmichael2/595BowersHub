module.exports.runtime = {
  handler: async function ({ action, table, id, fields, merge_into_id, column_name, column_type }) {
    try {
      const a = (action || "").trim().toLowerCase();
      const t = (table || "").trim().toLowerCase();
      const recordId = Number(id) || 0;
      const mergeIntoId = Number(merge_into_id) || 0;
      const colName = (column_name || "").trim().toLowerCase().replace(/\s+/g, '_');
      const colType = (column_type || "text").trim().toLowerCase();

      if (!a) return "Error: `action` is required. One of: update, archive, unarchive, delete, merge, add_column, list_columns.";
      if (!t) return "Error: `table` is required. One of: tools, saw_blades, wood, albums, manuals, router_bits.";

      // Parse fields if passed as JSON string
      let f = fields;
      if (typeof f === "string") {
        try { f = JSON.parse(f); }
        catch (e) { return `Error: fields was a string and not valid JSON (${e.message}).`; }
      }

      const body = { action: a, table: t };
      if (recordId) body.id = recordId;
      if (f && typeof f === "object" && Object.keys(f).length > 0) body.fields = f;
      if (mergeIntoId) body.merge_into_id = mergeIntoId;
      if (colName) body.column_name = colName;
      if (colType) body.column_type = colType;

      const url = "http://100.106.180.101:5678/webhook/inventory-admin";
      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      if (!response.ok) {
        const txt = await response.text().catch(() => "");
        return `Error from inventory-admin: HTTP ${response.status} ${txt.slice(0, 300)}`;
      }

      const data = await response.json();
      return JSON.stringify(data, null, 2);
    } catch (error) {
      return `Inventory admin failed: ${error.message}`;
    }
  },
};
