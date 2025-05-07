from typing import Dict, List, Optional, Tuple
import requests
import argparse
from pathlib import Path
from datetime import datetime
import json
import re

def get_github_repos(username: str, token: Optional[str] = None) -> List[Dict]:
    """Fetch repositories from GitHub."""
    try:
        headers = {
            'Accept': 'application/vnd.github.v3+json'
        }
        if token:
            headers['Authorization'] = f'token {token}'
            
        repos = []
        page = 1
        while True:
            url = f"https://api.github.com/users/{username}/repos?page={page}&per_page=100"
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            
            page_repos = response.json()
            if not page_repos:  # No more repos to fetch
                break
                
            for repo in page_repos:
                if repo['fork']:  # Skip forks
                    continue
                    
                repo_data = {
                    'name': repo['name'],
                    'description': repo['description'] or '',
                    'url': repo['html_url'],
                    'language': repo['language'] or 'Unknown',
                    'stars': repo['stargazers_count'],
                    'forks': repo['forks_count'],
                    'updated_at': repo['updated_at'],
                    'topics': repo.get('topics', []),
                    'source': 'github'
                }
                repos.append(repo_data)
                print(f"Found GitHub repo: {repo_data['name']}")
            
            # Check if there are more pages
            if 'next' not in {rel[1]: rel[0] for rel in (link.split('; rel="') for link in response.headers.get('Link', '').split(', ') if link)}:
                break
                
            page += 1
        
        return repos
    except Exception as e:
        print(f"Error fetching GitHub repositories: {e}")
        return []

def get_gitlab_repo_by_path(base_url: str, repo_path: str, headers: Dict) -> Optional[Dict]:
    """Fetch a single GitLab repository by its path."""
    try:
        # Encode the repo path for the URL
        encoded_path = requests.utils.quote(repo_path, safe='')
        project_url = f"{base_url}/api/v4/projects/{encoded_path}"
        print(f"Looking up GitLab project: {project_url}")
        
        response = requests.get(project_url, headers=headers)
        response.raise_for_status()
        
        repo = response.json()
        if repo.get('forked_from_project'):
            return None
            
        # Get primary language - now included in the response
        main_language = repo.get('language') or 'Unknown'
        
        repo_data = {
            'name': repo['name'],
            'description': repo.get('description') or '',
            'url': repo['web_url'],
            'language': main_language,
            'stars': repo.get('star_count', 0),
            'forks': repo.get('forks_count', 0),
            'updated_at': repo.get('last_activity_at'),
            'topics': repo.get('topics', []) or repo.get('tag_list', []),
            'source': 'gitlab'
        }
        print(f"Found GitLab repo: {repo_data['name']} ({main_language})")
        return repo_data
    except Exception as e:
        print(f"Error fetching GitLab repository {repo_path}: {e}")
        return None

def get_gitlab_repos(instance: str, username: str, token: Optional[str] = None) -> List[Dict]:
    """Fetch repositories from GitLab."""
    try:
        headers = {
            'Accept': 'application/json'
        }
        if token:
            headers['PRIVATE-TOKEN'] = token
            
        # Ensure instance URL is properly formatted
        base_url = instance.rstrip('/')
        
        # First get user ID
        user_url = f"{base_url}/api/v4/users?username={username}"
        print(f"Looking up GitLab user: {user_url}")
        user_response = requests.get(user_url, headers=headers)
        user_response.raise_for_status()
        
        users = user_response.json()
        if not users:
            print(f"GitLab user {username} not found")
            return []
            
        user_id = users[0]['id']
        print(f"Found GitLab user ID: {user_id}")
        
        # Then get user's projects with detailed information
        projects_url = f"{base_url}/api/v4/users/{user_id}/projects"
        print(f"Fetching GitLab projects: {projects_url}")
        response = requests.get(
            projects_url,
            headers=headers,
            params={
                'visibility': 'public',
                'order_by': 'last_activity_at',
                'sort': 'desc',
                'statistics': 'true',  # Get repository statistics
                'with_programming_language': 'true'  # Get language information
            }
        )
        response.raise_for_status()
        
        repos = []
        for repo in response.json():
            try:
                # Skip if it's a fork
                if repo.get('forked_from_project'):
                    continue
                    
                # Get primary language - now included in the response
                main_language = repo.get('language') or 'Unknown'
                
                repo_data = {
                    'name': repo['name'],
                    'description': repo.get('description') or '',
                    'url': repo['web_url'],
                    'language': main_language,
                    'stars': repo.get('star_count', 0),
                    'forks': repo.get('forks_count', 0),
                    'updated_at': repo.get('last_activity_at'),
                    'topics': repo.get('topics', []) or repo.get('tag_list', []),
                    'source': 'gitlab'
                }
                repos.append(repo_data)
                print(f"Found GitLab repo: {repo_data['name']} ({main_language})")
            except Exception as e:
                print(f"Error processing GitLab repo {repo.get('name', 'unknown')}: {e}")
                continue
        
        return repos
    except Exception as e:
        print(f"Error fetching GitLab repositories: {e}")
        return []

def format_repo(repo: Dict) -> str:
    """Format a repository in MkDocs format."""
    # Convert updated_at to datetime for sorting
    updated = datetime.fromisoformat(repo['updated_at'].replace('Z', '+00:00'))
    
    # Format topics
    topics_str = ', '.join(f"`{topic}`" for topic in repo['topics']) if repo['topics'] else ''
    
    # Format stats
    stats = []
    if repo['stars'] > 0:
        stats.append(f"⭐ {repo['stars']}")
    if repo['forks'] > 0:
        stats.append(f"🔱 {repo['forks']}")
    stats_str = f" ({' | '.join(stats)})" if stats else ""
    
    # Format source icon
    source_icon = "🐙" if repo['source'] == 'github' else "🦊"
    
    return f"""!!! python "{repo['name']}"
    **[{repo['name']}]({repo['url']})** {source_icon}{stats_str}  
    {repo['description']}  
    {topics_str}
"""

def generate_software_page(repos: List[Dict]) -> str:
    """Generate the full software page content."""
    if not repos:
        return "# Software\n\nNo repositories found."

    # Language to emoji mapping
    language_icons = {
        'Python': '🐍',
        'R': '📊',
        'JavaScript': '☕',
        'TypeScript': '📘',
        'Java': '☕',
        'C++': '⚡',
        'C': '⚙️',
        'Shell': '🐚',
        'Ruby': '💎',
        'Go': '🐹',
        'Rust': '🦀',
        'PHP': '🐘',
        'Swift': '🦅',
        'Kotlin': '🎯',
        'Jupyter Notebook': '📓',
        'HTML': '🌐',
        'CSS': '🎨',
        'Perl': '🐪',
        'Julia': '📊',
        'Scala': '⚡',
        'Haskell': 'λ',
        'Unknown': '📦'
    }

    content = ["# Software\n"]
    
    # Add sorting buttons
    content.append("""
<div class="sort-buttons">
    <button class="sort-button active" data-sort="stars">Sort by Stars</button>
    <button class="sort-button" data-sort="date">Sort by Date</button>
    <button class="sort-button" data-sort="language">Sort by Language</button>
</div>
""")

    content.append('<div id="repo-container">\n')

    # Sort repositories by stars initially
    repos.sort(key=lambda x: (-(x.get('stars', 0) or 0), x.get('updated_at', '')), reverse=True)

    for repo in repos:
        name = repo['name']
        description = repo.get('description', '').replace('\n', ' ').strip() or 'No description available.'
        url = repo['url']
        stars = repo.get('stars', 0) or 0
        language = repo.get('language', 'Unknown')
        updated_at = repo.get('updated_at', '')
        topics = repo.get('topics', [])
        
        # Get language emoji
        lang_icon = language_icons.get(language, '📦')
        
        content.append(f"""
<div class="repo-card" data-stars="{stars}" data-language="{language}" data-date="{updated_at}">
    <h3><a href="{url}">{name}</a></h3>
    <div class="repo-meta">
        <span>{lang_icon} {language}</span>
        <span>⭐ {stars}</span>
        <span>📅 {updated_at[:10]}</span>
    </div>
    <p>{description}</p>""")
        
        if topics:
            content.append('    <div class="repo-topics">')
            for topic in topics:
                content.append(f'        <span class="repo-topic">{topic}</span>')
            content.append('    </div>')
        
        content.append('</div>\n')

    content.append('</div>')  # Close repo-container
    
    return '\n'.join(content)

def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Update software page from GitHub and GitLab repositories",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        "-g", "--github-user",
        # default="apcamargo", # Antonio Camargo
        default="UriNeri",
        help="GitHub username"
    )
    parser.add_argument(
        "-t", "--github-token",
        help="GitHub personal access token for higher rate limits"
    )
    parser.add_argument(
        "-l", "--gitlab-instance",
        default="https://code.jgi.doe.gov",
        help="GitLab instance URL"
    )
    parser.add_argument(
        "-u", "--gitlab-user",
        default="UNeri",
        help="GitLab username"
    )
    parser.add_argument(
        "-k", "--gitlab-token",
        help="GitLab personal access token"
    )
    parser.add_argument(
        "-f", "--from-file",
        type=Path,
        default=Path("docs/my_gits.lst"),
        help="Path to file containing repository URLs (one per line)"
    )
    parser.add_argument(
        "-O", "--output",
        type=Path,
        default=Path("docs/software.md"),
        help="Output path for the software markdown file"
    )
    parser.add_argument(
        "-r", "--raw-output",
        type=Path,
        default=Path("docs/software.json"),
        help="Output path for raw repository data in JSON format"
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear the output files before writing"
    )
    return parser.parse_args()

def clear_file(file_path: Path) -> None:
    """Clear the contents of a file if it exists."""
    if file_path.exists():
        file_path.unlink()
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.touch()

def parse_repo_url(url: str) -> Tuple[str, str, str]:
    """Parse a repository URL to determine the source (github/gitlab), instance, and username/repo.
    
    Args:
        url: Repository URL (e.g., https://github.com/user/repo or https://gitlab.com/user/repo)
        
    Returns:
        Tuple of (source, instance, repo_path)
    """
    url = url.strip()
    if not url:
        raise ValueError("Empty URL provided")
        
    # Remove trailing .git if present
    url = url.rstrip('.git')
    
    # GitHub URLs
    github_match = re.match(r'https?://(?:www\.)?github\.com/([^/]+/[^/]+)/?$', url)
    if github_match:
        return 'github', 'https://github.com', github_match.group(1)
    
    # GitLab URLs - support any instance
    gitlab_match = re.match(r'https?://([^/]+)/([^/]+/[^/]+)/?$', url)
    if gitlab_match:
        instance = f"https://{gitlab_match.group(1)}"
        return 'gitlab', instance, gitlab_match.group(2)
    
    raise ValueError(f"Invalid repository URL: {url}")

def get_repo_from_url(url: str, github_token: Optional[str] = None, gitlab_token: Optional[str] = None) -> Optional[Dict]:
    """Get repository information from a URL.
    
    Args:
        url: Repository URL
        github_token: Optional GitHub token
        gitlab_token: Optional GitLab token
        
    Returns:
        Repository information dictionary or None if not found
    """
    try:
        source, instance, repo_path = parse_repo_url(url)
        
        if source == 'github':
            username, repo_name = repo_path.split('/')
            repos = get_github_repos(username, github_token)
            return next((repo for repo in repos if repo['name'] == repo_name), None)
        else:  # gitlab
            headers = {
                'Accept': 'application/json'
            }
            if gitlab_token:
                headers['PRIVATE-TOKEN'] = gitlab_token
                
            return get_gitlab_repo_by_path(instance, repo_path, headers)
            
    except Exception as e:
        print(f"Error processing repository URL {url}: {e}")
        return None

def get_repos_from_file(file_path: str, github_token: Optional[str] = None, gitlab_token: Optional[str] = None) -> List[Dict]:
    """Get repository information from a file containing repository URLs.
    
    Args:
        file_path: Path to file containing repository URLs (one per line)
        github_token: Optional GitHub token
        gitlab_token: Optional GitLab token
        
    Returns:
        List of repository information dictionaries
    """
    repos = []
    try:
        with open(file_path, 'r') as f:
            for line in f:
                url = line.strip()
                if not url or url.startswith('#'):
                    continue
                    
                repo = get_repo_from_url(url, github_token, gitlab_token)
                if repo:
                    repos.append(repo)
                    print(f"Found repository from URL: {url}")
                else:
                    print(f"Could not find repository: {url}")
    except Exception as e:
        print(f"Error reading repository URLs from {file_path}: {e}")
        
    return repos

def main():
    """Main function."""
    args = parse_args()
    
    if args.clear:
        if args.output:
            clear_file(args.output)
        if args.raw_output:
            clear_file(args.raw_output)
    
    # Fetch repositories
    repos = []
    
    # Get repositories from file if specified
    if args.from_file:
        file_repos = get_repos_from_file(args.from_file, args.github_token, args.gitlab_token)
        repos.extend(file_repos)
    
    # Get GitHub repositories
    github_repos = get_github_repos(args.github_user, args.github_token)
    repos.extend(github_repos)
    
    # Get GitLab repositories
    gitlab_repos = get_gitlab_repos(args.gitlab_instance, args.gitlab_user, args.gitlab_token)
    repos.extend(gitlab_repos)
    
    # Generate and save the software page
    content = generate_software_page(repos)
    
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content)
        print(f"Software page written to {args.output}")
    
    if args.raw_output:
        args.raw_output.parent.mkdir(parents=True, exist_ok=True)
        args.raw_output.write_text(json.dumps(repos, indent=2))
        print(f"Raw repository data written to {args.raw_output}")

if __name__ == "__main__":
    main() 