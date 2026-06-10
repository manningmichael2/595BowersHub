/**
 * 595BowersHub DB Admin — Frontend
 * Supports: table browsing, row editing, image upload, drag-to-reorder fields,
 * field visibility toggles, smart default ordering.
 */

const state = {
    schema: null,
    table: null,
    columns: [],
    rows: [],
    total: 0,
    offset: 0,
    limit: 50,
    sort: null,
    direction: 'asc',
    search: '',
    filters: [], // [{col, op, val}]
    pk: [],
    editingRow: null,
    editedFields: {},
    layoutMode: false, // true when user is rearranging fields
};

// --- Layout persistence (localStorage) ---

function layoutKey(suffix = '') {
    return `dbadmin_layout_${state.schema}.${state.table}${suffix}`;
}

function getLayout() {
    try {
        const raw = localStorage.getItem(layoutKey());
        if (raw) return JSON.parse(raw);
    } catch (e) {}
    return null;
}

function saveLayout(layout) {
    localStorage.setItem(layoutKey(), JSON.stringify(layout));
}

// List view layout (separate from detail view)
function getListLayout() {
    try {
        const raw = localStorage.getItem(layoutKey('_list'));
        if (raw) return JSON.parse(raw);
    } catch (e) {}
    return null;
}

function saveListLayout(layout) {
    localStorage.setItem(layoutKey('_list'), JSON.stringify(layout));
}

/**
 * Returns columns in display order with visibility, width, and height info.
 * Layout format: { order: [...], hidden: [...], widths: {col: '50%'}, heights: {col: 'md'} }
 */
function getOrderedColumns() {
    const layout = getLayout();
    const allCols = state.columns.map(c => c.column_name);

    if (!layout) {
        // Smart default: important fields first, auto fields last
        return smartDefaultOrder(state.columns).map(col => ({
            ...col,
            visible: true,
            width: getDefaultWidth(col),
            height: getDefaultHeight(col),
        }));
    }

    const hidden = new Set(layout.hidden || []);
    const widths = layout.widths || {};
    const heights = layout.heights || {};
    const ordered = [];

    // First: columns in saved order
    for (const name of (layout.order || [])) {
        const col = state.columns.find(c => c.column_name === name);
        if (col) {
            ordered.push({
                ...col,
                visible: !hidden.has(name),
                width: widths[name] || getDefaultWidth(col),
                height: heights[name] || getDefaultHeight(col),
            });
        }
    }

    // Then: any new columns not in saved layout (added after layout was saved)
    for (const col of state.columns) {
        if (!ordered.find(c => c.column_name === col.column_name)) {
            ordered.push({
                ...col,
                visible: true,
                width: getDefaultWidth(col),
                height: getDefaultHeight(col),
            });
        }
    }

    return ordered;
}

function getDefaultWidth(col) {
    const isJson = col.data_type === 'jsonb' || col.data_type === 'json';
    if (isJson || col.column_name === 'notes') return '100%';
    if (col.column_name === 'url') return '100%';
    return '50%';
}

function getDefaultHeight(col) {
    const isJson = col.data_type === 'jsonb' || col.data_type === 'json';
    if (isJson || col.column_name === 'notes') return 'lg';
    return 'sm';
}

/**
 * Smart default ordering: PK first, then "important" fields, then others, then auto/system last.
 */
function smartDefaultOrder(columns) {
    const autoFields = ['created_at', 'updated_at', 'archived_at'];
    const pk = new Set(state.pk);

    const pkCols = [];
    const importantCols = [];
    const normalCols = [];
    const autoCols = [];

    for (const col of columns) {
        if (pk.has(col.column_name)) {
            pkCols.push(col);
        } else if (autoFields.includes(col.column_name) ||
                   (col.column_default && col.column_default.includes('nextval'))) {
            autoCols.push(col);
        } else if (['name', 'title', 'brand', 'profile', 'type', 'model'].includes(col.column_name)) {
            importantCols.push(col);
        } else {
            normalCols.push(col);
        }
    }

    return [...pkCols, ...importantCols, ...normalCols, ...autoCols];
}

// --- API helpers ---

async function api(path, options = {}) {
    try {
        const res = await fetch(`/api${path}`, {
            headers: { 'Content-Type': 'application/json' },
            ...options,
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(err.detail || 'API error');
        }
        setConnectionStatus(true);
        return res.json();
    } catch (e) {
        if (e.message === 'Failed to fetch' || e.name === 'TypeError') {
            setConnectionStatus(false);
            throw new Error('Connection lost — is the server running?');
        }
        throw e;
    }
}

function setConnectionStatus(ok) {
    const el = document.getElementById('conn-status');
    if (!el) return;
    if (ok) {
        el.style.display = 'none';
    } else {
        el.style.display = 'block';
    }
}

// --- Toast ---

function toast(msg, type = 'success') {
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 4000);
}

function friendlyError(e, context) {
    let msg = e.message || 'Something went wrong';
    // Make common errors more readable
    if (msg.includes('violates not-null')) {
        const col = msg.match(/column "(\w+)"/)?.[1] || 'a required field';
        msg = `Missing required field: ${col}`;
    } else if (msg.includes('violates unique')) {
        msg = 'A record with that value already exists (duplicate)';
    } else if (msg.includes('violates foreign key')) {
        msg = 'Cannot delete — other records reference this one';
    } else if (msg.includes('invalid input syntax')) {
        const type = msg.match(/type (\w+)/)?.[1] || 'expected';
        msg = `Invalid value — expected a ${type}`;
    } else if (msg.includes('Connection lost')) {
        msg = 'Cannot reach the server. Is it running?';
    } else if (msg.includes('numeric field overflow')) {
        msg = 'Number is too large for this field';
    }
    toast(`${context}: ${msg}`, 'error');
}

// --- Sidebar ---

async function loadSidebar() {
    const schemas = await api('/schemas');
    const nav = document.getElementById('schema-nav');
    nav.innerHTML = '';

    // Load all tables in parallel
    const tablesBySchema = await Promise.all(
        schemas.map(async (schema) => ({
            schema,
            tables: await api(`/tables/${schema}`),
        }))
    );

    for (const { schema, tables } of tablesBySchema) {
        if (tables.length === 0) continue;

        const group = document.createElement('div');
        group.className = 'schema-group';

        const title = document.createElement('div');
        title.className = 'schema-name';
        title.textContent = schema;
        group.appendChild(title);

        const list = document.createElement('ul');
        list.className = 'table-list';

        for (const t of tables) {
            const li = document.createElement('li');
            li.textContent = t;
            li.dataset.schema = schema;
            li.dataset.table = t;
            li.addEventListener('click', () => selectTable(schema, t));
            li.addEventListener('contextmenu', (e) => {
                e.preventDefault();
                openTableContextMenu(e, schema, t);
            });
            list.appendChild(li);
        }

        group.appendChild(list);
        nav.appendChild(group);
    }
}

// --- Table selection ---

async function selectTable(schema, table) {
    state.schema = schema;
    state.table = table;
    state.offset = 0;
    state.sort = null;
    state.direction = 'asc';
    state.search = '';
    state.filters = [];
    state.editingRow = null;
    state.layoutMode = false;

    document.querySelectorAll('.table-list li').forEach(li => {
        li.classList.toggle('active', li.dataset.schema === schema && li.dataset.table === table);
    });

    const [columns, pkCols] = await Promise.all([
        api(`/columns/${schema}/${table}`),
        api(`/pk/${schema}/${table}`),
    ]);
    state.columns = columns;
    state.pk = pkCols;

    document.getElementById('empty-state').style.display = 'none';
    document.getElementById('table-view').style.display = 'block';
    document.getElementById('row-detail').classList.remove('active');
    document.getElementById('table-title').textContent = `${schema}.${table}`;
    document.getElementById('search-input').value = '';

    await loadRows();
}

// --- Load rows ---

async function loadRows() {
    const params = new URLSearchParams({
        limit: state.limit,
        offset: state.offset,
    });
    if (state.sort) {
        params.set('sort', state.sort);
        params.set('direction', state.direction);
    }
    if (state.search) {
        params.set('search', state.search);
    }
    if (state.filters.length > 0) {
        params.set('filters', JSON.stringify(state.filters));
    }

    const data = await api(`/rows/${state.schema}/${state.table}?${params}`);
    state.rows = data.rows;
    state.total = data.total;

    // Load thumbnails for image-supporting tables
    state.thumbnails = {};
    if (IMAGE_TABLES.includes(`${state.schema}.${state.table}`)) {
        try {
            state.thumbnails = await api(`/thumbnails/${state.schema}/${state.table}`);
        } catch (e) { /* non-critical */ }
    }

    document.getElementById('row-count').textContent = `${data.total} rows`;
    renderTable();
    renderPagination();
    renderFilters();
}

// --- Render table (list view) ---

function getListColumns() {
    const layout = getListLayout();
    const autoFields = ['created_at', 'updated_at', 'archived_at'];

    if (layout) {
        const hidden = new Set(layout.hidden || []);
        const ordered = [];
        for (const name of (layout.order || [])) {
            const col = state.columns.find(c => c.column_name === name);
            if (col) ordered.push({ ...col, visible: !hidden.has(name) });
        }
        // Add any new columns not in layout
        for (const col of state.columns) {
            if (!ordered.find(c => c.column_name === col.column_name)) {
                ordered.push({ ...col, visible: !autoFields.includes(col.column_name) });
            }
        }
        return ordered;
    }

    // Default: show all except auto fields, cap at 10
    return state.columns.map(col => ({
        ...col,
        visible: !autoFields.includes(col.column_name),
    }));
}

function renderTable() {
    const thead = document.getElementById('table-head');
    const tbody = document.getElementById('table-body');

    const allListCols = getListColumns();
    const visibleCols = allListCols.filter(c => c.visible).slice(0, 12);
    const hasThumbs = Object.keys(state.thumbnails || {}).length > 0 || IMAGE_TABLES.includes(`${state.schema}.${state.table}`);

    let headerHtml = '<tr>';
    headerHtml += '<th style="width:40px">#</th>';
    if (hasThumbs) headerHtml += '<th style="width:44px"></th>';
    for (const col of visibleCols) {
        let cls = '';
        if (state.sort === col.column_name) {
            cls = state.direction === 'asc' ? 'sorted-asc' : 'sorted-desc';
        }
        headerHtml += `<th class="${cls}" data-col="${col.column_name}">${col.column_name}</th>`;
    }
    headerHtml += '</tr>';
    thead.innerHTML = headerHtml;

    thead.querySelectorAll('th[data-col]').forEach(th => {
        th.addEventListener('click', () => {
            const col = th.dataset.col;
            if (state.sort === col) {
                state.direction = state.direction === 'asc' ? 'desc' : 'asc';
            } else {
                state.sort = col;
                state.direction = 'asc';
            }
            state.offset = 0;
            loadRows();
        });
    });

    let bodyHtml = '';
    for (let i = 0; i < state.rows.length; i++) {
        const row = state.rows[i];
        const isArchived = row.archived_at ? 'archived' : '';
        bodyHtml += `<tr class="${isArchived}" data-idx="${i}" style="cursor:pointer">`;
        bodyHtml += `<td>${state.offset + i + 1}</td>`;
        if (hasThumbs) {
            const pkCol = state.pk[0] || 'id';
            const thumbUrl = (state.thumbnails || {})[String(row[pkCol])];
            if (thumbUrl) {
                bodyHtml += `<td><img src="${thumbUrl}" class="row-thumb" loading="lazy" /></td>`;
            } else {
                bodyHtml += `<td></td>`;
            }
        }
        for (const col of visibleCols) {
            const val = row[col.column_name];
            const display = formatCell(val, col);
            bodyHtml += `<td title="${escapeHtml(String(val ?? ''))}">${display}</td>`;
        }
        bodyHtml += '</tr>';
    }

    if (state.rows.length === 0) {
        const colSpan = visibleCols.length + 1 + (hasThumbs ? 1 : 0);
        bodyHtml = `<tr><td colspan="${colSpan}" style="text-align:center; padding:2rem; color:var(--text-muted)">No rows found</td></tr>`;
    }

    tbody.innerHTML = bodyHtml;

    tbody.querySelectorAll('tr[data-idx]').forEach(tr => {
        tr.addEventListener('click', (e) => {
            // If clicking a thumbnail, open lightbox instead of row detail
            if (e.target.classList.contains('row-thumb')) {
                e.stopPropagation();
                openLightbox(e.target.src);
                return;
            }
            const idx = parseInt(tr.dataset.idx);
            openRowDetail(state.rows[idx]);
        });
    });
}

// --- List column picker modal ---

function openColumnPicker() {
    const overlay = document.getElementById('col-picker-overlay');
    overlay.classList.add('active');
    renderColumnPicker();
}

function closeColumnPicker() {
    document.getElementById('col-picker-overlay').classList.remove('active');
}

function renderColumnPicker() {
    const container = document.getElementById('col-picker-list');
    container.innerHTML = '';

    const allListCols = getListColumns();

    for (const col of allListCols) {
        const row = document.createElement('div');
        row.className = 'col-picker-row';
        row.draggable = true;
        row.dataset.col = col.column_name;

        row.innerHTML = `
            <span class="drag-handle">⠿</span>
            <label style="flex:1; cursor:pointer; display:flex; align-items:center; gap:0.4rem;">
                <input type="checkbox" ${col.visible ? 'checked' : ''} style="width:auto;" />
                ${col.column_name}
            </label>
            <span style="font-size:0.7rem; color:var(--text-muted);">${col.data_type}</span>
        `;

        // Checkbox toggle
        row.querySelector('input[type="checkbox"]').addEventListener('change', (e) => {
            saveListColumnVisibility();
        });

        container.appendChild(row);
    }

    // Drag and drop for reordering
    setupListColumnDrag(container);
}

function setupListColumnDrag(container) {
    let dragEl = null;
    const items = container.querySelectorAll('.col-picker-row');

    items.forEach(item => {
        item.addEventListener('dragstart', () => {
            dragEl = item;
            item.classList.add('dragging');
        });
        item.addEventListener('dragend', () => {
            item.classList.remove('dragging');
            dragEl = null;
            container.querySelectorAll('.drag-over').forEach(el => el.classList.remove('drag-over'));
            saveListColumnOrder();
        });
        item.addEventListener('dragover', (e) => {
            e.preventDefault();
            if (item !== dragEl) item.classList.add('drag-over');
        });
        item.addEventListener('dragleave', () => item.classList.remove('drag-over'));
        item.addEventListener('drop', (e) => {
            e.preventDefault();
            item.classList.remove('drag-over');
            if (dragEl && dragEl !== item) {
                const all = [...container.querySelectorAll('.col-picker-row')];
                const dragIdx = all.indexOf(dragEl);
                const dropIdx = all.indexOf(item);
                if (dragIdx < dropIdx) {
                    container.insertBefore(dragEl, item.nextSibling);
                } else {
                    container.insertBefore(dragEl, item);
                }
            }
        });
    });
}

function saveListColumnOrder() {
    const container = document.getElementById('col-picker-list');
    const rows = container.querySelectorAll('.col-picker-row');
    const order = [...rows].map(r => r.dataset.col);
    const hidden = [...rows]
        .filter(r => !r.querySelector('input[type="checkbox"]').checked)
        .map(r => r.dataset.col);

    saveListLayout({ order, hidden });
    renderTable();
}

function saveListColumnVisibility() {
    // Same as saveListColumnOrder — reads current state from DOM
    saveListColumnOrder();
}

function resetListLayout() {
    localStorage.removeItem(layoutKey('_list'));
    renderTable();
    renderColumnPicker();
    toast('List columns reset to defaults');
}

function formatCell(val, col) {
    if (val === null || val === undefined) return '<span style="color:var(--text-muted)">null</span>';
    if (typeof val === 'object') return `<span style="color:var(--warning)">{json}</span>`;

    // Show fractions for measurement columns in list view
    const fractionCols = ['radius_in', 'shank_size_in', 'cutting_diameter_in', 'cutting_length_in', 'diameter_in', 'kerf_in'];
    if (fractionCols.includes(col.column_name) && val !== null) {
        const frac = decimalToFraction(val);
        if (frac) return escapeHtml(frac) + '"';
    }

    const str = String(val);
    if (str.length > 50) return escapeHtml(str.slice(0, 50)) + '…';
    return escapeHtml(str);
}

function escapeHtml(str) {
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// --- Pagination ---

function renderPagination() {
    const el = document.getElementById('pagination');
    const totalPages = Math.ceil(state.total / state.limit);
    const currentPage = Math.floor(state.offset / state.limit) + 1;

    if (totalPages <= 1) {
        el.innerHTML = `<span>Showing all ${state.total} rows</span>`;
        return;
    }

    el.innerHTML = `
        <button class="btn" id="pg-prev" ${currentPage <= 1 ? 'disabled' : ''}>← Prev</button>
        <span>Page ${currentPage} of ${totalPages}</span>
        <button class="btn" id="pg-next" ${currentPage >= totalPages ? 'disabled' : ''}>Next →</button>
    `;

    document.getElementById('pg-prev')?.addEventListener('click', () => {
        state.offset = Math.max(0, state.offset - state.limit);
        loadRows();
    });
    document.getElementById('pg-next')?.addEventListener('click', () => {
        state.offset += state.limit;
        loadRows();
    });
}

// --- Row detail/edit with drag-and-drop reordering ---

const IMAGE_TABLES = [
    'inventory.tools', 'inventory.router_bits', 'inventory.saw_blades',
    'inventory.wood', 'inventory.albums', 'inventory.manuals',
    'house.rooms', 'cook.recipes'
];

function supportsImages() {
    return IMAGE_TABLES.includes(`${state.schema}.${state.table}`);
}

function openRowDetail(row) {
    state.editingRow = row;
    state.editedFields = {};
    state.layoutMode = false;

    document.getElementById('table-view').style.display = 'none';
    document.getElementById('row-detail').classList.add('active');

    const pkDisplay = state.pk.map(k => `${k}=${row[k]}`).join(', ');
    document.getElementById('detail-title').textContent = `Edit: ${pkDisplay}`;

    const hasArchive = state.columns.some(c => c.column_name === 'archived_at');
    document.getElementById('btn-archive').style.display = hasArchive ? '' : 'none';

    // Show/hide images section
    const imagesSection = document.getElementById('images-section');
    if (supportsImages()) {
        imagesSection.style.display = 'block';
        loadRowImages();
    } else {
        imagesSection.style.display = 'none';
    }

    // Update layout button state
    document.getElementById('btn-layout').textContent = '⚙ Layout';
    document.getElementById('btn-layout').classList.remove('btn-primary');

    renderDetailFields();
}

function renderDetailFields() {
    const grid = document.getElementById('detail-grid');
    grid.innerHTML = '';
    grid.classList.toggle('layout-mode', state.layoutMode);

    const orderedCols = getOrderedColumns();

    for (const col of orderedCols) {
        // In normal mode, skip hidden fields
        if (!state.layoutMode && !col.visible) continue;

        const field = document.createElement('div');
        field.className = 'detail-field';
        field.dataset.col = col.column_name;

        if (state.layoutMode) {
            field.classList.add('draggable');
            field.draggable = true;
            if (!col.visible) field.classList.add('field-hidden');
        }

        // Apply width class
        const fieldWidth = col.width || '50%';
        const widthClass = { '25%': 'w-25', '33%': 'w-33', '50%': 'w-50', '100%': 'w-100' }[fieldWidth] || 'w-50';
        field.classList.add(widthClass);

        // Apply height class
        const fieldHeight = col.height || 'sm';
        const heightClass = { 'sm': 'h-sm', 'md': 'h-md', 'lg': 'h-lg' }[fieldHeight] || 'h-sm';
        field.classList.add(heightClass);

        const isBool = col.data_type === 'boolean';
        const isPk = state.pk.includes(col.column_name);
        const isAuto = ['created_at', 'updated_at', 'archived_at'].includes(col.column_name) ||
                       (col.column_default && col.column_default.includes('nextval'));

        // Label row with visibility toggle in layout mode
        const labelRow = document.createElement('div');
        labelRow.className = 'field-label-row';

        if (state.layoutMode) {
            const dragHandle = document.createElement('span');
            dragHandle.className = 'drag-handle';
            dragHandle.textContent = '⠿';
            labelRow.appendChild(dragHandle);
        }

        const label = document.createElement('label');
        label.textContent = col.column_name + (isPk ? ' (PK)' : '') + (isAuto ? ' (auto)' : '');
        labelRow.appendChild(label);

        if (state.layoutMode) {
            const toggle = document.createElement('button');
            toggle.className = `visibility-toggle ${col.visible ? 'visible' : 'hidden-field'}`;
            toggle.textContent = col.visible ? '👁' : '👁‍🗨';
            toggle.title = col.visible ? 'Click to hide' : 'Click to show';
            toggle.addEventListener('click', (e) => {
                e.stopPropagation();
                toggleFieldVisibility(col.column_name);
            });
            labelRow.appendChild(toggle);
        }

        field.appendChild(labelRow);

        // In layout mode, show size controls
        if (state.layoutMode) {
            const sizeRow = document.createElement('div');
            sizeRow.className = 'field-size-row';

            // Width selector
            const widthGroup = document.createElement('div');
            widthGroup.className = 'size-group';
            widthGroup.innerHTML = '<span class="size-label">W:</span>';
            const widthOptions = ['25%', '33%', '50%', '100%'];
            for (const w of widthOptions) {
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'size-btn' + (fieldWidth === w ? ' active' : '');
                btn.textContent = w;
                btn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    setFieldWidth(col.column_name, w);
                });
                widthGroup.appendChild(btn);
            }
            sizeRow.appendChild(widthGroup);

            // Height selector
            const heightGroup = document.createElement('div');
            heightGroup.className = 'size-group';
            heightGroup.innerHTML = '<span class="size-label">H:</span>';
            const heightOptions = [
                { label: 'S', value: 'sm' },
                { label: 'M', value: 'md' },
                { label: 'L', value: 'lg' },
            ];
            for (const h of heightOptions) {
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'size-btn' + (fieldHeight === h.value ? ' active' : '');
                btn.textContent = h.label;
                btn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    setFieldHeight(col.column_name, h.value);
                });
                heightGroup.appendChild(btn);
            }
            sizeRow.appendChild(heightGroup);

            field.appendChild(sizeRow);

            const preview = document.createElement('div');
            preview.className = 'value';
            preview.style.fontSize = '0.75rem';
            preview.style.color = 'var(--text-muted)';
            preview.textContent = col.data_type;
            field.appendChild(preview);
        } else {
            const val = state.editingRow[col.column_name];
            const displayVal = val === null ? '' : (typeof val === 'object' ? JSON.stringify(val, null, 2) : String(val));

            if (isPk || isAuto) {
                const div = document.createElement('div');
                div.className = 'value';
                div.textContent = displayVal || '(null)';
                div.style.color = val === null ? 'var(--text-muted)' : '';
                field.appendChild(div);
            } else if (isBool) {
                // Boolean: render as a toggle
                const wrapper = document.createElement('div');
                wrapper.className = 'bool-toggle';

                const options = [
                    { label: 'Yes', value: true },
                    { label: 'No', value: false },
                    { label: '—', value: null },
                ];

                for (const opt of options) {
                    const btn = document.createElement('button');
                    btn.type = 'button';
                    btn.className = 'bool-btn';
                    btn.textContent = opt.label;
                    if (val === opt.value) btn.classList.add('active');
                    btn.addEventListener('click', () => {
                        wrapper.querySelectorAll('.bool-btn').forEach(b => b.classList.remove('active'));
                        btn.classList.add('active');
                        const original = state.editingRow[col.column_name];
                        if (opt.value !== original) {
                            state.editedFields[col.column_name] = opt.value;
                            wrapper.style.borderColor = 'var(--warning)';
                        } else {
                            delete state.editedFields[col.column_name];
                            wrapper.style.borderColor = '';
                        }
                    });
                    wrapper.appendChild(btn);
                }

                field.appendChild(wrapper);
            } else {
                // Smart field rendering based on column name/type
                const fieldEl = createSmartInput(col, val, displayVal, fieldHeight);
                field.appendChild(fieldEl);
            }
        }

        grid.appendChild(field);
    }

    // Set up drag-and-drop in layout mode
    if (state.layoutMode) {
        setupDragAndDrop(grid);
    }
}

// --- Smart field input factory ---

/**
 * Field hints: maps column names or patterns to input configurations.
 * This is what makes the form user-friendly without per-table code.
 */
const FIELD_HINTS = {
    // Angle fields: 0-360 with degree symbol
    angle_deg: { type: 'number', min: 0, max: 360, step: 0.5, suffix: '°', placeholder: '0-360' },

    // Measurement fields: fraction display with inch suffix
    radius_in: { type: 'fraction', suffix: '"', placeholder: 'e.g. 3/8 or 0.375' },
    shank_size_in: { type: 'fraction', suffix: '"', placeholder: 'e.g. 1/2 or 0.5' },
    cutting_diameter_in: { type: 'fraction', suffix: '"', placeholder: 'e.g. 1-1/2 or 1.5' },
    cutting_length_in: { type: 'fraction', suffix: '"', placeholder: 'e.g. 1-3/8 or 1.375' },
    diameter_in: { type: 'fraction', suffix: '"', placeholder: 'e.g. 10 or 7-1/4' },
    kerf_in: { type: 'fraction', suffix: '"', placeholder: 'e.g. 1/8 or 0.125' },
    size_bytes: { type: 'number', min: 0, step: 1, suffix: 'B' },

    // Currency fields
    purchase_price: { type: 'number', min: 0, step: 0.01, prefix: '$', placeholder: '0.00' },
    current_value_estimate: { type: 'number', min: 0, step: 0.01, prefix: '$', placeholder: '0.00' },
    balance: { type: 'number', step: 0.01, prefix: '$' },
    amount: { type: 'number', step: 0.01, prefix: '$' },

    // Integer fields
    teeth: { type: 'number', min: 0, step: 1, placeholder: 'count' },
    servings: { type: 'number', min: 0, step: 1 },
    servings_made: { type: 'number', min: 0, step: 1 },
    calories_each: { type: 'number', min: 0, step: 1, suffix: 'cal' },
    year: { type: 'number', min: 1900, max: 2100, step: 1 },
    floor: { type: 'number', min: -2, max: 10, step: 1 },
    rating: { type: 'number', min: 1, max: 5, step: 1, suffix: '★' },
    times_reinforced: { type: 'number', min: 0, step: 1 },
    times_used: { type: 'number', min: 0, step: 1 },

    // Dropdown/select fields
    condition: { type: 'select', options: ['new', 'excellent', 'good', 'fair', 'worn', 'damaged', 'broken'] },
    type: { type: 'select', options: ['saw', 'drill', 'chisel', 'plane', 'router', 'router lift', 'sander', 'clamp', 'jig', 'measuring', 'hand tool', 'power tool', 'other'] },
    unit: { type: 'select', options: ['board', 'bf', 'lf', 'piece', 'sheet', 'sqft'] },
    doc_type: { type: 'select', options: ['manual', 'spec_sheet', 'warranty', 'quick_start', 'parts_list', 'other'] },
    source: { type: 'select', options: ['simplefin', 'email', 'manual'] },
    domain: { type: 'select', options: ['receipt', 'tool', 'saw_blade', 'wood', 'album', 'manual', 'house_room', 'cook_recipe', 'router_bit', 'other'] },
    file_role: { type: 'select', options: ['source_page', 'finished_dish', 'in_progress', 'reference', 'other'] },

    // URL fields
    url: { type: 'url' },

    // Date fields
    acquired_at: { type: 'date' },
    cooked_at: { type: 'date' },
    last_played_at: { type: 'date' },
    value_estimated_at: { type: 'date' },
};

// Load saved field hints from the database and merge with hardcoded defaults.
// Saved hints override hardcoded ones for the same column name.
(async function loadSavedFieldHints() {
    try {
        const resp = await fetch('/api/field-hints');
        if (resp.ok) {
            const saved = await resp.json();
            for (const [col, hint] of Object.entries(saved)) {
                FIELD_HINTS[col] = hint;
            }
        }
    } catch (e) {
        // Silently fail — hardcoded defaults still work
    }
})();

function createSmartInput(col, val, displayVal, fieldHeight) {
    const hint = FIELD_HINTS[col.column_name];

    // If height is M or L and no special hint, use textarea
    if ((fieldHeight === 'md' || fieldHeight === 'lg') && (!hint || hint.type === 'text')) {
        return createTextarea(col, displayVal);
    }

    // Detect FK/lookup columns (end in _id and aren't the PK)
    if (col.column_name.endsWith('_id') && !state.pk.includes(col.column_name) && col.column_name !== 'asset_id') {
        return createLookupInput(col, val);
    }

    if (hint) {
        switch (hint.type) {
            case 'number': return createNumberInput(col, val, displayVal, hint);
            case 'fraction': return createFractionInput(col, val, hint);
            case 'select': return createSelectInput(col, val, hint);
            case 'url': return createUrlInput(col, displayVal);
            case 'date': return createDateInput(col, val, displayVal);
        }
    }

    // Also detect numeric postgres types
    if (['numeric', 'integer', 'bigint', 'smallint', 'real', 'double precision'].includes(col.data_type)) {
        return createNumberInput(col, val, displayVal, { type: 'number', step: 'any' });
    }

    // Date postgres types
    if (col.data_type === 'date') {
        return createDateInput(col, val, displayVal);
    }

    // Default: plain text input or textarea
    if (fieldHeight === 'md' || fieldHeight === 'lg') {
        return createTextarea(col, displayVal);
    }
    return createTextInput(col, displayVal);
}

function createTextInput(col, displayVal) {
    const input = document.createElement('input');
    input.type = 'text';
    input.value = displayVal;
    input.dataset.col = col.column_name;
    input.dataset.original = displayVal;
    attachChangeHandler(input, col.column_name);
    return input;
}

function createTextarea(col, displayVal) {
    const input = document.createElement('textarea');
    input.value = displayVal;
    input.dataset.col = col.column_name;
    input.dataset.original = displayVal;
    attachChangeHandler(input, col.column_name);
    return input;
}

function createNumberInput(col, val, displayVal, hint) {
    const wrapper = document.createElement('div');
    wrapper.className = 'input-with-addon';

    if (hint.prefix) {
        const pre = document.createElement('span');
        pre.className = 'input-addon prefix';
        pre.textContent = hint.prefix;
        wrapper.appendChild(pre);
    }

    const input = document.createElement('input');
    input.type = 'number';
    input.value = val !== null && val !== undefined ? val : '';
    if (hint.min !== undefined) input.min = hint.min;
    if (hint.max !== undefined) input.max = hint.max;
    if (hint.step !== undefined) input.step = hint.step;
    if (hint.placeholder) input.placeholder = hint.placeholder;
    input.dataset.col = col.column_name;
    input.dataset.original = displayVal;
    attachChangeHandler(input, col.column_name);
    wrapper.appendChild(input);

    if (hint.suffix) {
        const suf = document.createElement('span');
        suf.className = 'input-addon suffix';
        suf.textContent = hint.suffix;
        wrapper.appendChild(suf);
    }

    return wrapper;
}

function createSelectInput(col, val, hint) {
    const select = document.createElement('select');
    select.dataset.col = col.column_name;
    select.dataset.original = val !== null ? String(val) : '';

    // Add empty/null option
    const emptyOpt = document.createElement('option');
    emptyOpt.value = '';
    emptyOpt.textContent = '— none —';
    if (val === null || val === undefined) emptyOpt.selected = true;
    select.appendChild(emptyOpt);

    for (const opt of hint.options) {
        const option = document.createElement('option');
        option.value = opt;
        option.textContent = opt;
        if (String(val) === opt) option.selected = true;
        select.appendChild(option);
    }

    select.addEventListener('change', () => {
        const newVal = select.value === '' ? null : select.value;
        const original = select.dataset.original || null;
        if (newVal !== original) {
            state.editedFields[col.column_name] = newVal;
            select.style.borderColor = 'var(--warning)';
        } else {
            delete state.editedFields[col.column_name];
            select.style.borderColor = '';
        }
    });

    return select;
}

function createUrlInput(col, displayVal) {
    const wrapper = document.createElement('div');
    wrapper.className = 'input-with-addon';

    const input = document.createElement('input');
    input.type = 'url';
    input.value = displayVal;
    input.placeholder = 'https://...';
    input.dataset.col = col.column_name;
    input.dataset.original = displayVal;
    attachChangeHandler(input, col.column_name);
    wrapper.appendChild(input);

    if (displayVal) {
        const link = document.createElement('a');
        link.className = 'input-addon suffix url-link';
        link.href = displayVal;
        link.target = '_blank';
        link.textContent = '↗';
        link.title = 'Open link';
        wrapper.appendChild(link);
    }

    return wrapper;
}

function createDateInput(col, val, displayVal) {
    const input = document.createElement('input');
    input.type = 'date';
    // Format for date input (needs YYYY-MM-DD)
    if (val && typeof val === 'string') {
        input.value = val.split('T')[0];
    } else {
        input.value = displayVal;
    }
    input.dataset.col = col.column_name;
    input.dataset.original = input.value;
    attachChangeHandler(input, col.column_name);
    return input;
}

// --- Fraction utilities ---

const COMMON_FRACTIONS = [
    [1, 16], [1, 8], [3, 16], [1, 4], [5, 16], [3, 8], [7, 16],
    [1, 2], [9, 16], [5, 8], [11, 16], [3, 4], [13, 16], [7, 8],
    [15, 16], [1, 1]
];

function decimalToFraction(decimal) {
    if (decimal === null || decimal === undefined || decimal === '') return '';
    const num = parseFloat(decimal);
    if (isNaN(num)) return String(decimal);
    if (num === 0) return '0';

    // Handle whole + fractional parts
    const whole = Math.floor(num);
    const frac = num - whole;

    if (frac < 0.001) {
        return whole === 0 ? '0' : String(whole);
    }

    // Find closest common fraction
    let bestNum = 0, bestDen = 1, bestDiff = 999;
    for (const [n, d] of COMMON_FRACTIONS) {
        const diff = Math.abs(frac - n / d);
        if (diff < bestDiff) {
            bestDiff = diff;
            bestNum = n;
            bestDen = d;
        }
    }

    // If close enough to a common fraction (within 0.005)
    if (bestDiff < 0.005) {
        if (bestNum === bestDen) {
            // It's a whole number
            return String(whole + 1);
        }
        if (whole > 0) {
            return `${whole}-${bestNum}/${bestDen}`;
        }
        return `${bestNum}/${bestDen}`;
    }

    // Not a common fraction — show decimal
    return num % 1 === 0 ? String(num) : num.toFixed(3).replace(/0+$/, '').replace(/\.$/, '');
}

function fractionToDecimal(str) {
    if (!str || str.trim() === '') return null;
    str = str.trim();

    // Already a plain number?
    if (/^-?\d+\.?\d*$/.test(str)) {
        return parseFloat(str);
    }

    // Mixed number: "1-3/8" or "1 3/8"
    const mixedMatch = str.match(/^(\d+)[\s-]+(\d+)\/(\d+)$/);
    if (mixedMatch) {
        const whole = parseInt(mixedMatch[1]);
        const num = parseInt(mixedMatch[2]);
        const den = parseInt(mixedMatch[3]);
        if (den === 0) return null;
        return whole + num / den;
    }

    // Simple fraction: "3/8"
    const fracMatch = str.match(/^(\d+)\/(\d+)$/);
    if (fracMatch) {
        const num = parseInt(fracMatch[1]);
        const den = parseInt(fracMatch[2]);
        if (den === 0) return null;
        return num / den;
    }

    // Can't parse
    return null;
}

function createFractionInput(col, val, hint) {
    const wrapper = document.createElement('div');
    wrapper.className = 'input-with-addon';

    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'fraction-input';
    input.value = decimalToFraction(val);
    input.placeholder = hint.placeholder || 'e.g. 3/8';
    input.dataset.col = col.column_name;
    input.dataset.original = val !== null && val !== undefined ? String(val) : '';

    input.addEventListener('input', () => {
        const parsed = fractionToDecimal(input.value);
        const originalNum = input.dataset.original ? parseFloat(input.dataset.original) : null;

        if (input.value.trim() === '') {
            if (originalNum !== null) {
                state.editedFields[col.column_name] = null;
                input.style.borderColor = 'var(--warning)';
            } else {
                delete state.editedFields[col.column_name];
                input.style.borderColor = '';
            }
        } else if (parsed !== null && parsed !== originalNum) {
            state.editedFields[col.column_name] = String(parsed);
            input.style.borderColor = 'var(--warning)';
        } else if (parsed === originalNum) {
            delete state.editedFields[col.column_name];
            input.style.borderColor = '';
        }
    });

    // On blur, normalize display to fraction
    input.addEventListener('blur', () => {
        const parsed = fractionToDecimal(input.value);
        if (parsed !== null) {
            input.value = decimalToFraction(parsed);
        }
    });

    wrapper.appendChild(input);

    if (hint.suffix) {
        const suf = document.createElement('span');
        suf.className = 'input-addon suffix';
        suf.textContent = hint.suffix;
        wrapper.appendChild(suf);
    }

    return wrapper;
}

function createLookupInput(col, val) {
    // Derive the referenced table from the column name: "saw_blade_id" -> "saw_blades"
    const baseName = col.column_name.replace(/_id$/, '');
    // Try common pluralizations
    const possibleTables = [baseName + 's', baseName + 'es', baseName];

    const wrapper = document.createElement('div');
    wrapper.className = 'lookup-wrapper';

    const select = document.createElement('select');
    select.dataset.col = col.column_name;
    select.dataset.original = val !== null ? String(val) : '';

    // Add empty option
    const emptyOpt = document.createElement('option');
    emptyOpt.value = '';
    emptyOpt.textContent = '— none —';
    if (val === null || val === undefined) emptyOpt.selected = true;
    select.appendChild(emptyOpt);

    // Add loading option
    const loadingOpt = document.createElement('option');
    loadingOpt.value = '__loading__';
    loadingOpt.textContent = 'Loading...';
    loadingOpt.disabled = true;
    select.appendChild(loadingOpt);

    wrapper.appendChild(select);

    // Hyperlink to the linked record
    const link = document.createElement('a');
    link.className = 'lookup-link';
    link.textContent = '→ view';
    link.title = 'Open linked record';
    link.style.display = val ? '' : 'none';
    link.href = '#';
    link.addEventListener('click', (e) => {
        e.preventDefault();
        const selectedId = select.value;
        if (selectedId && selectedId !== '__loading__') {
            navigateToLinkedRecord(possibleTables, selectedId);
        }
    });
    wrapper.appendChild(link);

    // Update link visibility on change
    select.addEventListener('change', () => {
        const newVal = select.value === '' ? null : select.value;
        const original = select.dataset.original || null;
        if (String(newVal) !== String(original)) {
            state.editedFields[col.column_name] = newVal;
            select.style.borderColor = 'var(--warning)';
        } else {
            delete state.editedFields[col.column_name];
            select.style.borderColor = '';
        }
        link.style.display = newVal ? '' : 'none';
    });

    // Load options async
    loadLookupOptions(select, val, possibleTables);

    return wrapper;
}

async function navigateToLinkedRecord(possibleTables, id) {
    const schemas = await api('/schemas');
    for (const schema of schemas) {
        for (const tableName of possibleTables) {
            try {
                const data = await api(`/rows/${schema}/${tableName}?limit=1&offset=0&search=${id}`);
                if (data.rows && data.rows.length > 0) {
                    // Found it - navigate
                    await selectTable(schema, tableName);
                    // Find the row with this ID and open it
                    const row = state.rows.find(r => String(r.id) === String(id));
                    if (row) openRowDetail(row);
                    return;
                }
            } catch (e) { /* skip */ }
        }
    }
    toast('Could not find linked record', 'error');
}

async function loadLookupOptions(select, currentVal, possibleTables) {
    // Try to find the referenced table in all schemas
    const schemas = await api('/schemas');

    for (const schema of schemas) {
        for (const tableName of possibleTables) {
            try {
                const data = await api(`/lookup-options/${schema}/${tableName}`);
                if (data.options && data.options.length >= 0) {
                    // Remove loading option
                    const loading = select.querySelector('[value="__loading__"]');
                    if (loading) loading.remove();

                    // Add real options
                    for (const opt of data.options) {
                        const option = document.createElement('option');
                        option.value = opt.id;
                        option.textContent = `${opt.label || opt.id} (#${opt.id})`;
                        if (String(currentVal) === String(opt.id)) option.selected = true;
                        select.appendChild(option);
                    }
                    return; // Found it
                }
            } catch (e) {
                // Table doesn't exist in this schema, try next
            }
        }
    }

    // Couldn't find the table — fall back to plain number input
    const loading = select.querySelector('[value="__loading__"]');
    if (loading) loading.textContent = '(no linked table found)';
}

function attachChangeHandler(input, colName) {
    const handler = () => {
        const currentVal = input.value;
        if (currentVal !== input.dataset.original) {
            state.editedFields[colName] = currentVal === '' ? null : currentVal;
            input.style.borderColor = 'var(--warning)';
        } else {
            delete state.editedFields[colName];
            input.style.borderColor = '';
        }
    };
    input.addEventListener('input', handler);
    input.addEventListener('change', handler);
}

// --- Drag and drop ---

let draggedEl = null;

function setupDragAndDrop(container) {
    const items = container.querySelectorAll('.draggable');

    items.forEach(item => {
        item.addEventListener('dragstart', (e) => {
            draggedEl = item;
            item.classList.add('dragging');
            e.dataTransfer.effectAllowed = 'move';
        });

        item.addEventListener('dragend', () => {
            item.classList.remove('dragging');
            draggedEl = null;
            // Remove all drop indicators
            container.querySelectorAll('.drag-over').forEach(el => el.classList.remove('drag-over'));
        });

        item.addEventListener('dragover', (e) => {
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
            if (item !== draggedEl) {
                item.classList.add('drag-over');
            }
        });

        item.addEventListener('dragleave', () => {
            item.classList.remove('drag-over');
        });

        item.addEventListener('drop', (e) => {
            e.preventDefault();
            item.classList.remove('drag-over');
            if (draggedEl && draggedEl !== item) {
                // Reorder: insert dragged before or after this item
                const allItems = [...container.querySelectorAll('.draggable')];
                const dragIdx = allItems.indexOf(draggedEl);
                const dropIdx = allItems.indexOf(item);

                if (dragIdx < dropIdx) {
                    container.insertBefore(draggedEl, item.nextSibling);
                } else {
                    container.insertBefore(draggedEl, item);
                }

                // Save new order
                saveCurrentLayout();
            }
        });
    });
}

function saveCurrentLayout() {
    const grid = document.getElementById('detail-grid');
    const items = grid.querySelectorAll('.detail-field[data-col]');
    const order = [...items].map(el => el.dataset.col);

    const layout = getLayout() || {};
    layout.order = order;
    saveLayout(layout);
    toast('Layout saved', 'success');
}

function toggleFieldVisibility(colName) {
    const layout = getLayout() || { order: state.columns.map(c => c.column_name), hidden: [] };
    const hidden = new Set(layout.hidden || []);

    if (hidden.has(colName)) {
        hidden.delete(colName);
    } else {
        hidden.add(colName);
    }

    layout.hidden = [...hidden];
    saveLayout(layout);
    renderDetailFields();
}

function setFieldWidth(colName, width) {
    const layout = getLayout() || { order: state.columns.map(c => c.column_name), hidden: [] };
    if (!layout.widths) layout.widths = {};
    layout.widths[colName] = width;
    saveLayout(layout);
    renderDetailFields();
}

function setFieldHeight(colName, height) {
    const layout = getLayout() || { order: state.columns.map(c => c.column_name), hidden: [] };
    if (!layout.heights) layout.heights = {};
    layout.heights[colName] = height;
    saveLayout(layout);
    renderDetailFields();
}

function toggleLayoutMode() {
    state.layoutMode = !state.layoutMode;
    const btn = document.getElementById('btn-layout');
    btn.textContent = state.layoutMode ? '✓ Done' : '⚙ Layout';
    btn.classList.toggle('btn-primary', state.layoutMode);
    renderDetailFields();
}

function resetLayout() {
    if (!confirm('Reset field order and visibility to defaults for this table?')) return;
    localStorage.removeItem(layoutKey());
    renderDetailFields();
    toast('Layout reset to defaults');
}

// --- Save changes ---

async function saveRow() {
    if (Object.keys(state.editedFields).length === 0) {
        toast('No changes to save', 'error');
        return;
    }

    const pk = {};
    for (const k of state.pk) {
        pk[k] = state.editingRow[k];
    }

    try {
        await api(`/rows/${state.schema}/${state.table}`, {
            method: 'PUT',
            body: JSON.stringify({ pk, updates: state.editedFields }),
        });
        toast('Row updated');
        await loadRows();
        backToTable();
    } catch (e) {
        friendlyError(e, 'Save failed');
    }
}

// --- Archive ---

async function archiveRow() {
    if (!confirm('Archive this row? (soft-delete — sets archived_at)')) return;

    const pk = {};
    for (const k of state.pk) {
        pk[k] = state.editingRow[k];
    }

    try {
        await api(`/rows/${state.schema}/${state.table}/archive`, {
            method: 'POST',
            body: JSON.stringify({ pk }),
        });
        toast('Row archived');
        await loadRows();
        backToTable();
    } catch (e) {
        friendlyError(e, 'Archive failed');
    }
}

// --- Delete ---

async function deleteRow() {
    if (!confirm('PERMANENTLY delete this row? This cannot be undone.')) return;
    if (!confirm('Are you really sure? This is a hard delete.')) return;

    const pk = {};
    for (const k of state.pk) {
        pk[k] = state.editingRow[k];
    }

    try {
        await api(`/rows/${state.schema}/${state.table}/delete`, {
            method: 'POST',
            body: JSON.stringify({ pk }),
        });
        toast('Row deleted');
        await loadRows();
        backToTable();
    } catch (e) {
        friendlyError(e, 'Delete failed');
    }
}

// --- Back to table ---

function backToTable() {
    document.getElementById('row-detail').classList.remove('active');
    document.getElementById('table-view').style.display = 'block';
    state.editingRow = null;
    state.editedFields = {};
    state.layoutMode = false;
}

// --- Duplicate row ---

async function duplicateRow() {
    if (!state.editingRow) return;

    // Copy all fields except PK and auto-generated ones
    const values = {};
    const autoFields = ['created_at', 'updated_at', 'archived_at'];

    for (const col of state.columns) {
        const isPk = state.pk.includes(col.column_name);
        const isAuto = autoFields.includes(col.column_name) ||
                       (col.column_default && col.column_default.includes('nextval'));
        if (isPk || isAuto) continue;

        const val = state.editingRow[col.column_name];
        if (val !== null && val !== undefined) {
            values[col.column_name] = String(val);
        }
    }

    try {
        const result = await api(`/rows/${state.schema}/${state.table}/insert`, {
            method: 'POST',
            body: JSON.stringify({ values }),
        });
        toast('Row duplicated — editing the copy');
        await loadRows();

        // Open the new row for editing
        if (result.row) {
            const pkCol = state.pk[0] || 'id';
            const newRow = state.rows.find(r => String(r[pkCol]) === String(result.row[pkCol]));
            if (newRow) {
                openRowDetail(newRow);
            } else {
                backToTable();
            }
        } else {
            backToTable();
        }
    } catch (e) {
        friendlyError(e, 'Duplicate failed');
    }
}

// --- Add row modal ---

function openAddModal() {
    const overlay = document.getElementById('modal-overlay');
    const fields = document.getElementById('modal-fields');
    overlay.classList.add('active');

    fields.innerHTML = '';
    for (const col of state.columns) {
        const isAuto = (col.column_default && col.column_default.includes('nextval')) ||
                       ['created_at', 'updated_at', 'archived_at'].includes(col.column_name);
        if (isAuto) continue;

        const group = document.createElement('div');
        group.className = 'form-group';

        const label = document.createElement('label');
        label.textContent = col.column_name;
        group.appendChild(label);

        const isBool = col.data_type === 'boolean';
        const hint = FIELD_HINTS[col.column_name];
        const isLookup = col.column_name.endsWith('_id') && !state.pk.includes(col.column_name) && col.column_name !== 'asset_id';

        if (isBool) {
            // Boolean toggle
            const wrapper = document.createElement('div');
            wrapper.className = 'bool-toggle';
            wrapper.dataset.col = col.column_name;
            const options = [
                { label: 'Yes', value: 'true' },
                { label: 'No', value: 'false' },
                { label: '—', value: '' },
            ];
            for (const opt of options) {
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'bool-btn' + (opt.value === '' ? ' active' : '');
                btn.textContent = opt.label;
                btn.dataset.val = opt.value;
                btn.addEventListener('click', () => {
                    wrapper.querySelectorAll('.bool-btn').forEach(b => b.classList.remove('active'));
                    btn.classList.add('active');
                });
                wrapper.appendChild(btn);
            }
            group.appendChild(wrapper);
        } else if (isLookup) {
            // Lookup dropdown
            const select = document.createElement('select');
            select.dataset.col = col.column_name;
            const emptyOpt = document.createElement('option');
            emptyOpt.value = '';
            emptyOpt.textContent = '— none —';
            select.appendChild(emptyOpt);
            group.appendChild(select);
            // Load options
            const baseName = col.column_name.replace(/_id$/, '');
            const possibleTables = [baseName + 's', baseName + 'es', baseName];
            loadLookupOptions(select, null, possibleTables);
        } else if (hint && hint.type === 'select') {
            // Dropdown
            const select = document.createElement('select');
            select.dataset.col = col.column_name;
            const emptyOpt = document.createElement('option');
            emptyOpt.value = '';
            emptyOpt.textContent = '— none —';
            select.appendChild(emptyOpt);
            for (const opt of hint.options) {
                const option = document.createElement('option');
                option.value = opt;
                option.textContent = opt;
                select.appendChild(option);
            }
            group.appendChild(select);
        } else if (hint && hint.type === 'fraction') {
            // Fraction input
            const wrapper = document.createElement('div');
            wrapper.className = 'input-with-addon';
            const input = document.createElement('input');
            input.type = 'text';
            input.className = 'fraction-input';
            input.dataset.col = col.column_name;
            input.placeholder = hint.placeholder || 'e.g. 3/8';
            input.addEventListener('blur', () => {
                const parsed = fractionToDecimal(input.value);
                if (parsed !== null) input.value = decimalToFraction(parsed);
            });
            wrapper.appendChild(input);
            if (hint.suffix) {
                const suf = document.createElement('span');
                suf.className = 'input-addon suffix';
                suf.textContent = hint.suffix;
                wrapper.appendChild(suf);
            }
            group.appendChild(wrapper);
        } else if (hint && hint.type === 'number') {
            // Number with prefix/suffix
            const wrapper = document.createElement('div');
            wrapper.className = 'input-with-addon';
            if (hint.prefix) {
                const pre = document.createElement('span');
                pre.className = 'input-addon prefix';
                pre.textContent = hint.prefix;
                wrapper.appendChild(pre);
            }
            const input = document.createElement('input');
            input.type = 'number';
            input.dataset.col = col.column_name;
            if (hint.min !== undefined) input.min = hint.min;
            if (hint.max !== undefined) input.max = hint.max;
            if (hint.step !== undefined) input.step = hint.step;
            if (hint.placeholder) input.placeholder = hint.placeholder;
            wrapper.appendChild(input);
            if (hint.suffix) {
                const suf = document.createElement('span');
                suf.className = 'input-addon suffix';
                suf.textContent = hint.suffix;
                wrapper.appendChild(suf);
            }
            group.appendChild(wrapper);
        } else if (hint && hint.type === 'date' || col.data_type === 'date') {
            const input = document.createElement('input');
            input.type = 'date';
            input.dataset.col = col.column_name;
            group.appendChild(input);
        } else if (hint && hint.type === 'url') {
            const input = document.createElement('input');
            input.type = 'url';
            input.dataset.col = col.column_name;
            input.placeholder = 'https://...';
            group.appendChild(input);
        } else if (col.column_name === 'notes') {
            const textarea = document.createElement('textarea');
            textarea.dataset.col = col.column_name;
            textarea.placeholder = col.is_nullable === 'YES' ? 'optional' : 'required';
            textarea.style.minHeight = '80px';
            group.appendChild(textarea);
        } else {
            // Default text input
            const input = document.createElement('input');
            input.type = 'text';
            input.dataset.col = col.column_name;
            input.placeholder = col.is_nullable === 'YES' ? 'optional' : 'required';
            group.appendChild(input);
        }

        fields.appendChild(group);
    }
}

async function insertRow() {
    const fields = document.getElementById('modal-fields');
    const values = {};

    // Collect from all input types
    fields.querySelectorAll('input[data-col], textarea[data-col], select[data-col]').forEach(el => {
        const val = el.value.trim();
        if (val !== '') {
            // Handle fraction fields — convert to decimal
            if (el.classList.contains('fraction-input')) {
                const decimal = fractionToDecimal(val);
                if (decimal !== null) values[el.dataset.col] = String(decimal);
            } else {
                values[el.dataset.col] = val;
            }
        }
    });

    // Collect from boolean toggles
    fields.querySelectorAll('.bool-toggle[data-col]').forEach(wrapper => {
        const active = wrapper.querySelector('.bool-btn.active');
        if (active && active.dataset.val !== '') {
            values[wrapper.dataset.col] = active.dataset.val;
        }
    });

    if (Object.keys(values).length === 0) {
        toast('Enter at least one value', 'error');
        return;
    }

    try {
        await api(`/rows/${state.schema}/${state.table}/insert`, {
            method: 'POST',
            body: JSON.stringify({ values }),
        });
        toast('Row inserted');
        closeModal();
        await loadRows();
    } catch (e) {
        friendlyError(e, 'Insert failed');
    }
}

function closeModal() {
    document.getElementById('modal-overlay').classList.remove('active');
}

// --- Images ---

async function loadRowImages() {
    const grid = document.getElementById('images-grid');
    grid.innerHTML = '<span style="color:var(--text-muted); font-size:0.8rem;">Loading images...</span>';

    const rowId = getPkValue();
    if (!rowId) {
        grid.innerHTML = '';
        return;
    }

    try {
        const res = await fetch(`/api/images/${state.schema}/${state.table}/${rowId}`);
        const images = await res.json();

        if (images.length === 0) {
            grid.innerHTML = '<div class="image-card-empty">No images yet.<br>Upload one above.</div>';
            return;
        }

        grid.innerHTML = '';
        for (let i = 0; i < images.length; i++) {
            const img = images[i];
            const card = document.createElement('div');
            card.className = `image-card${img.is_primary ? ' primary' : ''}`;
            card.draggable = true;
            card.dataset.assetId = img.id;
            card.dataset.idx = i;

            const imgPath = img.path.replace(/^\/home\/michael\/files\//, '').replace(/^\/files\//, '');
            const imgUrl = `/files/${imgPath}`;

            card.innerHTML = `
                ${img.is_primary ? '<span class="primary-badge">PRIMARY</span>' : ''}
                <img src="${imgUrl}" alt="${escapeHtml(img.original_name || 'image')}"
                     onclick="openLightbox('${imgUrl}')" loading="lazy" />
                <div class="image-actions">
                    <button class="img-action-btn star" onclick="event.stopPropagation(); setAsPrimary('${img.id}')" title="Set as primary">★</button>
                    <button class="img-action-btn delete" onclick="event.stopPropagation(); unlinkImage('${img.id}')" title="Remove image">✕</button>
                </div>
                <div class="image-info" title="${escapeHtml(img.original_name || '')}">${escapeHtml(img.original_name || img.id.slice(0, 8))}</div>
            `;

            // Drag events for reordering
            card.addEventListener('dragstart', (e) => {
                e.dataTransfer.setData('text/plain', img.id);
                card.classList.add('dragging');
            });
            card.addEventListener('dragend', () => card.classList.remove('dragging'));
            card.addEventListener('dragover', (e) => {
                e.preventDefault();
                card.classList.add('drag-over');
            });
            card.addEventListener('dragleave', () => card.classList.remove('drag-over'));
            card.addEventListener('drop', (e) => {
                e.preventDefault();
                card.classList.remove('drag-over');
                const draggedId = e.dataTransfer.getData('text/plain');
                if (draggedId !== img.id) {
                    reorderImages(draggedId, img.id);
                }
            });

            grid.appendChild(card);
        }
    } catch (e) {
        grid.innerHTML = `<span style="color:var(--danger); font-size:0.8rem;">Failed to load images</span>`;
    }
}

async function setAsPrimary(assetId) {
    const rowId = getPkValue();
    if (!rowId) return;

    try {
        await api(`/reorder-images/${state.schema}/${state.table}/${rowId}`, {
            method: 'POST',
            body: JSON.stringify({ asset_ids: [assetId] }),
        });
        toast('Set as primary');
        loadRowImages();
    } catch (e) {
        friendlyError(e, 'Set primary failed');
    }
}

async function unlinkImage(assetId) {
    if (!confirm('Remove this image from the record? (The file is kept, just unlinked.)')) return;

    const rowId = getPkValue();
    if (!rowId) return;

    try {
        await api(`/unlink-image/${state.schema}/${state.table}/${rowId}/${assetId}`, {
            method: 'POST',
        });
        toast('Image removed');
        loadRowImages();
    } catch (e) {
        friendlyError(e, 'Remove image failed');
    }
}

async function reorderImages(draggedId, droppedOnId) {
    // Get current order from DOM
    const grid = document.getElementById('images-grid');
    const cards = [...grid.querySelectorAll('.image-card')];
    const ids = cards.map(c => c.dataset.assetId);

    // Move dragged to position of dropped
    const fromIdx = ids.indexOf(draggedId);
    const toIdx = ids.indexOf(droppedOnId);
    ids.splice(fromIdx, 1);
    ids.splice(toIdx, 0, draggedId);

    // First in list becomes primary
    const rowId = getPkValue();
    try {
        await api(`/reorder-images/${state.schema}/${state.table}/${rowId}`, {
            method: 'POST',
            body: JSON.stringify({ asset_ids: ids }),
        });
        loadRowImages();
    } catch (e) {
        friendlyError(e, 'Reorder failed');
    }
}

function getPkValue() {
    if (!state.editingRow || state.pk.length === 0) return null;
    return state.editingRow[state.pk[0]];
}

function openLightbox(url) {
    const lb = document.getElementById('lightbox');
    document.getElementById('lightbox-img').src = url;
    lb.classList.add('active');
}

async function uploadImage(file) {
    const rowId = getPkValue();
    if (!rowId) {
        toast('Cannot determine row ID', 'error');
        return;
    }

    const status = document.getElementById('upload-status');
    status.textContent = 'Uploading...';

    const formData = new FormData();
    formData.append('file', file);

    try {
        const res = await fetch(`/api/upload/${state.schema}/${state.table}/${rowId}`, {
            method: 'POST',
            body: formData,
        });

        let data;
        const contentType = res.headers.get('content-type') || '';
        if (contentType.includes('application/json')) {
            data = await res.json();
        } else {
            const text = await res.text();
            throw new Error(text.slice(0, 100) || `Server error (${res.status})`);
        }

        if (data.ok) {
            toast('Image uploaded and linked');
            status.textContent = '';
            loadRowImages();
        } else {
            toast(data.detail || 'Upload failed', 'error');
            status.textContent = 'Failed';
        }
    } catch (e) {
        toast('Upload failed: ' + e.message, 'error');
        status.textContent = 'Failed';
    }
}

// --- Create Table ---

function openCreateTableModal() {
    document.getElementById('create-table-overlay').classList.add('active');
    document.getElementById('ct-name').value = '';
    document.getElementById('ct-columns').innerHTML = '';
    document.getElementById('ct-preview').style.display = 'none';
    document.getElementById('ct-files').checked = true;
    // Add one default column
    addColumnRow();
}

function closeCreateTableModal() {
    document.getElementById('create-table-overlay').classList.remove('active');
}

function addColumnRow() {
    const container = document.getElementById('ct-columns');
    const row = document.createElement('div');
    row.className = 'ct-col-row';
    row.innerHTML = `
        <input type="text" class="ct-col-name" placeholder="column name" />
        <select class="ct-col-type">
            <option value="text">Text</option>
            <option value="integer">Integer</option>
            <option value="decimal">Decimal</option>
            <option value="number">Number</option>
            <option value="boolean">Boolean</option>
            <option value="date">Date</option>
            <option value="timestamp">Timestamp</option>
        </select>
        <label class="ct-col-nullable" title="Nullable">
            <input type="checkbox" checked /> null
        </label>
        <button class="btn btn-danger ct-col-remove" style="padding:0.2rem 0.5rem; font-size:0.7rem;">✕</button>
    `;
    row.querySelector('.ct-col-remove').addEventListener('click', () => row.remove());
    container.appendChild(row);
}

function getCreateTablePayload() {
    const schema = document.getElementById('ct-schema').value;
    const table_name = document.getElementById('ct-name').value.trim().toLowerCase().replace(/\s+/g, '_');
    const create_files_table = document.getElementById('ct-files').checked;

    const colRows = document.querySelectorAll('.ct-col-row');
    const columns = [];
    for (const row of colRows) {
        const name = row.querySelector('.ct-col-name').value.trim();
        const type = row.querySelector('.ct-col-type').value;
        const nullable = row.querySelector('.ct-col-nullable input').checked;
        if (name) {
            columns.push({ name, type, nullable });
        }
    }

    return { schema, table_name, columns, create_files_table };
}

async function previewCreateTable() {
    const payload = getCreateTablePayload();
    if (!payload.table_name) {
        toast('Enter a table name', 'error');
        return;
    }
    if (payload.columns.length === 0) {
        toast('Add at least one column', 'error');
        return;
    }

    try {
        const data = await api('/preview-create-table', {
            method: 'POST',
            body: JSON.stringify(payload),
        });
        document.getElementById('ct-preview').style.display = 'block';
        document.getElementById('ct-preview-sql').textContent = data.sql;
    } catch (e) {
        toast(e.message, 'error');
    }
}

async function createTable() {
    const payload = getCreateTablePayload();
    if (!payload.table_name) {
        toast('Enter a table name', 'error');
        return;
    }
    if (payload.columns.length === 0) {
        toast('Add at least one column', 'error');
        return;
    }

    if (!confirm(`Create table "${payload.schema}.${payload.table_name}"?`)) return;

    try {
        const data = await api('/create-table', {
            method: 'POST',
            body: JSON.stringify(payload),
        });
        toast(`Created ${data.table}` + (data.files_table ? ` + ${data.files_table}` : ''));
        closeCreateTableModal();
        // Reload sidebar to show new table
        await loadSidebar();
        // Select the new table
        await selectTable(payload.schema, payload.table_name);
    } catch (e) {
        toast(e.message, 'error');
    }
}

// --- Table Context Menu (right-click) ---

function openTableContextMenu(e, schema, table) {
    closeContextMenu();
    const menu = document.createElement('div');
    menu.id = 'context-menu';
    menu.className = 'context-menu';
    menu.style.left = e.pageX + 'px';
    menu.style.top = e.pageY + 'px';

    const actions = [
        { label: '✏ Rename Table', action: () => promptRenameTable(schema, table) },
        { label: '↗ Move to Schema', action: () => promptMoveTable(schema, table) },
        { label: '+ Add Column', action: () => promptAddColumn(schema, table) },
        { label: '− Delete Column', action: () => promptDeleteColumn(schema, table) },
    ];

    for (const a of actions) {
        const item = document.createElement('div');
        item.className = 'context-menu-item';
        item.textContent = a.label;
        item.addEventListener('click', () => { closeContextMenu(); a.action(); });
        menu.appendChild(item);
    }

    document.body.appendChild(menu);
    // Close on click outside
    setTimeout(() => {
        document.addEventListener('click', closeContextMenu, { once: true });
    }, 0);
}

function closeContextMenu() {
    const existing = document.getElementById('context-menu');
    if (existing) existing.remove();
}

// This file is temporary - content will be merged into app.js

async function promptRenameTable(schema, table) {
    openSchemaActionModal({
        title: `Rename ${schema}.${table}`,
        fields: [
            { id: 'new_name', label: 'New name', type: 'text', placeholder: table },
        ],
        confirmLabel: 'Rename',
        onConfirm: async (values) => {
            if (!values.new_name) { toast('Enter a name', 'error'); return; }
            await api('/rename-table', {
                method: 'POST',
                body: JSON.stringify({ schema, table, new_name: values.new_name }),
            });
            toast(`Renamed to ${schema}.${values.new_name}`);
            await loadSidebar();
        }
    });
}

async function promptMoveTable(schema, table) {
    const schemas = await api('/schemas');
    openSchemaActionModal({
        title: `Move ${schema}.${table}`,
        fields: [
            { id: 'new_schema', label: 'Move to schema', type: 'select',
              options: schemas.filter(s => s !== schema).map(s => ({ value: s, label: s })) },
        ],
        confirmLabel: 'Move Table',
        onConfirm: async (values) => {
            if (!values.new_schema) { toast('Select a schema', 'error'); return; }
            await api('/move-table', {
                method: 'POST',
                body: JSON.stringify({ schema, table, new_schema: values.new_schema }),
            });
            toast(`Moved to ${values.new_schema}.${table}`);
            await loadSidebar();
        }
    });
}

async function promptAddColumn(schema, table) {
    const schemas = await api('/schemas');
    const allTables = [];
    for (const s of schemas) {
        const tables = await api(`/tables/${s}`);
        for (const t of tables) {
            allTables.push({ value: `${s}.${t}`, label: `${s}.${t}` });
        }
    }

    openSchemaActionModal({
        title: `Add Column to ${schema}.${table}`,
        fields: [
            { id: 'name', label: 'Column name', type: 'text', placeholder: 'e.g. brand, weight_lbs' },
            { id: 'coltype', label: 'Type', type: 'select', options: [
                { value: 'text', label: 'Text' },
                { value: 'integer', label: 'Integer' },
                { value: 'decimal', label: 'Decimal' },
                { value: 'boolean', label: 'Boolean' },
                { value: 'date', label: 'Date' },
                { value: 'timestamp', label: 'Timestamp' },
                { value: 'lookup', label: 'Lookup (link to another table)' },
            ]},
            { id: 'ref_table', label: 'Link to table', type: 'select',
              options: [{ value: '', label: '-- select target table --' }, ...allTables], conditional: 'lookup' },
        ],
        confirmLabel: 'Add Column',
        onConfirm: async (values) => {
            if (!values.name) { toast('Enter a column name', 'error'); return; }
            if (values.coltype === 'lookup') {
                if (!values.ref_table) { toast('Select a table to link to', 'error'); return; }
                const [refSchema, refTable] = values.ref_table.split('.');
                await api('/add-lookup-column', {
                    method: 'POST',
                    body: JSON.stringify({ schema, table, name: values.name, ref_schema: refSchema, ref_table: refTable }),
                });
                toast(`Added lookup "${values.name}" -> ${values.ref_table}`);
            } else {
                await api('/add-column', {
                    method: 'POST',
                    body: JSON.stringify({ schema, table, name: values.name, type: values.coltype, nullable: true }),
                });
                toast(`Added column "${values.name}"`);
            }
            if (state.schema === schema && state.table === table) {
                await selectTable(schema, table);
            }
        }
    });
}

async function promptDeleteColumn(schema, table) {
    const columns = await api(`/columns/${schema}/${table}`);
    openSchemaActionModal({
        title: `Delete Column from ${schema}.${table}`,
        fields: [
            { id: 'column', label: 'Column to delete', type: 'select',
              options: columns.map(c => ({ value: c.column_name, label: `${c.column_name} (${c.data_type})` })) },
        ],
        confirmLabel: 'Delete Column',
        confirmDanger: true,
        onConfirm: async (values) => {
            if (!values.column) { toast('Select a column', 'error'); return; }
            if (!confirm(`Permanently delete "${values.column}"? All data in that column will be lost.`)) return;
            await api('/drop-column', {
                method: 'POST',
                body: JSON.stringify({ schema, table, column: values.column }),
            });
            toast(`Deleted column "${values.column}"`);
            if (state.schema === schema && state.table === table) {
                await selectTable(schema, table);
            }
        }
    });
}

async function createNewSchema() {
    openSchemaActionModal({
        title: 'Create New Schema',
        fields: [
            { id: 'name', label: 'Schema name (lowercase, underscores OK)', type: 'text', placeholder: 'e.g. garden, media' },
        ],
        confirmLabel: 'Create Schema',
        onConfirm: async (values) => {
            if (!values.name) { toast('Enter a name', 'error'); return; }
            await api('/create-schema', {
                method: 'POST',
                body: JSON.stringify({ name: values.name }),
            });
            toast(`Created schema "${values.name}"`);
            await loadSidebar();
        }
    });
}

// --- Schema Action Modal (reusable) ---

function openSchemaActionModal(config) {
    const overlay = document.getElementById('schema-action-overlay');
    overlay.classList.add('active');

    document.getElementById('schema-action-title').textContent = config.title;

    const fieldsContainer = document.getElementById('schema-action-fields');
    fieldsContainer.innerHTML = '';

    for (const field of config.fields) {
        const group = document.createElement('div');
        group.className = 'form-group';
        if (field.conditional) group.dataset.conditional = field.conditional;

        const label = document.createElement('label');
        label.textContent = field.label;
        group.appendChild(label);

        if (field.type === 'select') {
            const select = document.createElement('select');
            select.dataset.id = field.id;
            for (const opt of field.options) {
                const option = document.createElement('option');
                option.value = opt.value;
                option.textContent = opt.label;
                select.appendChild(option);
            }
            group.appendChild(select);
        } else {
            const input = document.createElement('input');
            input.type = 'text';
            input.dataset.id = field.id;
            input.placeholder = field.placeholder || '';
            group.appendChild(input);
        }

        fieldsContainer.appendChild(group);
    }

    // Show/hide conditional fields
    const typeSelect = fieldsContainer.querySelector('[data-id="coltype"]');
    if (typeSelect) {
        const updateConditionals = () => {
            fieldsContainer.querySelectorAll('[data-conditional]').forEach(g => {
                g.style.display = typeSelect.value === g.dataset.conditional ? '' : 'none';
            });
        };
        typeSelect.addEventListener('change', updateConditionals);
        updateConditionals();
    }

    const confirmBtn = document.getElementById('schema-action-confirm');
    confirmBtn.textContent = config.confirmLabel || 'Confirm';
    confirmBtn.className = config.confirmDanger ? 'btn btn-danger' : 'btn btn-primary';

    // Replace handler (avoid stacking)
    const newBtn = confirmBtn.cloneNode(true);
    confirmBtn.parentNode.replaceChild(newBtn, confirmBtn);
    newBtn.id = 'schema-action-confirm';
    newBtn.addEventListener('click', async () => {
        const values = {};
        fieldsContainer.querySelectorAll('[data-id]').forEach(el => {
            values[el.dataset.id] = el.value.trim();
        });
        try {
            await config.onConfirm(values);
            closeSchemaActionModal();
        } catch (e) {
            friendlyError(e, config.title);
        }
    });
}

function closeSchemaActionModal() {
    document.getElementById('schema-action-overlay').classList.remove('active');
}


// --- Filters ---

function renderFilters() {
    const container = document.getElementById('filter-bar');
    container.innerHTML = '';

    for (let i = 0; i < state.filters.length; i++) {
        const f = state.filters[i];
        const chip = document.createElement('span');
        chip.className = 'filter-chip';
        const opLabel = { eq: '=', neq: '≠', like: '~', gt: '>', lt: '<', gte: '≥', lte: '≤', null: 'is null', notnull: 'has value' }[f.op] || f.op;
        const valLabel = (f.op === 'null' || f.op === 'notnull') ? '' : ` "${f.val}"`;
        chip.innerHTML = `<span>${f.col} ${opLabel}${escapeHtml(valLabel)}</span><button class="filter-remove" data-idx="${i}">✕</button>`;
        chip.querySelector('.filter-remove').addEventListener('click', () => {
            state.filters.splice(i, 1);
            state.offset = 0;
            loadRows();
        });
        container.appendChild(chip);
    }
}

function openFilterModal() {
    const overlay = document.getElementById('filter-overlay');
    overlay.classList.add('active');

    // Populate column dropdown
    const colSelect = document.getElementById('filter-col');
    colSelect.innerHTML = '';
    for (const col of state.columns) {
        const opt = document.createElement('option');
        opt.value = col.column_name;
        opt.textContent = col.column_name;
        colSelect.appendChild(opt);
    }

    document.getElementById('filter-val').value = '';
    document.getElementById('filter-op').value = 'eq';
    updateFilterValVisibility();
}

function closeFilterModal() {
    document.getElementById('filter-overlay').classList.remove('active');
}

function updateFilterValVisibility() {
    const op = document.getElementById('filter-op').value;
    const valInput = document.getElementById('filter-val');
    if (op === 'null' || op === 'notnull') {
        valInput.style.display = 'none';
    } else {
        valInput.style.display = '';
    }
}

function addFilter() {
    const col = document.getElementById('filter-col').value;
    const op = document.getElementById('filter-op').value;
    const val = document.getElementById('filter-val').value;

    if (!col) return;
    if (op !== 'null' && op !== 'notnull' && !val) {
        toast('Enter a filter value', 'error');
        return;
    }

    state.filters.push({ col, op, val });
    state.offset = 0;
    closeFilterModal();
    loadRows();
}

// --- Search ---

let searchTimeout;
function onSearch(e) {
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(() => {
        state.search = e.target.value.trim();
        state.offset = 0;
        loadRows();
    }, 300);
}

// --- Init ---

document.addEventListener('DOMContentLoaded', () => {
    loadSidebar();

    // Handle ?open=schema.table.id parameter (from inbox redirect)
    const params = new URLSearchParams(window.location.search);
    const openParam = params.get('open');
    if (openParam) {
        const parts = openParam.split('.');
        if (parts.length === 3) {
            const [schema, table, id] = parts;
            // Wait for sidebar to load, then navigate to the record
            setTimeout(async () => {
                await selectTable(schema, table);
                // Find the row and open it
                const row = state.rows.find(r => String(r.id) === id);
                if (row) {
                    openRowDetail(row);
                } else {
                    // Row might not be on the first page — search for it
                    const data = await api(`/rows/${schema}/${table}?limit=1&offset=0&search=${id}`);
                    if (data.rows && data.rows.length > 0) {
                        openRowDetail(data.rows[0]);
                    }
                }
                // Clean URL
                window.history.replaceState({}, '', '/');
            }, 500);
        }
    }

    document.getElementById('btn-back').addEventListener('click', backToTable);
    document.getElementById('btn-save').addEventListener('click', saveRow);
    document.getElementById('btn-archive').addEventListener('click', archiveRow);
    document.getElementById('btn-delete').addEventListener('click', deleteRow);
    document.getElementById('btn-duplicate').addEventListener('click', duplicateRow);
    document.getElementById('btn-add-row').addEventListener('click', openAddModal);
    document.getElementById('btn-columns').addEventListener('click', openColumnPicker);
    document.getElementById('btn-filter').addEventListener('click', openFilterModal);
    document.getElementById('filter-cancel').addEventListener('click', closeFilterModal);
    document.getElementById('filter-apply').addEventListener('click', addFilter);
    document.getElementById('filter-op').addEventListener('change', updateFilterValVisibility);
    document.getElementById('col-picker-close').addEventListener('click', closeColumnPicker);
    document.getElementById('col-picker-reset').addEventListener('click', resetListLayout);
    document.getElementById('btn-layout').addEventListener('click', toggleLayoutMode);
    document.getElementById('btn-reset-layout').addEventListener('click', resetLayout);
    document.getElementById('btn-new-table').addEventListener('click', openCreateTableModal);
    document.getElementById('btn-new-schema').addEventListener('click', createNewSchema);
    document.getElementById('ct-cancel').addEventListener('click', closeCreateTableModal);
    document.getElementById('ct-add-col').addEventListener('click', addColumnRow);
    document.getElementById('ct-preview-btn').addEventListener('click', previewCreateTable);
    document.getElementById('ct-create').addEventListener('click', createTable);
    document.getElementById('modal-cancel').addEventListener('click', closeModal);
    document.getElementById('modal-save').addEventListener('click', insertRow);
    document.getElementById('search-input').addEventListener('input', onSearch);

    document.getElementById('file-upload').addEventListener('change', (e) => {
        const file = e.target.files[0];
        if (file) {
            uploadImage(file);
            e.target.value = '';
        }
    });

    document.getElementById('modal-overlay').addEventListener('click', (e) => {
        if (e.target === e.currentTarget) closeModal();
    });

    document.getElementById('create-table-overlay').addEventListener('click', (e) => {
        if (e.target === e.currentTarget) closeCreateTableModal();
    });

    document.getElementById('col-picker-overlay').addEventListener('click', (e) => {
        if (e.target === e.currentTarget) closeColumnPicker();
    });

    document.getElementById('filter-overlay').addEventListener('click', (e) => {
        if (e.target === e.currentTarget) closeFilterModal();
    });

    document.getElementById('schema-action-overlay').addEventListener('click', (e) => {
        if (e.target === e.currentTarget) closeSchemaActionModal();
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            const lightbox = document.getElementById('lightbox');
            if (lightbox.classList.contains('active')) {
                lightbox.classList.remove('active');
            } else if (document.getElementById('col-picker-overlay').classList.contains('active')) {
                closeColumnPicker();
            } else if (document.getElementById('create-table-overlay').classList.contains('active')) {
                closeCreateTableModal();
            } else if (document.getElementById('modal-overlay').classList.contains('active')) {
                closeModal();
            } else if (state.layoutMode) {
                toggleLayoutMode();
            } else if (document.getElementById('row-detail').classList.contains('active')) {
                backToTable();
            }
        }
    });
});
