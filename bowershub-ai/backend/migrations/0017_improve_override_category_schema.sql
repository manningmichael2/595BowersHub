-- Update override-category skill schema to be more descriptive and provide hints for the AI.
UPDATE public.bh_skills
SET 
    param_schema = '{
        "type": "object",
        "properties": {
            "transaction_id": {
                "type": "string",
                "description": "Specific transaction ID to update (e.g. TRN-...). Required if merchant pattern is not provided."
            },
            "description_pattern": {
                "type": "string",
                "description": "Merchant name or part of the description to match (e.g. \"Amazon\", \"Costco\"). Required if transaction_id is not provided."
            },
            "category_name": {
                "type": "string",
                "description": "The new category name (e.g. \"Shopping\", \"Food_Groceries\")."
            },
            "confirm_retroactive": {
                "type": "boolean",
                "description": "Set to true if user wants to update ALL past matching transactions immediately."
            },
            "create_if_missing": {
                "type": "boolean",
                "description": "Set to true only if the user explicitly asks to create a brand new category."
            }
        },
        "required": ["category_name"]
    }'::jsonb
WHERE name = 'override-category';
