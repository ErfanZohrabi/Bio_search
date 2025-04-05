// BioSearch Application JavaScript

document.addEventListener('DOMContentLoaded', function() {
    // DOM Elements
    const searchForm = document.getElementById('search-form');
    const searchQuery = document.getElementById('search-query');
    const resultsSection = document.getElementById('results-section');
    const loader = document.querySelector('.loader');
    const databaseTabs = document.getElementById('database-tabs');
    const databaseContent = document.getElementById('database-content');
    const exportBtn = document.getElementById('export-btn');
    const checkboxes = document.querySelectorAll('.database-checkbox');
    
    // Search Results Storage
    let currentResults = {};
    
    // Event Listeners
    searchForm.addEventListener('submit', handleSearch);
    exportBtn.addEventListener('click', exportResults);
    
    // Initialize example search terms as clickable
    document.querySelectorAll('.form-text .badge').forEach(badge => {
        badge.style.cursor = 'pointer';
        badge.addEventListener('click', () => {
            searchQuery.value = badge.textContent.split(' ')[0]; // Get first word of the badge
            searchQuery.focus();
        });
    });
    
    /**
     * Handle search form submission
     * @param {Event} e - Form submit event
     */
    function handleSearch(e) {
        e.preventDefault();
        
        // Get query and selected databases
        const query = searchQuery.value.trim();
        if (!query) {
            showToast('Please enter a search term', 'warning');
            return;
        }
        
        // Get selected databases
        const selectedDatabases = [];
        checkboxes.forEach(checkbox => {
            if (checkbox.checked) {
                selectedDatabases.push(checkbox.value);
            }
        });
        
        if (selectedDatabases.length === 0) {
            showToast('Please select at least one database', 'warning');
            return;
        }
        
        // Show loading state
        resultsSection.classList.remove('d-none');
        loader.classList.remove('d-none');
        databaseTabs.innerHTML = '';
        databaseContent.innerHTML = '';
        
        // Scroll to results section
        resultsSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
        
        // Prepare form data
        const formData = new FormData();
        formData.append('query', query);
        selectedDatabases.forEach(db => {
            formData.append('databases', db);
        });
        
        // Send search request
        fetch('/search', {
            method: 'POST',
            body: formData
        })
        .then(response => {
            if (!response.ok) {
                throw new Error('Network response was not ok');
            }
            return response.json();
        })
        .then(data => {
            currentResults = data;
            displayResults(data);
        })
        .catch(error => {
            console.error('Error:', error);
            displayError('An error occurred while searching. Please try again.');
        })
        .finally(() => {
            loader.classList.add('d-none');
        });
    }
    
    /**
     * Display search results in the UI
     * @param {Object} results - Search results from the API
     */
    function displayResults(results) {
        // Check if we have any results
        if (Object.keys(results).length === 0) {
            displayError('No results found. Try a different search term or select different databases.');
            return;
        }
        
        // Generate tabs and content for each database
        let isFirstTab = true;
        let tabsHtml = '';
        let contentHtml = '';
        
        for (const [database, dbResults] of Object.entries(results)) {
            // Skip if there's an error or no results
            if (dbResults.error || (Array.isArray(dbResults) && dbResults.length === 0)) {
                continue;
            }
            
            const dbId = database.toLowerCase().replace(/\s+/g, '-');
            const isActive = isFirstTab ? 'active' : '';
            const dbIcon = getDbIcon(database);
            
            // Add tab
            tabsHtml += `
                <li class="nav-item" role="presentation">
                    <button class="nav-link ${isActive}" id="${dbId}-tab" data-bs-toggle="tab"
                            data-bs-target="#${dbId}-content" type="button" role="tab"
                            aria-controls="${dbId}-content" aria-selected="${isFirstTab}">
                        <span class="badge badge-${dbId} me-1">${dbIcon}</span>
                        ${database} <span class="badge bg-light text-dark">${Array.isArray(dbResults) ? dbResults.length : 0}</span>
                    </button>
                </li>
            `;
            
            // Add content
            contentHtml += `
                <div class="tab-pane fade show ${isActive}" id="${dbId}-content" role="tabpanel"
                     aria-labelledby="${dbId}-tab">
                    ${generateResultsHtml(dbResults, database)}
                </div>
            `;
            
            if (isFirstTab) {
                isFirstTab = false;
            }
        }
        
        // If no valid results were found
        if (tabsHtml === '') {
            displayError('No results found. Try a different search term or select different databases.');
            return;
        }
        
        // Set the HTML
        databaseTabs.innerHTML = tabsHtml;
        databaseContent.innerHTML = contentHtml;
        
        // Make result items clickable to toggle checkboxes
        document.querySelectorAll('.result-item').forEach(item => {
            item.addEventListener('click', function(e) {
                // Skip if click was on a link or checkbox directly
                if (e.target.tagName === 'A' || e.target.tagName === 'INPUT' || 
                    e.target.closest('a') || e.target.closest('.form-check-input')) {
                    return;
                }
                
                // Find the checkbox within this item and toggle it
                const checkbox = this.querySelector('.form-check-input');
                if (checkbox) {
                    checkbox.checked = !checkbox.checked;
                }
            });
        });
        
        // Show success toast
        showToast(`Search completed. Found results in ${Object.keys(results).length} database(s).`, 'success');
        
        // Initialize tooltips
        initializeTooltips();
    }
    
    /**
     * Generate HTML for a specific database's results
     * @param {Array|Object} dbResults - Results for a specific database
     * @param {String} database - Database name
     * @returns {String} HTML string
     */
    function generateResultsHtml(dbResults, database) {
        if (dbResults.error) {
            return `<div class="alert alert-danger">
                <i class="fas fa-exclamation-triangle me-2"></i>${dbResults.error}
            </div>`;
        }
        
        if (!Array.isArray(dbResults) || dbResults.length === 0) {
            return `<div class="alert alert-info">
                <i class="fas fa-info-circle me-2"></i>No results found in ${database}.
            </div>`;
        }
        
        let html = '';
        const dbClass = database.toLowerCase().replace(/\s+/g, '-');
        
        dbResults.forEach((result, index) => {
            if (database === 'NCBI') {
                html += `
                    <div class="result-item" data-id="${result.id}" style="animation-delay: ${index * 0.05}s;">
                        <div class="d-flex justify-content-between align-items-start">
                            <div class="form-check">
                                <input class="form-check-input result-checkbox" type="checkbox" value="${result.id}" id="result-${result.id}">
                                <label class="form-check-label" for="result-${result.id}">
                                    <h3 class="result-title h5">${result.name || 'Unknown'}</h3>
                                </label>
                            </div>
                            <span class="badge badge-${dbClass}"><i class="fas fa-dna"></i></span>
                        </div>
                        <div class="result-meta">
                            <span class="result-meta-item" data-bs-toggle="tooltip" title="NCBI Gene ID">
                                <i class="fas fa-fingerprint"></i> ${result.id}
                            </span>
                            <span class="result-meta-item" data-bs-toggle="tooltip" title="Organism">
                                <i class="fas fa-leaf"></i> ${result.organism || 'N/A'}
                            </span>
                        </div>
                        <p>${result.description || 'No description available.'}</p>
                        <a href="${result.url}" target="_blank" class="result-link">
                            View on NCBI <i class="fas fa-external-link-alt"></i>
                        </a>
                    </div>
                `;
            } else if (database === 'PubMed') {
                html += `
                    <div class="result-item" data-id="${result.id}" style="animation-delay: ${index * 0.05}s;">
                        <div class="d-flex justify-content-between align-items-start">
                            <div class="form-check">
                                <input class="form-check-input result-checkbox" type="checkbox" value="${result.id}" id="result-${result.id}">
                                <label class="form-check-label" for="result-${result.id}">
                                    <h3 class="result-title h5">${result.title || 'Unknown'}</h3>
                                </label>
                            </div>
                            <span class="badge badge-${dbClass}"><i class="fas fa-book-medical"></i></span>
                        </div>
                        <div class="result-meta">
                            <span class="result-meta-item" data-bs-toggle="tooltip" title="PubMed ID">
                                <i class="fas fa-hashtag"></i> ${result.id}
                            </span>
                            <span class="result-meta-item" data-bs-toggle="tooltip" title="Authors">
                                <i class="fas fa-users"></i> ${result.authors || 'N/A'}
                            </span>
                            <span class="result-meta-item" data-bs-toggle="tooltip" title="Journal">
                                <i class="fas fa-book"></i> ${result.journal || 'N/A'}
                            </span>
                            <span class="result-meta-item" data-bs-toggle="tooltip" title="Publication Date">
                                <i class="fas fa-calendar-alt"></i> ${result.pubdate || 'N/A'}
                            </span>
                        </div>
                        <a href="${result.url}" target="_blank" class="result-link">
                            View on PubMed <i class="fas fa-external-link-alt"></i>
                        </a>
                    </div>
                `;
            } else if (database === 'UniProt') {
                html += `
                    <div class="result-item" data-id="${result.id}" style="animation-delay: ${index * 0.05}s;">
                        <div class="d-flex justify-content-between align-items-start">
                            <div class="form-check">
                                <input class="form-check-input result-checkbox" type="checkbox" value="${result.id}" id="result-${result.id}">
                                <label class="form-check-label" for="result-${result.id}">
                                    <h3 class="result-title h5">${result.name || 'Unknown'}</h3>
                                </label>
                            </div>
                            <span class="badge badge-${dbClass}"><i class="fas fa-atom"></i></span>
                        </div>
                        <div class="result-meta">
                            <span class="result-meta-item" data-bs-toggle="tooltip" title="UniProt Accession">
                                <i class="fas fa-id-card"></i> ${result.id}
                            </span>
                            <span class="result-meta-item" data-bs-toggle="tooltip" title="Gene">
                                <i class="fas fa-dna"></i> ${result.gene || 'N/A'}
                            </span>
                            <span class="result-meta-item" data-bs-toggle="tooltip" title="Organism">
                                <i class="fas fa-leaf"></i> ${result.organism || 'N/A'}
                            </span>
                        </div>
                        <p>${result.description || 'No description available.'}</p>
                        <a href="${result.url}" target="_blank" class="result-link">
                            View on UniProt <i class="fas fa-external-link-alt"></i>
                        </a>
                    </div>
                `;
            } else if (database === 'DrugBank') {
                html += `
                    <div class="result-item" data-id="${result.id}" style="animation-delay: ${index * 0.05}s;">
                        <div class="d-flex justify-content-between align-items-start">
                            <div class="form-check">
                                <input class="form-check-input result-checkbox" type="checkbox" value="${result.id}" id="result-${result.id}">
                                <label class="form-check-label" for="result-${result.id}">
                                    <h3 class="result-title h5">${result.name || 'Unknown'}</h3>
                                </label>
                            </div>
                            <span class="badge badge-${dbClass}"><i class="fas fa-prescription-bottle-alt"></i></span>
                        </div>
                        <div class="result-meta">
                            <span class="result-meta-item" data-bs-toggle="tooltip" title="DrugBank ID">
                                <i class="fas fa-id-card"></i> ${result.id}
                            </span>
                            <span class="result-meta-item" data-bs-toggle="tooltip" title="Type">
                                <i class="fas fa-tag"></i> ${result.type || 'N/A'}
                            </span>
                        </div>
                        <p>${result.description || 'No description available.'}</p>
                        <a href="${result.url}" target="_blank" class="result-link">
                            View on DrugBank <i class="fas fa-external-link-alt"></i>
                        </a>
                    </div>
                `;
            } else if (database === 'PDB') {
                html += `
                    <div class="result-item" style="animation-delay: ${index * 0.05}s;">
                        <div class="d-flex justify-content-between align-items-start">
                            <div>
                                <h3 class="result-title h5">${result.name || 'Unknown'}</h3>
                                <div class="result-meta">
                                    <span class="result-meta-item" data-bs-toggle="tooltip" title="PDB ID">
                                        <i class="fas fa-cube"></i> ${result.id}
                                    </span>
                                    ${result.description ? `
                                    <span class="result-meta-item" data-bs-toggle="tooltip" title="Description">
                                        <i class="fas fa-info-circle"></i> ${result.description}
                                    </span>` : ''}
                                </div>
                            </div>
                            <span class="badge badge-${dbClass}"><i class="fas fa-cube"></i></span>
                        </div>
                        <a href="${result.url}" target="_blank" class="result-link">
                            View on PDB <i class="fas fa-external-link-alt"></i>
                        </a>
                    </div>
                `;
            } else {
                // Generic result display for other databases
                html += `
                    <div class="result-item" style="animation-delay: ${index * 0.05}s;">
                        <div class="d-flex justify-content-between align-items-start">
                            <div>
                                <h3 class="result-title h5">${result.name || result.title || 'Unknown'}</h3>
                                <div class="result-meta">
                                    <span class="result-meta-item">
                                        <i class="fas fa-fingerprint"></i> ID: ${result.id || 'N/A'}
                                    </span>
                                </div>
                            </div>
                            <span class="badge badge-secondary">${database}</span>
                        </div>
                        ${result.description ? `<p>${result.description}</p>` : ''}
                        <a href="${result.url}" target="_blank" class="result-link">
                            View on ${database} <i class="fas fa-external-link-alt"></i>
                        </a>
                    </div>
                `;
            }
        });
        
        return html;
    }
    
    /**
     * Display error message in results section
     * @param {String} message - Error message to display
     */
    function displayError(message) {
        resultsSection.classList.remove('d-none');
        databaseTabs.innerHTML = '';
        databaseContent.innerHTML = `
            <div class="alert alert-warning">
                <i class="fas fa-exclamation-triangle me-2"></i>${message}
            </div>
        `;
        
        // Show error toast
        showToast(message, 'danger');
    }
    
    /**
     * Export results as JSON file
     */
    function exportResults() {
        if (Object.keys(currentResults).length === 0) {
            showToast('No results to export', 'warning');
            return;
        }
        
        const dataStr = JSON.stringify(currentResults, null, 2);
        const dataUri = 'data:application/json;charset=utf-8,'+ encodeURIComponent(dataStr);
        
        const exportFileName = `biosearch_results_${new Date().toISOString().slice(0, 10)}.json`;
        
        const linkElement = document.createElement('a');
        linkElement.setAttribute('href', dataUri);
        linkElement.setAttribute('download', exportFileName);
        linkElement.click();
        
        // Show success toast
        showToast('Results exported successfully', 'success');
    }
    
    /**
     * Get the appropriate icon for a database
     * @param {String} database - Database name
     * @returns {String} HTML for the icon
     */
    function getDbIcon(database) {
        const iconMap = {
            'NCBI': '<i class="fas fa-dna"></i>',
            'PubMed': '<i class="fas fa-book-medical"></i>',
            'UniProt': '<i class="fas fa-atom"></i>',
            'DrugBank': '<i class="fas fa-prescription-bottle-alt"></i>',
            'PDB': '<i class="fas fa-cube"></i>',
            'KEGG': '<i class="fas fa-project-diagram"></i>'
        };
        
        return iconMap[database] || '<i class="fas fa-database"></i>';
    }
    
    /**
     * Show a toast notification
     * @param {String} message - Message to display
     * @param {String} type - Type of notification (success, warning, danger)
     */
    function showToast(message, type) {
        // Check if toast container exists, if not create it
        let toastContainer = document.querySelector('.toast-container');
        if (!toastContainer) {
            toastContainer = document.createElement('div');
            toastContainer.className = 'toast-container position-fixed bottom-0 end-0 p-3';
            document.body.appendChild(toastContainer);
        }
        
        // Create toast
        const toastId = 'toast-' + Date.now();
        const iconMap = {
            'success': '<i class="fas fa-check-circle"></i>',
            'warning': '<i class="fas fa-exclamation-triangle"></i>',
            'danger': '<i class="fas fa-times-circle"></i>',
            'info': '<i class="fas fa-info-circle"></i>'
        };
        
        const bgColor = `bg-${type === 'danger' ? 'danger' : type}`;
        const textColor = type === 'warning' ? 'text-dark' : 'text-white';
        
        const toastHtml = `
            <div id="${toastId}" class="toast ${bgColor} ${textColor}" role="alert" aria-live="assertive" aria-atomic="true">
                <div class="toast-header ${bgColor} ${textColor}">
                    <strong class="me-auto">${iconMap[type] || ''} BioSearch</strong>
                    <button type="button" class="btn-close btn-close-white" data-bs-dismiss="toast" aria-label="Close"></button>
                </div>
                <div class="toast-body">
                    ${message}
                </div>
            </div>
        `;
        
        // Add toast to container
        toastContainer.insertAdjacentHTML('beforeend', toastHtml);
        
        // Initialize and show toast
        const toastElement = document.getElementById(toastId);
        const toast = new bootstrap.Toast(toastElement, { delay: 3000 });
        toast.show();
        
        // Remove toast after it's hidden
        toastElement.addEventListener('hidden.bs.toast', function() {
            toastElement.remove();
        });
    }
    
    /**
     * Initialize tooltips
     */
    function initializeTooltips() {
        const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
        tooltipTriggerList.forEach(function(tooltipTriggerEl) {
            new bootstrap.Tooltip(tooltipTriggerEl);
        });
    }
    
    // Initialize tooltips on page load
    initializeTooltips();
}); 