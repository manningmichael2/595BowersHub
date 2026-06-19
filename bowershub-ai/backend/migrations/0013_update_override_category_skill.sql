-- Update override-category skill to support merchant patterns and optional transaction IDs.
UPDATE public.bh_skills
SET 
    description = 'Re-categorize a specific transaction or set a general merchant rule (e.g. "Costco is groceries").',
    param_schema = '{
        "type": "object",
        "properties": {
            "transaction_id": {
                "type": "string",
                "description": "Optional: Specific transaction ID to update."
            },
            "description_pattern": {
                "type": "string",
                "description": "Optional: Merchant name or description pattern (e.g. \"Costco\", \"Netflix\")."
            },
            "category_name": {
                "type": "string",
                "description": "The new category name (e.g. \"Food_Groceries\")."
            },
            "confirm_retroactive": {
                "type": "boolean",
                "description": "If true, apply to all past similar transactions without asking."
            },
            "create_if_missing": {
                "type": "boolean",
                "description": "If true, create the category if it doesn''t exist."
            }
        },
        "required": ["category_name"]
    }'::jsonb
WHERE name = 'override-category';

-- Update remember skill to make topic optional.
UPDATE public.bh_skills
SET 
    param_schema = '{
        "type": "object",
        "required": ["fact"],
        "properties": {
            "fact": {
                "type": "string",
                "description": "The fact to remember"
            },
            "topic": {
                "type": "string",
                "description": "Optional: Topic slug e.g. \"finance/merchants\". Defaults to \"general\"."
            }
        }
    }'::jsonb
WHERE name = 'remember';
