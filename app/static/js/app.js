/**
 * Computer Institute Student Management System - Main JS Logic
 */

/**
 * TOAST NOTIFICATION SYSTEM
 * Display Bootstrap 5 toasts for success/error messages
 */
function showToast(message, type = 'success', duration = 5000) {
    const toastContainer = document.getElementById('toastContainer');
    if (!toastContainer) {
        console.error('Toast container not found');
        return;
    }

    // Determine icon and toast class based on type
    let icon = 'bi-check-circle-fill';
    let toastClass = 'toast-success';
    let title = 'Success';

    if (type === 'error' || type === 'danger') {
        icon = 'bi-exclamation-circle-fill';
        toastClass = 'toast-error';
        title = 'Error';
    } else if (type === 'warning') {
        icon = 'bi-exclamation-triangle-fill';
        toastClass = 'toast-warning';
        title = 'Warning';
    } else if (type === 'info') {
        icon = 'bi-info-circle-fill';
        toastClass = 'toast-info';
        title = 'Info';
    }

    // Create toast element
    const toastEl = document.createElement('div');
    toastEl.className = `toast show ${toastClass}`;
    toastEl.setAttribute('role', 'alert');
    toastEl.setAttribute('aria-live', 'assertive');
    toastEl.setAttribute('aria-atomic', 'true');
    toastEl.style.minWidth = '320px';
    toastEl.style.borderRadius = '12px';
    toastEl.style.marginBottom = '1rem';

    toastEl.innerHTML = `
        <div class="toast-header" style="background: transparent; border-bottom: 1px solid rgba(255,255,255,0.1);">
            <i class="bi ${icon} me-2"></i>
            <strong class="me-auto">${title}</strong>
            <button type="button" class="btn-close btn-close-white" data-bs-dismiss="toast" aria-label="Close"></button>
        </div>
        <div class="toast-body">
            ${message}
        </div>
    `;

    toastContainer.appendChild(toastEl);

    // Create Bootstrap toast instance and show
    const toast = new bootstrap.Toast(toastEl);
    toast.show();

    // Remove toast from DOM after it's hidden
    toastEl.addEventListener('hidden.bs.toast', () => {
        toastEl.remove();
    });

    // Auto-hide after duration
    if (duration > 0) {
        setTimeout(() => {
            if (toastEl.parentNode) {
                toast.hide();
            }
        }, duration);
    }
}

function initTomSelect() {
    document.querySelectorAll('.ts-select').forEach(function(el) {
        if (el.tomselect) return;
        var isMulti = el.multiple;
        new TomSelect(el, {
            maxItems: isMulti ? null : 1,
            plugins: isMulti ? ['remove_button', 'clear_button'] : ['clear_button'],
            sortField: [{field: 'text', direction: 'asc'}],
            placeholder: el.getAttribute('placeholder') || (isMulti ? 'Search and select...' : 'Search...'),
            hideSelected: false,
            closeAfterSelect: !isMulti,
            allowEmptyOption: true
        });
    });
}

function initApp() {
    console.log('Institute System JavaScript Initialized');
    
    // Initialize TomSelect on all .ts-select elements
    initTomSelect();
    
    // Automatically load AI Insights on Dashboard page
    if (document.getElementById('ai-insights-container')) {
        loadDashboardAIInsights();
    }
    
    // Set up manual attendance switch triggers
    setupManualAttendanceToggles();
    
    // Setup AJAX form submissions for all edit modals
    setupEditModalFormHandlers();
    
    // Initialize adaptive sortable tables
    initializeTableSorting();
    
    // Initialize table pagination for all data tables
    initializeTablePagination();

    // Initialize global search autocomplete
    initGlobalSearch();

    // Initialize scroll-driven entry animations
    initScrollAnimations();

    // Initialize cursor-relative ambient light glows
    initAmbientGlows();
}

function initScrollAnimations() {
    if (!('IntersectionObserver' in window)) {
        // Fallback for older browsers
        document.querySelectorAll('.animate-on-scroll').forEach(el => el.classList.add('animated'));
        return;
    }
    const observer = new IntersectionObserver((entries, obs) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('animated');
                obs.unobserve(entry.target);
            }
        });
    }, {
        threshold: 0.05,
        rootMargin: '0px 0px -20px 0px'
    });

    document.querySelectorAll('.animate-on-scroll').forEach(el => {
        observer.observe(el);
    });
}

function initAmbientGlows() {
    document.querySelectorAll('.glass-card').forEach(card => {
        card.addEventListener('mousemove', function(e) {
            const rect = card.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const y = e.clientY - rect.top;
            card.style.setProperty('--mouse-x', x + 'px');
            card.style.setProperty('--mouse-y', y + 'px');
        });
    });
}

document.addEventListener('DOMContentLoaded', initApp);
document.addEventListener('htmx:afterSettle', initApp);

/**
 * UNIVERSAL AJAX FORM HANDLER FOR EDIT MODALS
 * Converts all edit/form submissions in modals to AJAX to prevent full page reload
 * and ensure modals close properly after submission
 */
function setupEditModalFormHandlers() {
    // Find all forms inside modals that need AJAX handling
    const modalForms = document.querySelectorAll('.modal form');
    
    modalForms.forEach(form => {
        if (form.hasAttribute('data-no-ajax')) {
            return; // allow normal full-page form submission for create flows
        }
        form.addEventListener('submit', function(e) {
            // Only intercept edit/form POST requests in modals
            const action = this.getAttribute('action');
            const method = this.getAttribute('method') || 'POST';
            
            // Only handle POST forms (edit/delete operations)
            if (method.toUpperCase() !== 'POST') {
                return; // Let default form submission happen
            }
            
            e.preventDefault();
            
            // Get the modal that contains this form
            const modalEl = this.closest('.modal');
            const modal = modalEl ? bootstrap.Modal.getInstance(modalEl) : null;
            
            // Collect form data
            const formData = new FormData(this);
            
            // Show loading state on submit button
            const submitBtn = this.querySelector('[type="submit"]');
            const originalBtnText = submitBtn ? submitBtn.innerHTML : '';
            const originalBtnDisabled = submitBtn ? submitBtn.disabled : false;
            
            if (submitBtn) {
                submitBtn.disabled = true;
                submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>Saving...';
            }
            
            // Submit via AJAX
            fetch(action, {
                method: method,
                body: formData,
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                }
            })
            .then(response => {
                // Try to parse as JSON first
                const contentType = response.headers.get('content-type');
                if (contentType && contentType.includes('application/json')) {
                    return response.json().then(data => ({ ok: response.ok, data: data }));
                }
                return response.text().then(text => ({ ok: response.ok, data: null, text: text }));
            })
            .then(({ ok, data, text }) => {
                if (ok) {
                    // Success - close modal
                    if (modal) {
                        modal.hide();
                    }
                    
                    // Show success toast
                    let message = 'Changes saved successfully!';
                    if (data && data.message) {
                        message = data.message;
                    }
                    showToast(message, 'success');
                    
                    // Refresh content area via HTMX
                    setTimeout(() => {
                        if (window.htmx) {
                            htmx.ajax('GET', window.location.href, {target: '#main-content', swap: 'innerHTML'});
                        } else {
                            window.location.reload();
                        }
                    }, 600);
                } else {
                    // Error response
                    let errorMsg = 'Error saving changes';
                    if (data && data.message) {
                        errorMsg = data.message;
                    }
                    showToast(errorMsg, 'error');
                    // Restore button state
                    if (submitBtn) {
                        submitBtn.disabled = originalBtnDisabled;
                        submitBtn.innerHTML = originalBtnText;
                    }
                }
            })
            .catch(error => {
                console.error('Form submission error:', error);
                // Restore button state
                if (submitBtn) {
                    submitBtn.disabled = originalBtnDisabled;
                    submitBtn.innerHTML = originalBtnText;
                }
                // Show error toast
                showToast('Error saving changes. Please check the form and try again.', 'error');
            });
        });
    });
}

/**
 * 1. AI Dashboard Insights Fetcher
 */
function loadDashboardAIInsights() {
    const container = document.getElementById('ai-insights-container');
    const summaryEl = document.getElementById('ai-insights-summary');
    
    if (!container) return;
    
    var controller = new AbortController();
    var timeoutId = setTimeout(function() { controller.abort(); }, 5000);
    
    fetch('/api/dashboard/ai-insights', { signal: controller.signal })
        .then(function(response) { clearTimeout(timeoutId); return response.json(); })
        .then(function(data) {
            // Write Summary
            if (summaryEl && data.summary) {
                summaryEl.innerHTML = `<p class="mb-0 text-secondary">${data.summary}</p>`;
            }
            
            // Render Insights Cards
            container.innerHTML = '';
            if (data.insights && data.insights.length > 0) {
                data.insights.forEach(function(insight, idx) {
                    let badgeClass = 'badge-cyan';
                    if (insight.badge === 'High') badgeClass = 'badge-danger'; // red/rose glow
                    if (insight.badge === 'Medium') badgeClass = 'badge-amber';
                    
                    const card = document.createElement('div');
                    card.className = 'col-md-4 mb-3 insight-card';
                    card.innerHTML = `
                        <div class="glass-card p-4 h-100 border-start border-3" style="border-left-color: ${insight.badge === 'High' ? 'var(--accent-rose)' : insight.badge === 'Medium' ? 'var(--accent-amber)' : 'var(--accent-cyan)'} !important">
                            <div class="d-flex justify-content-between align-items-start mb-3">
                                <h5 class="card-title mb-0" style="max-width: 65%; word-wrap: break-word;">${insight.title}</h5>
                                <span class="badge badge-custom ${badgeClass}">${insight.badge} Priority</span>
                            </div>
                            <p class="card-text text-secondary font-size-sm" style="font-size: 0.9rem; line-height: 1.5;">${insight.description}</p>
                        </div>
                    `;
                    container.appendChild(card);
                });
            } else {
                container.innerHTML = '<div class="col-12 text-center text-muted">No insights recorded today.</div>';
            }
        })
        .catch(function(error) {
            clearTimeout(timeoutId);
            console.error('AI Insights Loading Error:', error);
            if (summaryEl) summaryEl.innerHTML = '<p class="mb-0 text-secondary">Institute health overview loaded from cached metrics.</p>';
            container.innerHTML = '<div class="col-12 text-center text-muted p-3">AI analysis timed out. Showing precomputed metrics below.</div>';
        });
}

/**
 * 2. AI Enquiry Follow-up Assistant
 */
function generateEnquiryFollowUp(enquiryId) {
    const textContainer = document.getElementById('ai-followup-textarea');
    const loadingSpinner = document.getElementById('ai-followup-loading');
    const displayBox = document.getElementById('ai-followup-box');
    
    if (!textContainer) return;
    
    // Toggle displays
    loadingSpinner.classList.remove('d-none');
    displayBox.classList.add('d-none');
    
    fetch(`/api/enquiry/ai-followup/${enquiryId}`)
        .then(response => response.json())
        .then(data => {
            loadingSpinner.classList.add('d-none');
            displayBox.classList.remove('d-none');
            
            if (data.followup_draft) {
                textContainer.value = data.followup_draft;
            } else {
                textContainer.value = "Error generating follow-up template. Check backend logs.";
            }
        })
        .catch(error => {
            console.error('Follow-up generation error:', error);
            loadingSpinner.classList.add('d-none');
            displayBox.classList.remove('d-none');
            textContainer.value = "Network error while connecting to the AI Advisor. Please try again.";
        });
}

function copyFollowUpToClipboard() {
    const textarea = document.getElementById('ai-followup-textarea');
    if (!textarea) return;
    
    textarea.select();
    textarea.setSelectionRange(0, 99999); // Mobile
    navigator.clipboard.writeText(textarea.value)
        .then(() => {
            const btn = document.getElementById('btn-copy-followup');
            const originalText = btn.innerHTML;
            btn.innerHTML = '<i class="bi bi-check-lg mr-1"></i> Copied!';
            btn.className = "btn btn-success font-weight-bold";
            
            setTimeout(() => {
                btn.innerHTML = originalText;
                btn.className = "btn btn-outline-premium";
            }, 2000);
        })
        .catch(err => {
            console.error('Clipboard copy failed:', err);
        });
}



/**
 * 4. Printable ID Card Dynamic Drawer
 */
function showIDCard(name, role, email, phone, qrCodeUuid, extraLabel, extraVal) {
    // Inject values into Modal ID Card container
    document.getElementById('modal-id-name').innerText = name;
    document.getElementById('modal-id-role').innerText = role;
    document.getElementById('modal-id-email').innerText = email;
    document.getElementById('modal-id-phone').innerText = phone;
    
    const extraBox = document.getElementById('modal-id-extra');
    if (extraLabel && extraVal) {
        extraBox.classList.remove('d-none');
        extraBox.innerHTML = `<strong>${extraLabel}:</strong> ${extraVal}`;
    } else {
        extraBox.classList.add('d-none');
    }
    
    // Clear and draw QR Code using qrcode.js
    const qrTarget = document.getElementById("modal-id-qr");
    qrTarget.innerHTML = "";
    
    // Renders the QR code inside the modal ID Card block
    new QRCode(qrTarget, {
        text: qrCodeUuid,
        width: 100,
        height: 100,
        colorDark : "#000000",
        colorLight : "#ffffff",
        correctLevel : QRCode.CorrectLevel.H
    });
    
    // Open the ID Card BS5 Modal
    const myModal = new bootstrap.Modal(document.getElementById('idCardModal'));
    myModal.show();
}

function printCurrentIDCard() {
    window.print();
}

/**
 * 5. Attendance manual markers (Sync switches asynchronously)
 */
function setupManualAttendanceToggles() {
    const switches = document.querySelectorAll('.attendance-toggle-switch');
    switches.forEach(sw => {
        sw.addEventListener('change', function() {
            const pType = this.dataset.personType; // 'student' or 'tutor'
            const pId = this.dataset.personId;
            const isChecked = this.checked;
            const newStatus = isChecked ? 'Present' : 'Absent';
            
            // Find status text label
            const label = document.getElementById(`status-label-${pType}-${pId}`);
            if (label) {
                label.innerText = newStatus;
                label.className = `badge badge-custom ${isChecked ? 'badge-active' : 'badge-inactive'}`;
            }
            
            // POST to API
            fetch('/api/attendance/mark', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    person_type: pType,
                    person_id: parseInt(pId),
                    status: newStatus
                })
            })
            .then(res => res.json().then(data => ({ status: res.status, data: data })))
            .then(function(result) {
                if (result.data.success) {
                    console.log('Synced ' + pType + ' ' + pId + ' attendance to ' + newStatus);
                } else {
                    // Revert toggle and show error
                    this.checked = !isChecked;
                    if (label) {
                        label.innerText = isChecked ? 'Absent' : 'Present';
                        label.className = 'badge badge-custom ' + (!isChecked ? 'badge-active' : 'badge-inactive');
                    }
                    showToast(result.data.error || 'Failed to mark attendance', 'danger');
                }
            }.bind(this))
            .catch(function(err) {
                console.error('Attendance Sync Failure:', err);
                this.checked = !isChecked;
                if (label) {
                    label.innerText = isChecked ? 'Absent' : 'Present';
                    label.className = 'badge badge-custom ' + (!isChecked ? 'badge-active' : 'badge-inactive');
                }
            }.bind(this));
        });
    });
}

function initializeTableSorting() {
    const tables = document.querySelectorAll('table.table-custom.sortable');
    tables.forEach(table => {
        const headers = table.querySelectorAll('thead th');
        headers.forEach((th, index) => {
            th.style.position = 'relative';
            th.innerHTML = `${th.innerHTML} <span class="sort-indicator"></span>`;
            th.addEventListener('click', () => {
                const currentDir = th.classList.contains('sort-asc') ? 'asc' : th.classList.contains('sort-desc') ? 'desc' : null;
                const newDir = currentDir === 'asc' ? 'desc' : 'asc';
                headers.forEach(header => header.classList.remove('sort-asc', 'sort-desc'));
                th.classList.add(newDir === 'asc' ? 'sort-asc' : 'sort-desc');
                sortTableByColumn(table, index, newDir === 'asc');
            });
        });
    });
}

function sortTableByColumn(table, columnIndex, asc = true) {
    const tbody = table.querySelector('tbody');
    if (!tbody) return;

    const rows = Array.from(tbody.querySelectorAll('tr'));
    const isNumeric = rows.every(row => {
        const cell = row.children[columnIndex];
        const text = cell ? cell.textContent.trim() : '';
        return text === '' || !isNaN(text.replace(/[^0-9.-]+/g, ''));
    });

    const sortedRows = rows.sort((a, b) => {
        const aText = a.children[columnIndex] ? a.children[columnIndex].textContent.trim() : '';
        const bText = b.children[columnIndex] ? b.children[columnIndex].textContent.trim() : '';

        if (isNumeric) {
            const aNum = parseFloat(aText.replace(/[^0-9.-]+/g, '')) || 0;
            const bNum = parseFloat(bText.replace(/[^0-9.-]+/g, '')) || 0;
            return asc ? aNum - bNum : bNum - aNum;
        }

        return asc ? aText.localeCompare(bText, undefined, { numeric: true, sensitivity: 'base' }) : bText.localeCompare(aText, undefined, { numeric: true, sensitivity: 'base' });
    });

    sortedRows.forEach(row => tbody.appendChild(row));

    if (table._pagination) {
        table._pagination.rows = sortedRows;
        table._pagination.currentPage = 1;
        renderTablePage(table);
    }
}

function initializeTablePagination() {
    const tables = document.querySelectorAll('table.table-custom');
    tables.forEach(table => {
        const tbody = table.querySelector('tbody');
        if (!tbody) return;

        const rows = Array.from(tbody.querySelectorAll('tr'));
        const pageSize = parseInt(table.dataset.pageSize, 10) || 10;
        if (rows.length <= pageSize) return;

        if (table._pagination) return;

        // Animate rows with staggered delay
        rows.forEach(function(row, i) {
            row.style.setProperty('--row-index', i);
        });

        // Build toolbar
        var wrapper = document.createElement('div');
        wrapper.className = 'table-toolbar';

        var searchWrap = document.createElement('div');
        searchWrap.className = 'search-wrap';
        searchWrap.innerHTML = '<i class="bi bi-search"></i><input type="text" class="form-control form-control-sm" placeholder="Search table...">';

        var right = document.createElement('div');
        right.className = 'toolbar-right';

        var info = document.createElement('span');
        info.className = 'table-info';

        var rpp = document.createElement('div');
        rpp.className = 'rows-per-page';
        rpp.innerHTML = 'Rows: <select class="form-select form-select-sm"><option value="5">5</option><option value="10" selected>10</option><option value="25">25</option><option value="50">50</option></select>';

        var exportBtn = document.createElement('button');
        exportBtn.type = 'button';
        exportBtn.className = 'btn btn-sm btn-outline-premium ms-2';
        exportBtn.innerHTML = '<i class="bi bi-download me-1"></i>Export';
        exportBtn.addEventListener('click', function() {
            const tableId = table.id || table.getAttribute('id');
            const filename = (tableId || 'data') + '_export.csv';
            exportTableToCSV(tableId, filename);
        });

        right.appendChild(info);
        right.appendChild(rpp);
        right.appendChild(exportBtn);
        wrapper.appendChild(searchWrap);
        wrapper.appendChild(right);
        table.parentNode.insertBefore(wrapper, table);

        var pagination = {
            rows: rows,
            pageSize: pageSize,
            currentPage: 1,
            totalPages: Math.ceil(rows.length / pageSize),
            controls: null,
            toolbar: wrapper,
            infoEl: info,
            searchEl: searchWrap.querySelector('input'),
            rppSelect: rpp.querySelector('select'),
            searchQuery: ''
        };

        var controls = document.createElement('div');
        controls.className = 'table-pagination';
        table.parentNode.insertBefore(controls, table.nextSibling);
        pagination.controls = controls;
        table._pagination = pagination;

        // Search handler
        pagination.searchEl.addEventListener('input', function() {
            pagination.searchQuery = this.value.toLowerCase().trim();
            pagination.currentPage = 1;
            renderTablePage(table);
        });

        // Rows-per-page handler
        pagination.rppSelect.addEventListener('change', function() {
            pagination.pageSize = parseInt(this.value, 10);
            pagination.currentPage = 1;
            renderTablePage(table);
        });

        renderTablePage(table);
    });
}

function getActiveRows(pagination) {
    if (!pagination.searchQuery) return pagination.rows;
    return pagination.rows.filter(function(row) {
        return row.textContent.toLowerCase().indexOf(pagination.searchQuery) !== -1;
    });
}

function renderTablePage(table) {
    var pagination = table._pagination;
    if (!pagination) return;

    var activeRows = getActiveRows(pagination);
    var totalRows = activeRows.length;
    var pageSize = pagination.pageSize;
    var currentPage = pagination.currentPage;
    var totalPages = Math.max(1, Math.ceil(totalRows / pageSize));

    pagination.totalPages = totalPages;
    var start = (currentPage - 1) * pageSize;
    var end = Math.min(start + pageSize, totalRows);

    // Show/hide rows and animate
    pagination.rows.forEach(function(row) {
        row.style.display = 'none';
    });
    activeRows.slice(start, end).forEach(function(row, i) {
        row.style.display = '';
        row.style.setProperty('--row-index', i);
        row.style.animation = 'none';
        // Force reflow then re-add animation
        void row.offsetWidth;
        row.style.animation = '';
    });

    // Update info text
    pagination.infoEl.textContent = totalRows > 0
        ? 'Showing ' + (start + 1) + '\u2013' + end + ' of ' + totalRows
        : 'No results';

    // Update rows-per-page to reflect actual count
    pagination.rppSelect.value = String(pageSize);

    // Build pagination buttons
    var controls = pagination.controls;
    controls.innerHTML = '';

    if (totalPages <= 1) {
        controls.style.display = 'none';
        return;
    }
    controls.style.display = '';

    var pageButtons = [];
    if (totalPages <= 7) {
        for (var i = 1; i <= totalPages; i++) pageButtons.push(i);
    } else {
        if (currentPage <= 4) {
            for (var i = 1; i <= 5; i++) pageButtons.push(i);
            pageButtons.push('...', totalPages);
        } else if (currentPage >= totalPages - 3) {
            pageButtons.push(1, '...');
            for (var i = totalPages - 4; i <= totalPages; i++) pageButtons.push(i);
        } else {
            pageButtons.push(1, '...', currentPage - 1, currentPage, currentPage + 1, '...', totalPages);
        }
    }

    var prevBtn = createPaginationButton('Prev', currentPage > 1, function() {
        pagination.currentPage = Math.max(1, pagination.currentPage - 1);
        renderTablePage(table);
    });
    controls.appendChild(prevBtn);

    pageButtons.forEach(function(page) {
        if (page === '...') {
            var ellipsis = document.createElement('button');
            ellipsis.type = 'button';
            ellipsis.textContent = '\u2026';
            ellipsis.disabled = true;
            controls.appendChild(ellipsis);
            return;
        }
        var btn = createPaginationButton(page, true, function() {
            pagination.currentPage = page;
            renderTablePage(table);
        }, page === currentPage);
        controls.appendChild(btn);
    });

    var nextBtn = createPaginationButton('Next', currentPage < totalPages, function() {
        pagination.currentPage = Math.min(totalPages, pagination.currentPage + 1);
        renderTablePage(table);
    });
    controls.appendChild(nextBtn);
}

function createPaginationButton(label, enabled, onClick, active) {
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.textContent = label;
    btn.disabled = !enabled;
    if (active) btn.classList.add('active');
    if (enabled) {
        btn.addEventListener('click', onClick);
    }
    return btn;
}

/**
 * Export table to CSV
 */
function exportTableToCSV(tableId, filename) {
    const table = document.getElementById(tableId);
    if (!table) {
        console.error('Table not found:', tableId);
        return;
    }

    const rows = table.querySelectorAll('tbody tr');
    const headers = table.querySelectorAll('thead th');
    
    let csv = [];
    
    // Add headers
    let headerRow = [];
    headers.forEach(th => {
        headerRow.push(th.textContent.trim());
    });
    csv.push(headerRow.join(','));
    
    // Add data rows
    rows.forEach(row => {
        let rowData = [];
        const cells = row.querySelectorAll('td');
        cells.forEach(cell => {
            // Get text content, clean up whitespace
            let text = cell.textContent.trim();
            // Escape quotes and wrap in quotes if contains comma
            if (text.includes(',') || text.includes('"')) {
                text = '"' + text.replace(/"/g, '""') + '"';
            }
            rowData.push(text);
        });
        csv.push(rowData.join(','));
    });
    
    // Create download link
    const csvContent = csv.join('\n');
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    const url = URL.createObjectURL(blob);
    
    link.setAttribute('href', url);
    link.setAttribute('download', filename || 'export.csv');
    link.style.visibility = 'hidden';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    
    showToast('Table exported successfully!', 'success');
}

/**
 * Date Range Filter
 */
function createDateRangeFilter(container, callback) {
    const wrapper = document.createElement('div');
    wrapper.className = 'date-range-filter d-flex gap-2 align-items-center mb-3';
    wrapper.innerHTML = `
        <div class="input-group input-group-sm" style="max-width: 250px;">
            <span class="input-group-text bg-transparent border-secondary text-secondary"><i class="bi bi-calendar"></i></span>
            <input type="date" class="form-control form-control-sm bg-transparent border-secondary text-white" id="dateFrom" placeholder="From">
        </div>
        <span class="text-secondary">to</span>
        <div class="input-group input-group-sm" style="max-width: 250px;">
            <span class="input-group-text bg-transparent border-secondary text-secondary"><i class="bi bi-calendar"></i></span>
            <input type="date" class="form-control form-control-sm bg-transparent border-secondary text-white" id="dateTo" placeholder="To">
        </div>
        <button type="button" class="btn btn-sm btn-outline-premium" id="applyDateFilter">
            <i class="bi bi-funnel-fill me-1"></i>Filter
        </button>
        <button type="button" class="btn btn-sm btn-outline-secondary" id="clearDateFilter">
            <i class="bi bi-x-lg me-1"></i>Clear
        </button>
    `;
    
    container.appendChild(wrapper);
    
    const dateFrom = wrapper.querySelector('#dateFrom');
    const dateTo = wrapper.querySelector('#dateTo');
    const applyBtn = wrapper.querySelector('#applyDateFilter');
    const clearBtn = wrapper.querySelector('#clearDateFilter');
    
    applyBtn.addEventListener('click', function() {
        const from = dateFrom.value;
        const to = dateTo.value;
        if (callback) callback(from, to);
    });
    
    clearBtn.addEventListener('click', function() {
        dateFrom.value = '';
        dateTo.value = '';
        if (callback) callback(null, null);
    });
    
    return { dateFrom, dateTo, applyBtn, clearBtn };
}

/**
 * 6. Webcam QR Attendance Scanner Controller
 */
let html5QrcodeScanner = null;

function playSuccessBeep() {
    try {
        const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        
        // Dynamic sound synthesize - dual frequency chord for a delightful beep sound!
        const osc1 = audioCtx.createOscillator();
        const osc2 = audioCtx.createOscillator();
        const gainNode = audioCtx.createGain();
        
        osc1.type = 'sine';
        osc1.frequency.setValueAtTime(880, audioCtx.currentTime); // A5
        
        osc2.type = 'sine';
        osc2.frequency.setValueAtTime(1109, audioCtx.currentTime); // C#6
        
        gainNode.gain.setValueAtTime(0.12, audioCtx.currentTime);
        gainNode.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + 0.3);
        
        osc1.connect(gainNode);
        osc2.connect(gainNode);
        gainNode.connect(audioCtx.destination);
        
        osc1.start();
        osc2.start();
        osc1.stop(audioCtx.currentTime + 0.3);
        osc2.stop(audioCtx.currentTime + 0.3);
    } catch (e) {
        console.warn("Audio Context beep error:", e);
    }
}

function startAttendanceQRScanner() {
    const scannerPanel = document.getElementById('scanner-panel');
    const startBtn = document.getElementById('btn-start-scanner');
    const stopBtn = document.getElementById('btn-stop-scanner');
    const scanLog = document.getElementById('scanner-log-feed');
    
    if (!scannerPanel) return;
    
    // Toggle controls
    scannerPanel.classList.remove('d-none');
    startBtn.classList.add('d-none');
    stopBtn.classList.remove('d-none');
    
    scanLog.innerHTML = '<div class="text-secondary"><i class="bi bi-clock-history me-1"></i> Waiting for barcode signatures...</div>';
    
    // Initialize html5Qrcode
    html5QrcodeScanner = new Html5Qrcode("qr-reader");
    
    const config = { fps: 15, qrbox: { width: 220, height: 220 } };
    
    html5QrcodeScanner.start(
        { facingMode: "environment" }, 
        config, 
        (decodedText, decodedResult) => {
            // Success handler callback
            processQRScan(decodedText);
        },
        (errorMessage) => {
            // Log scanner warnings silently
        }
    ).catch(err => {
        console.error("Camera startup error:", err);
        scanLog.innerHTML = `<div class="text-danger fw-bold"><i class="bi bi-exclamation-triangle-fill me-1"></i> Camera permission denied or device not found.</div>`;
    });
}

function stopAttendanceQRScanner() {
    const scannerPanel = document.getElementById('scanner-panel');
    const startBtn = document.getElementById('btn-start-scanner');
    const stopBtn = document.getElementById('btn-stop-scanner');
    
    if (!html5QrcodeScanner) return;
    
    html5QrcodeScanner.stop().then(() => {
        html5QrcodeScanner = null;
        scannerPanel.classList.add('d-none');
        startBtn.classList.remove('d-none');
        stopBtn.classList.add('d-none');
    }).catch(err => {
        console.error("Stop scanner error:", err);
    });
}

// Keep track of last scanned signatures to avoid repeated processing of same QR within 8 seconds
let lastScannedUuid = null;
let lastScannedTime = 0;

function processQRScan(uuidStr) {
    const now = Date.now();
    if (lastScannedUuid === uuidStr && (now - lastScannedTime < 8000)) {
        // Ignored as duplicate scans
        return;
    }
    
    lastScannedUuid = uuidStr;
    lastScannedTime = now;
    
    const logFeed = document.getElementById('scanner-log-feed');
    
    fetch('/api/attendance/scan', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ qr_code_uuid: uuidStr })
    })
    .then(res => res.json())
    .then(data => {
        if (data.success) {
            playSuccessBeep();
            
            // Add success feed item
            const item = document.createElement('div');
            item.className = 'border border-success rounded-3 p-3 mb-2 bg-success bg-opacity-10 d-flex justify-content-between align-items-center animate-fade-in';
            item.innerHTML = `
                <div>
                    <span class="badge badge-custom badge-active me-2">${data.role}</span>
                    <strong class="text-emerald">${data.name}</strong>
                    <div class="small text-secondary mt-1">${data.message}</div>
                </div>
                <i class="bi bi-patch-check-fill text-emerald fs-3"></i>
            `;
            
            // Clear default info
            if (logFeed.innerHTML.includes("Waiting for barcode")) {
                logFeed.innerHTML = "";
            }
            logFeed.insertBefore(item, logFeed.firstChild);
            
            // Update the checklist table UI if we are on the attendance dashboard manual list
            const rowCheckbox = document.getElementById(`att-checkbox-${data.role.toLowerCase()}-${data.name}`);
            if (rowCheckbox) {
                rowCheckbox.checked = true;
                const label = document.getElementById(`status-label-${data.role.toLowerCase()}-${data.name}`);
                if (label) {
                    label.innerText = 'Present';
                    label.className = 'badge badge-custom badge-active';
                }
            }
        } else {
            const item = document.createElement('div');
            item.className = 'border border-danger rounded-3 p-3 mb-2 bg-danger bg-opacity-10';
            item.innerHTML = `
                <div class="text-rose fw-bold"><i class="bi bi-x-circle me-1"></i> Scan Failed</div>
                <div class="small text-secondary mt-1">${data.message}</div>
            `;
            if (logFeed.innerHTML.includes("Waiting for barcode")) {
                logFeed.innerHTML = "";
            }
            logFeed.insertBefore(item, logFeed.firstChild);
        }
    })
    .catch(err => {
        console.error("QR Scan Sync Error:", err);
    });
}

/* =====================================================
 * 7. Global Search with Autocomplete
 * ===================================================== */
/**
 * Client-side empty state renderer
 * Used for JS-generated dynamic content
 */
function renderEmptyState(message, subtitle, type) {
  var svgs = {
    students: '<svg viewBox="0 0 120 100" fill="none"><circle cx="38" cy="30" r="12" stroke="currentColor" stroke-width="2" fill="none" opacity="0.3"/><path d="M20 68c0-10 8-18 18-18s18 8 18 18" stroke="currentColor" stroke-width="2" fill="none" opacity="0.3"/><circle cx="82" cy="28" r="10" stroke="currentColor" stroke-width="2" fill="none" opacity="0.2"/><path d="M68 62c0-8 6.5-14.5 14-14.5S96 54 96 62" stroke="currentColor" stroke-width="2" fill="none" opacity="0.2"/><circle cx="60" cy="72" r="20" stroke="currentColor" stroke-width="2" fill="none" stroke-dasharray="4 4" opacity="0.5"/></svg>',
    attendance: '<svg viewBox="0 0 120 100" fill="none"><rect x="24" y="14" width="72" height="72" rx="8" stroke="currentColor" stroke-width="2" fill="none" opacity="0.3"/><line x1="24" y1="34" x2="96" y2="34" stroke="currentColor" stroke-width="2" opacity="0.1"/><line x1="48" y1="14" x2="48" y2="4" stroke="currentColor" stroke-width="2" opacity="0.2"/><line x1="72" y1="14" x2="72" y2="4" stroke="currentColor" stroke-width="2" opacity="0.2"/><circle cx="60" cy="66" r="6" stroke="currentColor" stroke-width="2" fill="none" opacity="0.5"/></svg>',
    payroll: '<svg viewBox="0 0 120 100" fill="none"><rect x="26" y="18" width="68" height="64" rx="6" stroke="currentColor" stroke-width="2" fill="none" opacity="0.3"/><rect x="36" y="28" width="48" height="12" rx="3" stroke="currentColor" stroke-width="2" fill="none" opacity="0.2"/><rect x="36" y="48" width="32" height="10" rx="2" stroke="currentColor" stroke-width="2" fill="none" opacity="0.12"/><path d="M86 60l14 14-14-14z" stroke="currentColor" stroke-width="2" fill="none" opacity="0.5"/></svg>',
    backups: '<svg viewBox="0 0 120 100" fill="none"><ellipse cx="60" cy="72" rx="32" ry="10" stroke="currentColor" stroke-width="2" fill="none" opacity="0.2"/><rect x="36" y="24" width="48" height="48" rx="6" stroke="currentColor" stroke-width="2" fill="none" opacity="0.3"/><rect x="44" y="34" width="32" height="6" rx="2" stroke="currentColor" stroke-width="2" fill="none" opacity="0.2"/><rect x="44" y="46" width="24" height="6" rx="2" stroke="currentColor" stroke-width="2" fill="none" opacity="0.12"/><path d="M74 16l10 10-10-10z" stroke="currentColor" stroke-width="2" fill="none" opacity="0.5"/></svg>',
    general: '<svg viewBox="0 0 120 100" fill="none"><circle cx="60" cy="42" r="24" stroke="currentColor" stroke-width="2" fill="none" opacity="0.25"/><line x1="78" y1="60" x2="92" y2="74" stroke="currentColor" stroke-width="2" stroke-linecap="round" opacity="0.25"/></svg>'
  };
  var svg = svgs[type] || svgs.general;
  return '<div class="empty-state py-3"><div class="empty-state-illustration" style="width:100px;height:80px;">' + svg + '</div><div class="empty-state-content"><h4 class="empty-state-title" style="font-size:0.95rem;">' + message + '</h4>' + (subtitle ? '<p class="empty-state-subtitle" style="font-size:0.8rem;margin:2px 0 0;">' + subtitle + '</p>' : '') + '</div></div>';
}

function initGlobalSearch() {
    const input = document.getElementById('globalSearch');
    if (!input || input.dataset.searchInitialized) return;
    input.dataset.searchInitialized = '1';

    const dropdown = document.getElementById('globalSearchDropdown');
    let debounceTimer = null;

    function renderResults(data) {
        const r = data.results;
        const keys = ['students', 'tutors', 'courses', 'enquiries'];
        const labels = { students: 'Students', tutors: 'Tutors', courses: 'Courses', enquiries: 'Enquiries' };
        const icons = { students: 'bi-person-vcard', tutors: 'bi-person-workspace', courses: 'bi-journal-bookmark-fill', enquiries: 'bi-question-circle' };

        let html = '';
        let total = 0;
        for (const key of keys) {
            const items = r[key];
            if (!items || items.length === 0) continue;
            total += items.length;
            html += '<div class="gs-group-label"><i class="bi ' + icons[key] + ' me-1"></i>' + labels[key] + '</div>';
            for (const item of items) {
                var badgeHtml = item.badge ? '<span class="gs-badge gs-badge-' + item.badge.toLowerCase() + '">' + item.badge + '</span>' : '';
                html += '<a href="' + item.url + '" class="gs-item"><div class="gs-item-main"><div class="gs-item-name">' + escapeHtml(item.name) + '</div><div class="gs-item-sub">' + escapeHtml(item.subtitle) + '</div></div>' + badgeHtml + '</a>';
            }
        }
        if (total === 0) {
            html = '<div class="gs-empty"><i class="bi bi-search me-1"></i>No results for "' + escapeHtml(input.value) + '"</div>';
        }
        dropdown.innerHTML = html;
        dropdown.classList.remove('d-none');
    }

    function escapeHtml(t) {
        if (!t) return '';
        var d = document.createElement('div');
        d.textContent = t;
        return d.innerHTML;
    }

    input.addEventListener('input', function() {
        clearTimeout(debounceTimer);
        var q = this.value.trim();
        if (q.length < 2) {
            dropdown.classList.add('d-none');
            return;
        }
        debounceTimer = setTimeout(function() {
            fetch('/api/search?q=' + encodeURIComponent(q))
                .then(function(r) { return r.json(); })
                .then(function(data) { renderResults(data); })
                .catch(function() { dropdown.classList.add('d-none'); });
        }, 250);
    });

    input.addEventListener('focus', function() {
        if (this.value.trim().length >= 2) dropdown.classList.remove('d-none');
    });

    document.addEventListener('click', function(e) {
        if (!input.contains(e.target) && !dropdown.contains(e.target)) {
            dropdown.classList.add('d-none');
        }
    });

    input.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') dropdown.classList.add('d-none');
        if (e.key === 'Enter') { dropdown.classList.add('d-none'); }
    });
}


