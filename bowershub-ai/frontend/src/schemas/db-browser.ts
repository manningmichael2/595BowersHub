import { z } from 'zod'

export const TableInfoSchema = z
  .object({
    name: z.string(),
    column_count: z.number(),
    row_count: z.number(),
    has_link_table: z.boolean(),
  })
  .passthrough()

export const SchemaInfoSchema = z
  .object({
    name: z.string(),
    tables: z.array(TableInfoSchema),
  })
  .passthrough()

export const ColumnMetaSchema = z
  .object({
    column_name: z.string(),
    data_type: z.string(),
    is_nullable: z.string(),
    column_default: z.string().nullable(),
    is_pk: z.boolean(),
    fk_schema: z.string().optional(),
    fk_table: z.string().optional(),
    fk_column: z.string().optional(),
  })
  .passthrough()

export const FieldHintSchema = z
  .object({
    column_name: z.string(),
    input_type: z.enum([
      'text',
      'number',
      'fraction',
      'select',
      'url',
      'date',
      'boolean',
      'textarea',
    ]),
    options: z.array(z.string()).nullable(),
    prefix: z.string().nullable(),
    suffix: z.string().nullable(),
    min_val: z.number().nullable(),
    max_val: z.number().nullable(),
    step: z.number().nullable(),
    placeholder: z.string().nullable(),
  })
  .passthrough()

export const FilterConditionSchema = z
  .object({
    column: z.string(),
    operator: z.enum(['eq', 'neq', 'contains', 'gt', 'lt', 'is_null', 'has_value']),
    value: z.string(),
  })
  .passthrough()

export const LayoutConfigSchema = z
  .object({
    list: z.object({
      columns: z.array(
        z.object({
          name: z.string(),
          visible: z.boolean(),
          position: z.number(),
        })
      ),
    }),
    detail: z.object({
      fields: z.array(
        z.object({
          name: z.string(),
          visible: z.boolean(),
          position: z.number(),
          width: z.union([z.literal(25), z.literal(33), z.literal(50), z.literal(100)]),
          height: z.enum(['small', 'medium', 'large']),
        })
      ),
    }),
  })
  .passthrough()

export const SavedViewSchema = z
  .object({
    id: z.string(),
    name: z.string(),
    schema_name: z.string(),
    table_name: z.string(),
    config: z.object({
      filters: z.array(FilterConditionSchema),
      sortColumn: z.string().nullable(),
      sortDirection: z.enum(['asc', 'desc']).nullable(),
      columns: z.array(
        z.object({
          name: z.string(),
          visible: z.boolean(),
          position: z.number(),
        })
      ),
    }),
    created_at: z.string(),
    updated_at: z.string(),
  })
  .passthrough()

export const UndoEntrySchema = z
  .object({
    id: z.number(),
    session_id: z.string(),
    schema_name: z.string(),
    table_name: z.string(),
    row_id: z.string(),
    operation_type: z.enum(['update', 'insert', 'delete', 'bulk_update']),
    previous_values: z.record(z.string(), z.any()).nullable(),
    new_values: z.record(z.string(), z.any()).nullable(),
    is_undone: z.boolean(),
  })
  .passthrough()

export const RelationGroupSchema = z
  .object({
    schema: z.string(),
    table: z.string(),
    fk_column: z.string(),
    total_count: z.number(),
    rows: z.array(z.record(z.string(), z.any())),
  })
  .passthrough()

export const ImportResultSchema = z
  .object({
    total_rows: z.number(),
    imported_rows: z.number(),
    failed_rows: z.array(
      z.object({
        line_number: z.number(),
        error: z.string(),
      })
    ),
  })
  .passthrough()

export const RowsResponseSchema = z
  .object({
    rows: z.array(z.record(z.string(), z.any())),
    total_rows: z.number(),
    filtered_rows: z.number(),
  })
  .passthrough()

export type SchemaInfo = z.infer<typeof SchemaInfoSchema>
export type TableInfo = z.infer<typeof TableInfoSchema>
export type ColumnMeta = z.infer<typeof ColumnMetaSchema>
export type FieldHint = z.infer<typeof FieldHintSchema>
export type FilterCondition = z.infer<typeof FilterConditionSchema>
export type LayoutConfig = z.infer<typeof LayoutConfigSchema>
export type SavedView = z.infer<typeof SavedViewSchema>
export type UndoEntry = z.infer<typeof UndoEntrySchema>
export type RelationGroup = z.infer<typeof RelationGroupSchema>
export type ImportResult = z.infer<typeof ImportResultSchema>
