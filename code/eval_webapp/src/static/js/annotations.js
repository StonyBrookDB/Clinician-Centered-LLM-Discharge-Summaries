/**
 * Summary Annotations Manager (Summary A or B)
 * Handles text selection, annotation creation, and formal review workflow.
 */

class AnnotationsManager {
    constructor(options = {}) {
        this.encounterNumber = options.encounterNumber;
        this.doctorId = options.doctorId;
        this.onAnnotationsChange = options.onAnnotationsChange || (() => {});
        this.onJumpToHighlight = options.onJumpToHighlight || (() => {});
        this.readOnly = options.readOnly || false;
        this.adminView = options.adminView || false;
        this.reviewDoctorId = options.reviewDoctorId || null;
        const normalizedLabel = String(options.summaryLabel || 'B').toUpperCase();
        this.summaryLabel = normalizedLabel === 'A' ? 'A' : 'B';
        this.summaryPart = options.summaryPart || null;
        this.contentId = options.contentId || null;
        this.contentSelector = options.contentSelector || null;

        this.annotations = [];
        this.iframe = null;
        this.toolbar = null;
        this.modal = null;
        this.selectedRange = null;
        this.selectedText = '';
        this.annotationModeEnabled = false;
        this.currentEditAnnotationId = null;

        this.issueTypes = {
            inaccuracy: { label: 'Inaccuracy/Fabrication', color: '#fecaca', icon: '⚠️' },
            omission: { label: 'Omission', color: '#bfdbfe', icon: '📝' }
        };

        this.initToolbar();
        this.initModal();
        this.injectStyles();
    }

    /**
     * Inject CSS styles
     */
    injectStyles() {
        if (document.getElementById('annotations-styles')) return;

        const style = document.createElement('style');
        style.id = 'annotations-styles';
        style.textContent = `
            /* Annotation toolbar */
            .annotation-toolbar {
                position: fixed;
                display: none;
                z-index: 10000;
                background: white;
                border: 1px solid #d1d5db;
                border-radius: 8px;
                box-shadow: 0 4px 12px rgba(0,0,0,0.15);
                padding: 8px 12px;
            }
            .annotation-toolbar-inner {
                display: flex;
                align-items: center;
                gap: 8px;
            }
            .annotation-type-btn {
                padding: 6px 12px;
                border: 1px solid #d1d5db;
                border-radius: 4px;
                background: white;
                cursor: pointer;
                font-size: 12px;
                display: flex;
                align-items: center;
                gap: 4px;
                transition: all 0.15s;
            }
            .annotation-type-btn:hover {
                background: #f3f4f6;
            }
            .annotation-type-btn.inaccuracy:hover { background: #fecaca; }
            .annotation-type-btn.omission:hover { background: #bfdbfe; }
            .annotation-type-option.readonly {
                pointer-events: none;
                opacity: 0.6;
            }

            /* Annotation modal */
            .annotation-modal {
                position: fixed;
                top: 0;
                left: 0;
                right: 0;
                bottom: 0;
                background: rgba(0,0,0,0.5);
                display: none;
                align-items: center;
                justify-content: center;
                z-index: 10001;
            }
            .annotation-modal.open {
                display: flex;
            }
            .annotation-modal-content {
                background: white;
                border-radius: 8px;
                padding: 1.5rem;
                max-width: 800px;
                width: 95%;
                max-height: 95vh;
                overflow-y: auto;
            }
            .annotation-modal-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 1rem;
            }
            .annotation-modal-header h3 {
                margin: 0;
                font-size: 1.1rem;
            }
            .annotation-modal-close {
                background: none;
                border: none;
                font-size: 1.5rem;
                cursor: pointer;
                color: #6b7280;
            }
            .annotation-selected-text {
                background: #f9fafb;
                border: 1px solid #e5e7eb;
                border-left: 3px solid #0068c9;
                border-radius: 4px;
                padding: 0.75rem;
                margin-bottom: 1rem;
                font-size: 0.875rem;
                max-height: 100px;
                overflow-y: auto;
            }
            .annotation-form-group {
                margin-bottom: 1rem;
            }
            .annotation-form-group label {
                display: block;
                margin-bottom: 0.5rem;
                font-size: 0.875rem;
                font-weight: 500;
                color: #374151;
            }
            .annotation-type-select {
                display: flex;
                gap: 8px;
                flex-wrap: wrap;
            }
            .annotation-type-option {
                padding: 8px 16px;
                border: 2px solid #e5e7eb;
                border-radius: 6px;
                cursor: pointer;
                font-size: 0.875rem;
                transition: all 0.15s;
            }
            .annotation-type-option:hover {
                border-color: #9ca3af;
            }
            .annotation-type-option.selected {
                border-color: #0068c9;
                background: #eff6ff;
            }
            .annotation-type-option.inaccuracy.selected { background: #fef2f2; border-color: #ef4444; }
            .annotation-type-option.omission.selected { background: #eff6ff; border-color: #3b82f6; }
            .annotation-textarea {
                width: 100%;
                min-height: 80px;
                padding: 0.5rem;
                border: 1px solid #d1d5db;
                border-radius: 4px;
                font-size: 0.875rem;
                resize: vertical;
            }
            .annotation-harm-grid {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 1rem;
            }
            .harm-slider-container {
                display: flex;
                flex-direction: column;
                gap: 0.5rem;
            }
            .harm-slider {
                width: 100%;
                height: 8px;
                -webkit-appearance: none;
                appearance: none;
                background: linear-gradient(to right, #dcfce7 0%, #fef08a 50%, #fecaca 100%);
                border-radius: 4px;
                outline: none;
            }
            .harm-slider::-webkit-slider-thumb {
                -webkit-appearance: none;
                width: 20px;
                height: 20px;
                background: white;
                border: 2px solid #374151;
                border-radius: 50%;
                cursor: pointer;
                box-shadow: 0 1px 3px rgba(0,0,0,0.2);
            }
            .harm-value {
                text-align: center;
                font-size: 0.875rem;
                color: #6b7280;
            }
            .harm-reference-table {
                width: 100%;
                border-collapse: collapse;
                margin-top: 0.75rem;
                font-size: 0.65rem;
                line-height: 1.2;
            }
            .harm-reference-table th,
            .harm-reference-table td {
                border: 1px solid #e5e7eb;
                padding: 0.25rem 0.4rem;
                text-align: left;
            }
            .harm-reference-table th {
                background: #f3f4f6;
                font-weight: 600;
                font-size: 0.6rem;
                text-transform: uppercase;
                color: #374151;
            }
            .harm-reference-table .level-cell {
                width: 40px;
                text-align: center;
                font-weight: 600;
            }
            .harm-reference-table td {
                cursor: pointer;
            }
            .harm-reference-table td:hover {
                background: #f3f4f6;
            }
            .harm-reference-table td.highlight-potential:hover,
            .harm-reference-table td.highlight-likelihood:hover {
                filter: brightness(0.95);
            }
            .harm-reference-table td.highlight-potential {
                background: #fef08a;
                font-weight: 500;
            }
            .harm-reference-table td.highlight-likelihood {
                background: #bfdbfe;
                font-weight: 500;
            }
            .harm-reference-table td.highlight-potential.highlight-likelihood {
                background: linear-gradient(135deg, #fef08a 50%, #bfdbfe 50%);
            }
            .harm-reference-table .level-cell.highlight-potential,
            .harm-reference-table .level-cell.highlight-likelihood {
                background: #e5e7eb;
            }
            .annotation-modal-actions {
                display: flex;
                justify-content: space-between;
                gap: 0.5rem;
                margin-top: 1.5rem;
                padding-top: 1rem;
                border-top: 1px solid #e5e7eb;
            }
            .annotation-modal-actions button {
                padding: 0.5rem 1rem;
                border-radius: 4px;
                cursor: pointer;
                font-size: 0.875rem;
            }
            .annotation-save-btn {
                background: #0068c9;
                color: white;
                border: none;
            }
            .annotation-save-btn:hover {
                background: #0054a3;
            }
            .annotation-save-btn:disabled {
                background: #9ca3af;
                cursor: not-allowed;
            }
            .annotation-delete-btn {
                background: #fee2e2;
                color: #991b1b;
                border: 1px solid #fecaca;
            }
            .annotation-delete-btn:hover {
                background: #fecaca;
            }
            .annotation-cancel-btn {
                background: #f3f4f6;
                border: 1px solid #d1d5db;
            }
            .annotation-cancel-btn:hover {
                background: #e5e7eb;
            }

            /* Annotation panel */
            .annotations-panel {
                position: fixed;
                right: 0;
                top: 60px;
                bottom: 0;
                width: 350px;
                background: white;
                border-left: 1px solid #e5e7eb;
                box-shadow: -2px 0 10px rgba(0,0,0,0.1);
                transform: translateX(100%);
                transition: transform 0.3s;
                z-index: 100;
                display: flex;
                flex-direction: column;
            }
            .annotations-panel.open {
                transform: translateX(0);
            }
            .annotation-item {
                padding: 0.75rem;
                border-radius: 6px;
                margin-bottom: 0.75rem;
                cursor: pointer;
                transition: box-shadow 0.15s;
            }
            .annotation-item:hover {
                box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            }
            .annotation-item.inaccuracy { background: #fef2f2; border-left: 3px solid #ef4444; }
            .annotation-item.omission { background: #eff6ff; border-left: 3px solid #3b82f6; }
            .annotation-item-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 0.5rem;
            }
            .annotation-item-type {
                font-size: 0.75rem;
                font-weight: 600;
                text-transform: uppercase;
            }
            .annotation-item-harm {
                font-size: 0.7rem;
                color: #6b7280;
            }
            .annotation-item-text {
                font-size: 0.8rem;
                color: #374151;
                line-height: 1.4;
                margin-bottom: 0.5rem;
            }
            .annotation-item-comment {
                font-size: 0.75rem;
                color: #6b7280;
                font-style: italic;
            }
            .annotation-item-actions {
                display: flex;
                gap: 0.5rem;
                margin-top: 0.5rem;
            }
            .annotation-item-btn {
                padding: 4px 8px;
                font-size: 0.7rem;
                border: 1px solid #d1d5db;
                border-radius: 3px;
                background: white;
                cursor: pointer;
            }
            .annotation-item-btn:hover {
                background: #f3f4f6;
            }
        `;
        document.head.appendChild(style);
    }

    /**
     * Initialize floating toolbar
     */
    initToolbar() {
        this.toolbar = document.createElement('div');
        this.toolbar.className = 'annotation-toolbar';
        this.toolbar.innerHTML = `
            <div class="annotation-toolbar-inner">
                <span style="font-size: 12px; color: #6b7280; margin-right: 4px;">Add:</span>
                ${Object.entries(this.issueTypes).map(([type, data]) => `
                    <button class="annotation-type-btn ${type}" data-type="${type}">
                        ${data.icon} ${data.label.split('/')[0]}
                    </button>
                `).join('')}
            </div>
        `;
        document.body.appendChild(this.toolbar);

        // Button click handlers
        this.toolbar.querySelectorAll('.annotation-type-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const type = e.currentTarget.dataset.type;
                this.openModal(null, type);
            });
        });

        // Hide toolbar on outside click
        document.addEventListener('click', (e) => {
            if (!this.toolbar.contains(e.target)) {
                this.hideToolbar();
            }
        });
    }

    /**
     * Initialize annotation modal
     */
    initModal() {
        this.modal = document.createElement('div');
        this.modal.className = 'annotation-modal';
        this.modal.innerHTML = `
            <div class="annotation-modal-content">
                <div class="annotation-modal-header">
                    <h3 id="annotation-modal-title">Add Annotation</h3>
                    <button class="annotation-modal-close">&times;</button>
                </div>
                <div class="annotation-selected-text" id="annotation-selected-text"></div>
                <div class="annotation-form-group">
                    <label>Issue Type</label>
                    <div class="annotation-type-select" id="annotation-type-select">
                        ${Object.entries(this.issueTypes).map(([type, data]) => `
                            <div class="annotation-type-option ${type}" data-type="${type}">
                                ${data.icon} ${data.label}
                            </div>
                        `).join('')}
                    </div>
                </div>
                <div class="annotation-form-group">
                    <label>Explanation</label>
                    <textarea class="annotation-textarea" id="annotation-comment" placeholder="Describe the issue..."></textarea>
                </div>
                <div class="annotation-form-group">
                    <label>Harm Assessment</label>
                    <div class="annotation-harm-grid">
                        <div class="harm-slider-container">
                            <label style="font-size: 0.75rem; font-weight: normal;">Potential Severity (0-7)</label>
                            <input type="range" class="harm-slider" id="harm-potential" min="0" max="7" value="0">
                            <div class="harm-value" id="harm-potential-value">0 - None</div>
                        </div>
                        <div class="harm-slider-container">
                            <label style="font-size: 0.75rem; font-weight: normal;">Likelihood (0-7)</label>
                            <input type="range" class="harm-slider" id="harm-likelihood" min="0" max="7" value="0">
                            <div class="harm-value" id="harm-likelihood-value">0 - None</div>
                        </div>
                    </div>
                    <table class="harm-reference-table" id="harm-reference-table">
                        <thead>
                            <tr>
                                <th>Level</th>
                                <th>Potential of Harm</th>
                                <th>Likelihood of Harm</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr data-level="7">
                                <td class="level-cell">7</td>
                                <td class="potential-cell">Potential for death</td>
                                <td class="likelihood-cell">Near Certain (&gt;1 in 10)</td>
                            </tr>
                            <tr data-level="6">
                                <td class="level-cell">6</td>
                                <td class="potential-cell">Potential for severe permanent harm</td>
                                <td class="likelihood-cell">Likely (1 in 100)</td>
                            </tr>
                            <tr data-level="5">
                                <td class="level-cell">5</td>
                                <td class="potential-cell">Potential for lifelong bodily or psychological injury or disfigurement</td>
                                <td class="likelihood-cell">Possible (1 in 1,000)</td>
                            </tr>
                            <tr data-level="4">
                                <td class="level-cell">4</td>
                                <td class="potential-cell">Potential for permanent harm (lifelong bodily or psychological injury or increased susceptibility to disease)</td>
                                <td class="likelihood-cell">Rare (1 in 10K)</td>
                            </tr>
                            <tr data-level="3">
                                <td class="level-cell">3</td>
                                <td class="potential-cell">Potential for temporary harm (bodily or psychological injury, but likely not permanent)</td>
                                <td class="likelihood-cell">Very Rare (1 in 100K)</td>
                            </tr>
                            <tr data-level="2">
                                <td class="level-cell">2</td>
                                <td class="potential-cell">Potential for requiring additional treatment</td>
                                <td class="likelihood-cell">Extremely Rare (1 in 1M)</td>
                            </tr>
                            <tr data-level="1">
                                <td class="level-cell">1</td>
                                <td class="potential-cell">Potential for emotional distress or inconvenience (mild and transient anxiety or pain or physical discomfort)</td>
                                <td class="likelihood-cell">Nearly Impossible (&le;1 in 10M)</td>
                            </tr>
                            <tr data-level="0">
                                <td class="level-cell">0</td>
                                <td class="potential-cell">No potential for harm</td>
                                <td class="likelihood-cell">Impossible (0 in 10M)</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
                <div class="annotation-modal-actions">
                    <button class="annotation-delete-btn" id="annotation-delete" style="display: none;">Delete</button>
                    <div style="flex: 1;"></div>
                    <button class="annotation-cancel-btn" id="annotation-cancel">Cancel</button>
                    <button class="annotation-save-btn" id="annotation-save">Save Annotation</button>
                </div>
            </div>
        `;
        document.body.appendChild(this.modal);

        // Event handlers
        this.modal.querySelector('.annotation-modal-close').addEventListener('click', () => this.closeModal());
        this.modal.querySelector('#annotation-cancel').addEventListener('click', () => this.closeModal());
        this.modal.querySelector('#annotation-save').addEventListener('click', () => this.saveFromModal());
        this.modal.querySelector('#annotation-delete').addEventListener('click', () => this.deleteFromModal());

        // Type selection
        this.modal.querySelectorAll('.annotation-type-option').forEach(opt => {
            opt.addEventListener('click', (e) => {
                if (this.readOnly) {
                    return;
                }
                this.modal.querySelectorAll('.annotation-type-option').forEach(o => o.classList.remove('selected'));
                e.currentTarget.classList.add('selected');
                this.updateSaveButtonState();
            });
        });

        // Harm slider updates
        const harmLabels = ['None', 'Minimal', 'Minor', 'Moderate', 'Significant', 'Serious', 'Severe', 'Catastrophic'];
        ['potential', 'likelihood'].forEach(type => {
            const slider = this.modal.querySelector(`#harm-${type}`);
            const valueEl = this.modal.querySelector(`#harm-${type}-value`);
            slider.addEventListener('input', () => {
                const val = parseInt(slider.value, 10);
                valueEl.textContent = `${val} - ${harmLabels[val]}`;
                this.updateHarmTableHighlights();
            });
        });

        // Table cell click handlers
        const table = this.modal.querySelector('#harm-reference-table');
        table.querySelectorAll('tbody tr').forEach(row => {
            const level = parseInt(row.dataset.level, 10);

            // Click on level cell or potential cell sets potential slider
            row.querySelector('.level-cell').addEventListener('click', () => {
                if (this.readOnly) {
                    return;
                }
                const slider = this.modal.querySelector('#harm-potential');
                slider.value = level;
                slider.dispatchEvent(new Event('input'));
            });
            row.querySelector('.potential-cell').addEventListener('click', () => {
                if (this.readOnly) {
                    return;
                }
                const slider = this.modal.querySelector('#harm-potential');
                slider.value = level;
                slider.dispatchEvent(new Event('input'));
            });

            // Click on likelihood cell sets likelihood slider
            row.querySelector('.likelihood-cell').addEventListener('click', () => {
                if (this.readOnly) {
                    return;
                }
                const slider = this.modal.querySelector('#harm-likelihood');
                slider.value = level;
                slider.dispatchEvent(new Event('input'));
            });
        });

        // Comment input updates save button
        this.modal.querySelector('#annotation-comment').addEventListener('input', () => {
            this.updateSaveButtonState();
        });

        // Close on backdrop click
        this.modal.addEventListener('click', (e) => {
            if (e.target === this.modal) {
                this.closeModal();
            }
        });
    }

    /**
     * Update save button enabled state
     */
    updateSaveButtonState() {
        const selectedType = this.modal.querySelector('.annotation-type-option.selected');
        const comment = this.modal.querySelector('#annotation-comment').value.trim();
        const saveBtn = this.modal.querySelector('#annotation-save');
        if (this.readOnly) {
            saveBtn.disabled = true;
            return;
        }
        saveBtn.disabled = !selectedType || !comment;
    }

    /**
     * Update harm reference table highlights based on slider values
     */
    updateHarmTableHighlights() {
        const potentialVal = parseInt(this.modal.querySelector('#harm-potential').value, 10);
        const likelihoodVal = parseInt(this.modal.querySelector('#harm-likelihood').value, 10);
        const table = this.modal.querySelector('#harm-reference-table');

        if (!table) return;

        // Clear existing highlights
        table.querySelectorAll('td').forEach(cell => {
            cell.classList.remove('highlight-potential', 'highlight-likelihood');
        });

        // Highlight the corresponding row cells
        const potentialRow = table.querySelector(`tr[data-level="${potentialVal}"]`);
        const likelihoodRow = table.querySelector(`tr[data-level="${likelihoodVal}"]`);

        if (potentialRow) {
            potentialRow.querySelector('.level-cell').classList.add('highlight-potential');
            potentialRow.querySelector('.potential-cell').classList.add('highlight-potential');
        }

        if (likelihoodRow) {
            likelihoodRow.querySelector('.level-cell').classList.add('highlight-likelihood');
            likelihoodRow.querySelector('.likelihood-cell').classList.add('highlight-likelihood');
        }
    }

    /**
     * Enable annotation mode
     */
    enableAnnotationMode(enabled) {
        if (this.readOnly) {
            this.annotationModeEnabled = false;
            this.hideToolbar();
            return;
        }
        this.annotationModeEnabled = enabled;
        if (!enabled) {
            this.hideToolbar();
        }
    }

    /**
     * Attach to iframe
     */
    attachToIframe(iframe) {
        this.iframe = iframe;

        // Wait for iframe to load
        iframe.addEventListener('load', () => {
            this.setupIframeListeners();
            this.applyAnnotationsToDocument();
        });

        // If already loaded
        if (iframe.contentDocument && iframe.contentDocument.readyState === 'complete') {
            this.setupIframeListeners();
            this.applyAnnotationsToDocument();
        }
    }

    setSummaryPart(summaryPart) {
        if (summaryPart === this.summaryPart) {
            return;
        }
        this.summaryPart = summaryPart || null;
        this.loadAnnotations();
    }

    getContentElement(doc) {
        if (!doc) {
            return null;
        }
        if (this.contentId) {
            const byId = doc.getElementById(this.contentId);
            if (byId) {
                return byId;
            }
        }
        if (this.contentSelector) {
            const bySelector = doc.querySelector(this.contentSelector);
            if (bySelector) {
                return bySelector;
            }
        }
        return doc.querySelector('[data-encounter]') || doc.body;
    }

    /**
     * Setup listeners on iframe
     */
    setupIframeListeners() {
        if (!this.iframe || !this.iframe.contentDocument) return;

        const doc = this.iframe.contentDocument;

        if (!this.readOnly) {
            // Listen for text selection
            doc.addEventListener('mouseup', (e) => {
                if (this.annotationModeEnabled) {
                    setTimeout(() => this.handleSelection(e), 10);
                }
            });

            // Listen for annotation clicks (for editing)
            doc.addEventListener('click', (e) => {
                if (e.target.classList.contains('annotation-highlight')) {
                    const annotationId = e.target.dataset.annotationId;
                    if (annotationId) {
                        this.editAnnotation(parseInt(annotationId, 10));
                    }
                }
            });
        }
        if (this.readOnly) {
            doc.addEventListener('click', (e) => {
                if (e.target.classList.contains('annotation-highlight')) {
                    const annotationId = e.target.dataset.annotationId;
                    if (annotationId) {
                        this.editAnnotation(parseInt(annotationId, 10));
                    }
                }
            });
        }

        // Inject annotation highlight styles
        const style = doc.createElement('style');
        style.textContent = `
            .annotation-highlight {
                cursor: pointer;
                border-radius: 2px;
                padding: 1px 0;
            }
            .annotation-highlight:hover {
                filter: brightness(0.95);
            }
            .annotation-highlight.inaccuracy { background-color: #fecaca; }
            .annotation-highlight.omission { background-color: #bfdbfe; }
        `;
        doc.head.appendChild(style);
    }

    /**
     * Handle text selection
     */
    handleSelection(e) {
        if (this.readOnly) {
            this.hideToolbar();
            return;
        }
        if (!this.iframe || !this.iframe.contentDocument) return;

        const selection = this.iframe.contentWindow.getSelection();
        if (!selection || selection.isCollapsed || !selection.toString().trim()) {
            this.hideToolbar();
            return;
        }

        this.selectedText = selection.toString().trim();
        this.selectedRange = selection.getRangeAt(0).cloneRange();

        // Calculate position
        const rect = this.selectedRange.getBoundingClientRect();
        const iframeRect = this.iframe.getBoundingClientRect();

        const toolbarX = iframeRect.left + rect.left + (rect.width / 2);
        const toolbarY = iframeRect.top + rect.top - 10;

        this.showToolbar(toolbarX, toolbarY);
    }

    /**
     * Show toolbar
     */
    showToolbar(x, y) {
        this.toolbar.style.display = 'block';

        const toolbarRect = this.toolbar.getBoundingClientRect();
        let left = x - (toolbarRect.width / 2);
        let top = y - toolbarRect.height;

        left = Math.max(10, Math.min(left, window.innerWidth - toolbarRect.width - 10));
        top = Math.max(10, top);

        this.toolbar.style.left = `${left}px`;
        this.toolbar.style.top = `${top}px`;
    }

    /**
     * Hide toolbar
     */
    hideToolbar() {
        this.toolbar.style.display = 'none';
    }

    /**
     * Get selection offsets for annotations.
     */
    getSelectionOffsets() {
        if (!this.selectedRange || !this.iframe || !this.iframe.contentDocument) return null;

        const doc = this.iframe.contentDocument;
        const content = this.getContentElement(doc);
        if (!content) {
            return null;
        }

        const startRange = doc.createRange();
        startRange.setStart(content, 0);
        startRange.setEnd(this.selectedRange.startContainer, this.selectedRange.startOffset);

        const endRange = doc.createRange();
        endRange.setStart(content, 0);
        endRange.setEnd(this.selectedRange.endContainer, this.selectedRange.endOffset);

        const startOffset = startRange.toString().length;
        const endOffset = endRange.toString().length;

        if (endOffset < startOffset) {
            return { start: endOffset, end: startOffset };
        }

        return { start: startOffset, end: endOffset };
    }

    /**
     * Clear selection
     */
    clearSelection() {
        if (this.iframe && this.iframe.contentWindow) {
            this.iframe.contentWindow.getSelection().removeAllRanges();
        }
        this.selectedRange = null;
        this.selectedText = '';
    }

    /**
     * Open modal for new or existing annotation
     */
    openModal(annotation, defaultType = 'inaccuracy') {
        if (this.readOnly && !annotation) {
            return;
        }
        const titleEl = this.modal.querySelector('#annotation-modal-title');
        const textEl = this.modal.querySelector('#annotation-selected-text');
        const commentEl = this.modal.querySelector('#annotation-comment');
        const deleteBtn = this.modal.querySelector('#annotation-delete');
        const potentialSlider = this.modal.querySelector('#harm-potential');
        const likelihoodSlider = this.modal.querySelector('#harm-likelihood');
        const saveBtn = this.modal.querySelector('#annotation-save');

        if (annotation) {
            // Editing existing annotation
            titleEl.textContent = this.readOnly ? 'View Annotation' : 'Edit Annotation';
            textEl.textContent = annotation.selected_text || '[No text selected]';
            commentEl.value = annotation.comment_text || '';
            potentialSlider.value = annotation.harm_potential || 0;
            likelihoodSlider.value = annotation.harm_likelihood || 0;
            deleteBtn.style.display = this.readOnly ? 'none' : 'block';
            this.currentEditAnnotationId = annotation.annotation_id;

            // Select type
            this.modal.querySelectorAll('.annotation-type-option').forEach(opt => {
                opt.classList.toggle('selected', opt.dataset.type === annotation.issue_type);
            });
        } else {
            // Creating new annotation
            titleEl.textContent = 'Add Annotation';
            textEl.textContent = this.selectedText || '[No text selected]';
            commentEl.value = '';
            potentialSlider.value = 0;
            likelihoodSlider.value = 0;
            deleteBtn.style.display = 'none';
            this.currentEditAnnotationId = null;

            // Select default type
            this.modal.querySelectorAll('.annotation-type-option').forEach(opt => {
                opt.classList.toggle('selected', opt.dataset.type === defaultType);
            });
        }

        // Trigger slider value updates
        potentialSlider.dispatchEvent(new Event('input'));
        likelihoodSlider.dispatchEvent(new Event('input'));

        this.updateSaveButtonState();
        this.updateHarmTableHighlights();
        this.modal.classList.add('open');
        if (this.readOnly) {
            commentEl.blur();
            commentEl.setAttribute('disabled', 'disabled');
            potentialSlider.setAttribute('disabled', 'disabled');
            likelihoodSlider.setAttribute('disabled', 'disabled');
            saveBtn.setAttribute('disabled', 'disabled');
            deleteBtn.setAttribute('disabled', 'disabled');
            this.modal.querySelectorAll('.annotation-type-option').forEach(opt => {
                opt.classList.add('readonly');
                opt.setAttribute('aria-disabled', 'true');
            });
        } else {
            commentEl.removeAttribute('disabled');
            potentialSlider.removeAttribute('disabled');
            likelihoodSlider.removeAttribute('disabled');
            saveBtn.removeAttribute('disabled');
            deleteBtn.removeAttribute('disabled');
            this.modal.querySelectorAll('.annotation-type-option').forEach(opt => {
                opt.classList.remove('readonly');
                opt.removeAttribute('aria-disabled');
            });
            commentEl.focus();
        }
        this.hideToolbar();
    }

    /**
     * Close modal
     */
    closeModal() {
        this.modal.classList.remove('open');
        this.currentEditAnnotationId = null;
        this.clearSelection();
    }

    /**
     * Save from modal
     */
    async saveFromModal() {
        if (this.readOnly) {
            this.closeModal();
            return;
        }
        const selectedType = this.modal.querySelector('.annotation-type-option.selected');
        if (!selectedType) return;

        const issueType = selectedType.dataset.type;
        const commentText = this.modal.querySelector('#annotation-comment').value.trim();
        const harmPotential = parseInt(this.modal.querySelector('#harm-potential').value, 10);
        const harmLikelihood = parseInt(this.modal.querySelector('#harm-likelihood').value, 10);

        if (!commentText) {
            alert('Please provide an explanation.');
            return;
        }

        if (this.currentEditAnnotationId) {
            // Update existing
            await this.updateAnnotation(this.currentEditAnnotationId, {
                issue_type: issueType,
                comment_text: commentText,
                harm_potential: harmPotential,
                harm_likelihood: harmLikelihood
            });
        } else {
            // Create new
            await this.createAnnotation(issueType, commentText, harmPotential, harmLikelihood);
        }

        this.closeModal();
    }

    /**
     * Create new annotation
     */
    async createAnnotation(issueType, commentText, harmPotential, harmLikelihood) {
        if (this.readOnly) return;
        const offsets = this.getSelectionOffsets();

        try {
        const response = await fetch('/api/annotations', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                encounter_number: this.encounterNumber,
                summary_label: this.summaryLabel,
                summary_part: this.summaryPart,
                issue_type: issueType,
                comment_text: commentText,
                harm_potential: harmPotential,
                    harm_likelihood: harmLikelihood,
                    selection_start: offsets ? offsets.start : null,
                    selection_end: offsets ? offsets.end : null,
                    selected_text: this.selectedText || null
                })
            });

            if (response.ok) {
                const data = await response.json();
                this.annotations.push(data.annotation);
                this.applyAnnotationsToDocument();
                this.onAnnotationsChange(this.annotations);
            }
        } catch (error) {
            console.error('Failed to create annotation:', error);
        }
    }

    /**
     * Update existing annotation
     */
    async updateAnnotation(annotationId, updates) {
        if (this.readOnly) return;
        try {
            const response = await fetch(`/api/annotations/${annotationId}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(updates)
            });

            if (response.ok) {
                const annotation = this.annotations.find(a => a.annotation_id === annotationId);
                if (annotation) {
                    Object.assign(annotation, updates);
                }
                this.applyAnnotationsToDocument();
                this.onAnnotationsChange(this.annotations);
            }
        } catch (error) {
            console.error('Failed to update annotation:', error);
        }
    }

    /**
     * Delete from modal
     */
    async deleteFromModal() {
        if (this.readOnly) {
            this.closeModal();
            return;
        }
        if (!this.currentEditAnnotationId) return;

        if (confirm('Delete this annotation?')) {
            await this.deleteAnnotation(this.currentEditAnnotationId);
            this.closeModal();
        }
    }

    /**
     * Delete annotation
     */
    async deleteAnnotation(annotationId) {
        if (this.readOnly) return;
        try {
            const response = await fetch(`/api/annotations/${annotationId}`, {
                method: 'DELETE'
            });

            if (response.ok) {
                this.annotations = this.annotations.filter(a => a.annotation_id !== annotationId);
                this.applyAnnotationsToDocument();
                this.onAnnotationsChange(this.annotations);
            }
        } catch (error) {
            console.error('Failed to delete annotation:', error);
        }
    }

    /**
     * Edit existing annotation
     */
    editAnnotation(annotationId) {
        const annotation = this.annotations.find(a => a.annotation_id === annotationId);
        if (annotation) {
            this.openModal(annotation, annotation.issue_type);
        }
    }

    /**
     * Load annotations
     */
    async loadAnnotations() {
        try {
            let url = `/api/annotations?encounter_number=${this.encounterNumber}&summary_label=${encodeURIComponent(this.summaryLabel)}`;
            if (this.summaryPart) {
                url += `&summary_part=${encodeURIComponent(this.summaryPart)}`;
            }
            if (this.adminView && this.reviewDoctorId) {
                url += `&review_doctor_id=${encodeURIComponent(this.reviewDoctorId)}&admin_view=1`;
            }
            const response = await fetch(url);
            if (response.ok) {
                const data = await response.json();
                this.annotations = data.annotations || [];
                this.applyAnnotationsToDocument();
                this.onAnnotationsChange(this.annotations);
            }
        } catch (error) {
            console.error('Failed to load annotations:', error);
        }
    }

    /**
     * Apply annotations to document
     */
    applyAnnotationsToDocument() {
        if (!this.iframe || !this.iframe.contentDocument) return;

        const doc = this.iframe.contentDocument;
        const content = this.getContentElement(doc);
        if (!content) {
            return;
        }

        // Remove existing highlights
        doc.querySelectorAll('.annotation-highlight').forEach(el => {
            const text = doc.createTextNode(el.textContent);
            el.parentNode.replaceChild(text, el);
        });
        content.normalize();

        // Apply annotations with text offsets (from end to start)
        const annotationsWithOffsets = this.annotations.filter(a =>
            a.selection_start != null && a.selection_end != null
        );
        annotationsWithOffsets.sort((a, b) => b.selection_start - a.selection_start);

        for (const annotation of annotationsWithOffsets) {
            this.applyAnnotationToText(doc, content, annotation);
        }
    }

    /**
     * Apply single annotation
     */
    applyAnnotationToText(doc, container, annotation) {
        const textNodes = [];
        const walker = doc.createTreeWalker(container, NodeFilter.SHOW_TEXT, null, false);
        let currentOffset = 0;
        let node;

        while ((node = walker.nextNode())) {
            const nodeLength = node.textContent.length;
            textNodes.push({
                node: node,
                start: currentOffset,
                end: currentOffset + nodeLength
            });
            currentOffset += nodeLength;
        }

        const nodesToHighlight = textNodes.filter(nodeInfo =>
            annotation.selection_start < nodeInfo.end && annotation.selection_end > nodeInfo.start
        );

        for (let index = nodesToHighlight.length - 1; index >= 0; index--) {
            const nodeInfo = nodesToHighlight[index];
            const nodeLength = nodeInfo.node.textContent.length;
            const highlightStartInNode = Math.max(0, annotation.selection_start - nodeInfo.start);
            const highlightEndInNode = Math.min(nodeLength, annotation.selection_end - nodeInfo.start);

            if (highlightStartInNode < highlightEndInNode) {
                const range = doc.createRange();
                range.setStart(nodeInfo.node, highlightStartInNode);
                range.setEnd(nodeInfo.node, highlightEndInNode);

                const span = doc.createElement('span');
                span.className = `annotation-highlight ${annotation.issue_type}`;
                span.dataset.annotationId = annotation.annotation_id;
                span.title = `${annotation.issue_type}: ${annotation.comment_text}`;

                try {
                    range.surroundContents(span);
                } catch (error) {
                    console.warn('Could not apply annotation highlight:', error);
                    try {
                        const fragment = range.extractContents();
                        span.appendChild(fragment);
                        range.insertNode(span);
                    } catch (innerError) {
                        console.warn('Failed to apply annotation highlight manually:', innerError);
                    }
                }
            }
        }
    }

    /**
     * Scroll to annotation
     */
    scrollToAnnotation(annotationId) {
        if (!this.iframe || !this.iframe.contentDocument) return;

        const doc = this.iframe.contentDocument;
        const highlightEl = doc.querySelector(`[data-annotation-id="${annotationId}"]`);

        if (highlightEl) {
            highlightEl.scrollIntoView({ behavior: 'smooth', block: 'center' });

            // Flash effect
            highlightEl.style.transition = 'outline 0.2s';
            highlightEl.style.outline = '3px solid #0068c9';
            setTimeout(() => {
                highlightEl.style.outline = 'none';
            }, 1500);
        }
    }
}

// Export for use
window.AnnotationsManager = AnnotationsManager;
