document.addEventListener('DOMContentLoaded', function() {
    const repoContainer = document.getElementById('repo-container');
    if (!repoContainer) return;

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

        repos.sort((a, b) => {
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

        repos.forEach(repo => repoContainer.appendChild(repo));
    }

    document.querySelectorAll('.sort-button').forEach(button => {
        button.addEventListener('click', () => {
            sortRepos(button.dataset.sort);
        });
    });

    // Initial sort
    sortRepos('stars');
}); 