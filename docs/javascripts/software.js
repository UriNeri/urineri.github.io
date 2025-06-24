function initializeSoftwarePage() {
    const repoContainer = document.getElementById('repo-container');
    if (!repoContainer) return;

    // Check if already initialized to prevent duplicate event listeners
    if (repoContainer.dataset.initialized === 'true') return;
    repoContainer.dataset.initialized = 'true';

    const repos = Array.from(repoContainer.children);
    let currentSort = 'stars';
    let sortDirection = 'desc';

    function sortRepos(criteria) {
        const buttons = document.querySelectorAll('.sort-button');
        buttons.forEach(btn => {
            if (btn.dataset.sort === criteria) {
                btn.classList.add('active');
            } else {
                btn.classList.remove('active');
            }
        });

        if (currentSort === criteria) {
            sortDirection = sortDirection === 'desc' ? 'asc' : 'desc';
        } else {
            currentSort = criteria;
            sortDirection = 'desc';
        }

        // Get fresh list of repos each time in case DOM changed
        const currentRepos = Array.from(repoContainer.children);
        
        currentRepos.sort((a, b) => {
            let aValue, bValue;
            
            switch(criteria) {
                case 'stars':
                    aValue = parseInt(a.dataset.stars) || 0;
                    bValue = parseInt(b.dataset.stars) || 0;
                    break;
                case 'date':
                    aValue = new Date(a.dataset.date);
                    bValue = new Date(b.dataset.date);
                    break;
                case 'language':
                    aValue = a.dataset.language || '';
                    bValue = b.dataset.language || '';
                    return sortDirection === 'desc' 
                        ? bValue.localeCompare(aValue)
                        : aValue.localeCompare(bValue);
            }

            return sortDirection === 'desc' ? bValue - aValue : aValue - bValue;
        });

        // Clear container and re-append sorted repos
        repoContainer.innerHTML = '';
        currentRepos.forEach(repo => repoContainer.appendChild(repo));
    }

    // Add event listeners to buttons
    document.querySelectorAll('.sort-button').forEach(button => {
        button.addEventListener('click', () => {
            sortRepos(button.dataset.sort);
        });
    });

    // Initial sort
    sortRepos('stars');
    
    console.log('Software page initialized with', repos.length, 'repositories');
}

// Multiple initialization strategies to handle different loading scenarios

// Strategy 1: Standard DOM loaded
document.addEventListener('DOMContentLoaded', function() {
    console.log('DOMContentLoaded fired');
    initializeSoftwarePage();
});

// Strategy 2: Use MutationObserver to detect when the repo-container appears
const observer = new MutationObserver(function(mutations) {
    mutations.forEach(function(mutation) {
        if (mutation.type === 'childList') {
            const repoContainer = document.getElementById('repo-container');
            if (repoContainer && repoContainer.dataset.initialized !== 'true') {
                console.log('repo-container detected via MutationObserver');
                initializeSoftwarePage();
            }
        }
    });
});

// Start observing when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function() {
        observer.observe(document.body, { childList: true, subtree: true });
    });
} else {
    // DOM already loaded
    observer.observe(document.body, { childList: true, subtree: true });
    initializeSoftwarePage(); // Try immediate initialization
}

// Strategy 3: Periodic check as fallback (will stop once initialized)
let checkCount = 0;
const maxChecks = 50; // Stop after 5 seconds (50 * 100ms)

function checkAndInit() {
    if (checkCount >= maxChecks) return;
    
    const repoContainer = document.getElementById('repo-container');
    if (repoContainer && repoContainer.dataset.initialized !== 'true') {
        console.log('repo-container found via periodic check');
        initializeSoftwarePage();
        return;
    }
    
    checkCount++;
    setTimeout(checkAndInit, 100);
}

// Start periodic check
setTimeout(checkAndInit, 100); 