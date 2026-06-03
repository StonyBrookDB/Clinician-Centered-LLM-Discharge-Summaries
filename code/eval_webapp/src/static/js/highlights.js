/**
 * Clinical Notes Highlights Manager
 * Handles text selection, highlight creation, and persistence for clinical notes.
 */

class HighlightsManager {
    constructor(options = {}) {
        this.encounterNumber = options.encounterNumber;
        this.doctorId = options.doctorId;
        this.onHighlightsChange = options.onHighlightsChange || (() => {});
        this.readOnly = options.readOnly || false;
        this.adminView = options.adminView || false;
        this.reviewDoctorId = options.reviewDoctorId || null;

        this.highlights = [];
        this.highlightsLoaded = false;  // Track if highlights have been fetched
        this.currentNoteFilename = null;
        this.iframe = null;
        this.toolbar = null;
        this.editModal = null;
        this.selectedRange = null;
        this.selectedText = '';
        this.toolbarJustShown = false;  // Flag to prevent immediate hide

        this.colors = {
            yellow: { bg: '#fef08a', label: 'Yellow' },
            green: { bg: '#bbf7d0', label: 'Green' },
            blue: { bg: '#bfdbfe', label: 'Blue' },
            pink: { bg: '#fbcfe8', label: 'Pink' },
            orange: { bg: '#fed7aa', label: 'Orange' }
        };

        this.initToolbar();
        this.initEditModal();
    }

    /**
     * Initialize floating toolbar for creating highlights
     */
    initToolbar() {
        this.toolbar = document.createElement('div');
        this.toolbar.className = 'highlight-toolbar';
        this.toolbar.innerHTML = `
            <div class="highlight-toolbar-inner">
                <span class="toolbar-label">Highlight:</span>
                ${Object.entries(this.colors).map(([color, data]) => `
                    <button class="color-btn" data-color="${color}"
                            style="background-color: ${data.bg}"
                            title="${data.label}"></button>
                `).join('')}
            </div>
        `;
        this.toolbar.style.cssText = `
            position: fixed;
            display: none;
            z-index: 10000;
            background: white;
            border: 1px solid #d1d5db;
            border-radius: 8px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            padding: 8px;
        `;

        // Add toolbar styles
        const style = document.createElement('style');
        style.textContent = `
            .highlight-toolbar-inner {
                display: flex;
                align-items: center;
                gap: 6px;
            }
            .toolbar-label {
                font-size: 12px;
                color: #6b7280;
                margin-right: 4px;
            }
            .color-btn {
                width: 24px;
                height: 24px;
                border: 2px solid #e5e7eb;
                border-radius: 4px;
                cursor: pointer;
                transition: transform 0.1s, border-color 0.1s;
            }
            .color-btn:hover {
                transform: scale(1.1);
                border-color: #9ca3af;
            }
            /* Edit modal styles */
            .highlight-edit-modal {
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
            .highlight-edit-modal.open {
                display: flex;
            }
            .highlight-edit-content {
                background: white;
                border-radius: 8px;
                padding: 1.5rem;
                max-width: 400px;
                width: 90%;
                max-height: 80vh;
                overflow-y: auto;
            }
            .highlight-edit-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 1rem;
            }
            .highlight-edit-header h3 {
                margin: 0;
                font-size: 1.1rem;
            }
            .highlight-edit-close {
                background: none;
                border: none;
                font-size: 1.5rem;
                cursor: pointer;
                color: #6b7280;
            }
            .highlight-edit-text {
                background: #f9fafb;
                border: 1px solid #e5e7eb;
                border-radius: 4px;
                padding: 0.75rem;
                margin-bottom: 1rem;
                font-size: 0.875rem;
                max-height: 100px;
                overflow-y: auto;
            }
            .highlight-edit-colors {
                display: flex;
                gap: 8px;
                margin-bottom: 1rem;
            }
            .highlight-edit-colors .color-btn {
                width: 32px;
                height: 32px;
            }
            .highlight-edit-colors .color-btn.selected {
                border-color: #374151;
                border-width: 3px;
            }
            .highlight-edit-comment {
                width: 100%;
                min-height: 80px;
                padding: 0.5rem;
                border: 1px solid #d1d5db;
                border-radius: 4px;
                font-size: 0.875rem;
                resize: vertical;
                margin-bottom: 1rem;
            }
            .highlight-edit-actions {
                display: flex;
                justify-content: space-between;
                gap: 0.5rem;
            }
            .highlight-edit-actions button {
                padding: 0.5rem 1rem;
                border-radius: 4px;
                cursor: pointer;
                font-size: 0.875rem;
            }
            .highlight-save-btn {
                background: #0068c9;
                color: white;
                border: none;
            }
            .highlight-save-btn:hover {
                background: #0054a3;
            }
            .highlight-delete-btn {
                background: #fee2e2;
                color: #991b1b;
                border: 1px solid #fecaca;
            }
            .highlight-delete-btn:hover {
                background: #fecaca;
            }
            .highlight-cancel-btn {
                background: #f3f4f6;
                border: 1px solid #d1d5db;
            }
            .highlight-cancel-btn:hover {
                background: #e5e7eb;
            }
        `;
        document.head.appendChild(style);
        document.body.appendChild(this.toolbar);

        // Color button click handlers
        this.toolbar.querySelectorAll('.color-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const color = e.target.dataset.color;
                this.createHighlight(color);
            });
        });

        // Hide toolbar when clicking outside (but not immediately after showing)
        document.addEventListener('click', (e) => {
            if (this.toolbarJustShown) {
                this.toolbarJustShown = false;
                return;
            }
            if (!this.toolbar.contains(e.target)) {
                this.hideToolbar();
            }
        });
    }

    /**
     * Initialize edit/delete modal for existing highlights
     */
    initEditModal() {
        this.editModal = document.createElement('div');
        this.editModal.className = 'highlight-edit-modal';
        this.editModal.innerHTML = `
            <div class="highlight-edit-content">
                <div class="highlight-edit-header">
                    <h3>Edit Highlight</h3>
                    <button class="highlight-edit-close">&times;</button>
                </div>
                <div class="highlight-edit-text" id="modal-selected-text"></div>
                <label style="display: block; margin-bottom: 0.5rem; font-size: 0.875rem; color: #374151;">Color:</label>
                <div class="highlight-edit-colors">
                    ${Object.entries(this.colors).map(([color, data]) => `
                        <button class="color-btn" data-color="${color}"
                                style="background-color: ${data.bg}"
                                title="${data.label}"></button>
                    `).join('')}
                </div>
                <label style="display: block; margin-bottom: 0.5rem; font-size: 0.875rem; color: #374151;">Comment (optional):</label>
                <textarea class="highlight-edit-comment" id="modal-comment" placeholder="Add a note..."></textarea>
                <div class="highlight-edit-actions">
                    <button class="highlight-delete-btn" id="modal-delete" style="display: none;">Delete</button>
                    <div style="flex: 1;"></div>
                    <button class="highlight-cancel-btn" id="modal-cancel">Cancel</button>
                    <button class="highlight-save-btn" id="modal-save">Save</button>
                </div>
            </div>
        `;
        document.body.appendChild(this.editModal);

        // Modal event handlers
        this.editModal.querySelector('.highlight-edit-close').addEventListener('click', () => this.closeEditModal());
        this.editModal.querySelector('#modal-cancel').addEventListener('click', () => this.closeEditModal());
        this.editModal.querySelector('#modal-save').addEventListener('click', () => this.saveFromModal());
        this.editModal.querySelector('#modal-delete').addEventListener('click', () => this.deleteFromModal());

        // Color selection in modal
        this.editModal.querySelectorAll('.color-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                this.editModal.querySelectorAll('.color-btn').forEach(b => b.classList.remove('selected'));
                e.target.classList.add('selected');
            });
        });

        // Close on backdrop click
        this.editModal.addEventListener('click', (e) => {
            if (e.target === this.editModal) {
                this.closeEditModal();
            }
        });
    }

    /**
     * Attach to an iframe containing clinical note HTML
     */
    attachToIframe(iframe, noteFilename) {
        this.iframe = iframe;
        this.currentNoteFilename = noteFilename;

        // Wait for iframe to load
        iframe.addEventListener('load', () => {
            this.setupIframeListeners();
            this.applyHighlightsToDocument();

            // If highlights haven't loaded yet, wait for them and retry
            if (!this.highlightsLoaded) {
                const checkHighlights = setInterval(() => {
                    if (this.highlightsLoaded) {
                        clearInterval(checkHighlights);
                        this.applyHighlightsToDocument();
                    }
                }, 50);
                // Stop checking after 5 seconds
                setTimeout(() => clearInterval(checkHighlights), 5000);
            }
        });

        // If already loaded
        if (iframe.contentDocument && iframe.contentDocument.readyState === 'complete') {
            this.setupIframeListeners();
            this.applyHighlightsToDocument();
        }
    }

    /**
     * Setup selection listeners on iframe document
     */
    setupIframeListeners() {
        if (!this.iframe || !this.iframe.contentDocument) return;

        const doc = this.iframe.contentDocument;

        if (!this.readOnly) {
            // Listen for text selection on mouseup
            doc.addEventListener('mouseup', (e) => {
                // Use timeout to ensure selection is stable
                setTimeout(() => this.handleSelection(e), 50);
            });

            // Listen for highlight clicks (for editing)
            doc.addEventListener('click', (e) => {
                if (e.target.classList.contains('user-highlight')) {
                    const highlightId = e.target.dataset.highlightId;
                    if (highlightId) {
                        this.editHighlight(parseInt(highlightId, 10));
                    }
                }
            });
        }

        // Inject highlight styles into iframe
        const style = doc.createElement('style');
        style.textContent = `
            .user-highlight {
                cursor: pointer;
                border-radius: 2px;
            }
            .user-highlight:hover {
                filter: brightness(0.95);
            }
            .user-highlight.yellow { background-color: #fef08a; }
            .user-highlight.green { background-color: #bbf7d0; }
            .user-highlight.blue { background-color: #bfdbfe; }
            .user-highlight.pink { background-color: #fbcfe8; }
            .user-highlight.orange { background-color: #fed7aa; }
        `;
        doc.head.appendChild(style);
    }

    /**
     * Handle text selection in iframe (from mouseup)
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

        // Calculate position for toolbar
        const rect = this.selectedRange.getBoundingClientRect();
        const iframeRect = this.iframe.getBoundingClientRect();

        // Position toolbar above selection
        const toolbarX = iframeRect.left + rect.left + (rect.width / 2);
        const toolbarY = iframeRect.top + rect.top - 10;

        this.showToolbar(toolbarX, toolbarY);
    }

    /**
     * Show the floating toolbar at position
     */
    showToolbar(x, y) {
        this.toolbar.style.display = 'block';
        this.toolbarJustShown = true;  // Prevent immediate hide from document click

        // Get toolbar dimensions
        const toolbarRect = this.toolbar.getBoundingClientRect();

        // Center horizontally and position above
        let left = x - (toolbarRect.width / 2);
        let top = y - toolbarRect.height;

        // Keep within viewport
        left = Math.max(10, Math.min(left, window.innerWidth - toolbarRect.width - 10));
        top = Math.max(10, top);

        this.toolbar.style.left = `${left}px`;
        this.toolbar.style.top = `${top}px`;
    }

    /**
     * Hide the floating toolbar
     */
    hideToolbar() {
        this.toolbar.style.display = 'none';
        this.selectedRange = null;
        this.selectedText = '';
    }

    /**
     * Create a new highlight
     */
    async createHighlight(color, comment = null) {
        if (this.readOnly) {
            this.hideToolbar();
            this.clearSelection();
            return;
        }
        if (!this.selectedText || !this.currentNoteFilename) {
            this.hideToolbar();
            return;
        }

        // Calculate text offsets
        const offsets = this.getSelectionOffsets();
        if (!offsets) {
            this.hideToolbar();
            return;
        }

        try {
            const response = await fetch('/api/highlights', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    encounter_number: this.encounterNumber,
                    note_filename: this.currentNoteFilename,
                    start_offset: offsets.start,
                    end_offset: offsets.end,
                    selected_text: this.selectedText,
                    color: color,
                    comment: comment
                })
            });

            if (response.ok) {
                const data = await response.json();
                this.highlights.push(data.highlight);
                this.applyHighlightsToDocument();
                this.onHighlightsChange(this.highlights);
            }
        } catch (error) {
            console.error('Failed to create highlight:', error);
        }

        this.hideToolbar();
        this.clearSelection();
    }

    /**
     * Get character offsets for current selection.
     * Since content is now plain text in a single container, offset calculation is simple.
     */
    getSelectionOffsets() {
        if (!this.selectedRange || !this.iframe || !this.iframe.contentDocument) return null;

        const doc = this.iframe.contentDocument;
        // Look for the document content container, fall back to body
        const container = doc.querySelector('.document-content') || doc.body;

        // Calculate offsets using selection start/end to avoid whitespace normalization issues.
        const startRange = doc.createRange();
        startRange.setStart(container, 0);
        startRange.setEnd(this.selectedRange.startContainer, this.selectedRange.startOffset);

        const endRange = doc.createRange();
        endRange.setStart(container, 0);
        endRange.setEnd(this.selectedRange.endContainer, this.selectedRange.endOffset);

        const startOffset = startRange.toString().length;
        const endOffset = endRange.toString().length;

        if (endOffset < startOffset) {
            return { start: endOffset, end: startOffset };
        }

        return { start: startOffset, end: endOffset };
    }

    /**
     * Clear text selection in iframe
     */
    clearSelection() {
        if (this.iframe && this.iframe.contentWindow) {
            this.iframe.contentWindow.getSelection().removeAllRanges();
        }
    }

    /**
     * Load highlights for current encounter
     */
    async loadHighlights() {
        try {
            let url = `/api/highlights?encounter_number=${this.encounterNumber}`;
            if (this.adminView && this.reviewDoctorId) {
                url += `&review_doctor_id=${encodeURIComponent(this.reviewDoctorId)}&admin_view=1`;
            }
            const response = await fetch(url);
            if (response.ok) {
                const data = await response.json();
                this.highlights = data.highlights || [];
                this.highlightsLoaded = true;
                this.onHighlightsChange(this.highlights);
                // Apply highlights in case iframe is already loaded
                this.applyHighlightsToDocument();
            }
        } catch (error) {
            console.error('Failed to load highlights:', error);
        }
    }

    /**
     * Apply highlights to the current iframe document
     */
    applyHighlightsToDocument() {
        if (!this.iframe || !this.iframe.contentDocument || !this.currentNoteFilename) return;

        const doc = this.iframe.contentDocument;
        // Look for the document content container, fall back to body
        const container = doc.querySelector('.document-content') || doc.body;

        // Always clear any existing highlight spans first. This ensures deleted highlights
        // disappear immediately even when the current note has zero remaining highlights.
        doc.querySelectorAll('.user-highlight').forEach((el) => {
            const parent = el.parentNode;
            if (!parent) return;
            while (el.firstChild) {
                parent.insertBefore(el.firstChild, el);
            }
            parent.removeChild(el);
        });
        container.normalize();

        // Get highlights for current note
        const noteHighlights = this.highlights.filter(h => h.note_filename === this.currentNoteFilename);
        if (noteHighlights.length === 0) return;

        // Sort by offset (apply from end to start to preserve offsets)
        noteHighlights.sort((a, b) => b.start_offset - a.start_offset);

        // Apply each highlight
        for (const highlight of noteHighlights) {
            this.applyHighlightToText(doc, highlight);
        }
    }

    /**
     * Apply a single highlight to the document
     * Handles highlights that span multiple text nodes
     */
    applyHighlightToText(doc, highlight) {
        // Look for the document content container, fall back to body
        const container = doc.querySelector('.document-content') || doc.body;

        // Collect all text nodes and their offsets first
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

        // Find all text nodes that intersect the highlight and apply to each
        // Process in reverse order to avoid offset issues when modifying DOM
        const nodesToHighlight = textNodes.filter(n =>
            highlight.start_offset < n.end && highlight.end_offset > n.start
        );

        // Process in reverse order
        for (let i = nodesToHighlight.length - 1; i >= 0; i--) {
            const nodeInfo = nodesToHighlight[i];
            const node = nodeInfo.node;
            const nodeLength = node.textContent.length;

            const highlightStartInNode = Math.max(0, highlight.start_offset - nodeInfo.start);
            const highlightEndInNode = Math.min(nodeLength, highlight.end_offset - nodeInfo.start);

            if (highlightStartInNode < highlightEndInNode) {
                // Split the text node and wrap the highlighted portion
                const range = doc.createRange();
                range.setStart(node, highlightStartInNode);
                range.setEnd(node, highlightEndInNode);

                const span = doc.createElement('span');
                span.className = `user-highlight ${highlight.color}`;
                span.dataset.highlightId = highlight.highlight_id;
                if (highlight.comment) {
                    span.title = highlight.comment;
                }

                try {
                    range.surroundContents(span);
                } catch (e) {
                    // If surroundContents fails, try manual approach
                    console.warn('surroundContents failed, trying manual wrap:', e);
                    try {
                        const fragment = range.extractContents();
                        span.appendChild(fragment);
                        range.insertNode(span);
                    } catch (e2) {
                        console.warn('Could not apply highlight to node:', e2);
                    }
                }
            }
        }
    }

    /**
     * Open edit modal for an existing highlight
     */
    editHighlight(highlightId) {
        if (this.readOnly) return;
        const highlight = this.highlights.find(h => h.highlight_id === highlightId);
        if (!highlight) return;

        this.currentEditHighlightId = highlightId;
        this.openEditModal(highlight, highlight.color);
    }

    /**
     * Open the edit modal
     */
    openEditModal(highlight, defaultColor) {
        if (this.readOnly) return;
        const textEl = this.editModal.querySelector('#modal-selected-text');
        const commentEl = this.editModal.querySelector('#modal-comment');
        const deleteBtn = this.editModal.querySelector('#modal-delete');
        const headerEl = this.editModal.querySelector('h3');

        if (highlight) {
            // Editing existing highlight
            headerEl.textContent = 'Edit Highlight';
            textEl.textContent = highlight.selected_text;
            commentEl.value = highlight.comment || '';
            deleteBtn.style.display = 'block';
            this.currentEditHighlightId = highlight.highlight_id;
        } else {
            // Creating new highlight with comment
            headerEl.textContent = 'Add Highlight';
            textEl.textContent = this.selectedText;
            commentEl.value = '';
            deleteBtn.style.display = 'none';
            this.currentEditHighlightId = null;
        }

        // Select color
        this.editModal.querySelectorAll('.color-btn').forEach(btn => {
            btn.classList.toggle('selected', btn.dataset.color === defaultColor);
        });

        this.editModal.classList.add('open');
        commentEl.focus();
    }

    /**
     * Close the edit modal
     */
    closeEditModal() {
        this.editModal.classList.remove('open');
        this.currentEditHighlightId = null;
        this.hideToolbar();
    }

    /**
     * Save from modal (create or update)
     */
    async saveFromModal() {
        if (this.readOnly) {
            this.closeEditModal();
            return;
        }
        const selectedColorBtn = this.editModal.querySelector('.color-btn.selected');
        const color = selectedColorBtn ? selectedColorBtn.dataset.color : 'yellow';
        const comment = this.editModal.querySelector('#modal-comment').value.trim() || null;

        if (this.currentEditHighlightId) {
            // Update existing highlight
            await this.updateHighlight(this.currentEditHighlightId, color, comment);
        } else {
            // Create new highlight
            await this.createHighlight(color, comment);
        }

        this.closeEditModal();
    }

    /**
     * Update an existing highlight
     */
    async updateHighlight(highlightId, color, comment) {
        if (this.readOnly) return;
        try {
            const response = await fetch(`/api/highlights/${highlightId}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ color, comment })
            });

            if (response.ok) {
                // Update local data
                const highlight = this.highlights.find(h => h.highlight_id === highlightId);
                if (highlight) {
                    highlight.color = color;
                    highlight.comment = comment;
                }
                this.applyHighlightsToDocument();
                this.onHighlightsChange(this.highlights);
            }
        } catch (error) {
            console.error('Failed to update highlight:', error);
        }
    }

    /**
     * Delete from modal
     */
    async deleteFromModal() {
        if (this.readOnly) {
            this.closeEditModal();
            return;
        }
        if (!this.currentEditHighlightId) return;

        if (confirm('Delete this highlight?')) {
            await this.deleteHighlight(this.currentEditHighlightId);
            this.closeEditModal();
        }
    }

    /**
     * Delete a highlight
     */
    async deleteHighlight(highlightId) {
        if (this.readOnly) return;
        try {
            const response = await fetch(`/api/highlights/${highlightId}`, {
                method: 'DELETE'
            });

            if (response.ok) {
                const targetId = Number(highlightId);
                this.highlights = this.highlights.filter(h => Number(h.highlight_id) !== targetId);
                this.applyHighlightsToDocument();
                this.onHighlightsChange(this.highlights);
            }
        } catch (error) {
            console.error('Failed to delete highlight:', error);
        }
    }

    /**
     * Navigate to a highlight (for jump-to-source from sidebar)
     */
    jumpToHighlight(highlightId) {
        const highlight = this.highlights.find(h => h.highlight_id === highlightId);
        if (!highlight) return null;

        return {
            noteFilename: highlight.note_filename,
            highlightId: highlightId
        };
    }

    /**
     * Scroll to and flash a highlight in the current document
     */
    scrollToHighlight(highlightId) {
        if (!this.iframe || !this.iframe.contentDocument) return;

        const doc = this.iframe.contentDocument;
        const highlightEl = doc.querySelector(`[data-highlight-id="${highlightId}"]`);

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

// Export for use in documents page
window.HighlightsManager = HighlightsManager;
