from typing import Dict, List, Union
import requests
from datetime import datetime
import json
from pathlib import Path
import argparse
from habanero import Crossref
import polars as pl
import bibtexparser
from bibtexparser.bparser import BibTexParser
from bibtexparser.customization import convert_to_unicode
from bibtexparser.bibdatabase import BibDatabase

def get_orcid_works(orcid_id: str) -> List[Dict]:
    """Fetch publications from ORCID."""
    try:
        url = f"https://pub.orcid.org/v3.0/{orcid_id}/works"
        headers = {
            "Accept": "application/json"
        }
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            raise Exception(f"Failed to fetch data: {response.status_code}")
        
        works = response.json()['group']
        publications = []
        
        for work in works:
            work_summary = work['work-summary'][0]
            pub_data = {
                'title': work_summary.get('title', {}).get('title', {}).get('value', ''),
                'type': work_summary.get('type', 'Article'),
                'year': work_summary.get('publication-date', {}).get('year', {}).get('value'),
                'doi': next((ei['external-id-value'] for ei in work_summary.get('external-ids', {}).get('external-id', [])
                           if ei['external-id-type'] == 'doi'), None),
                'journal': '',  # ORCID doesn't always provide journal info in the summary
                'author': [],  # ORCID doesn't always provide author info in the summary
                'source': 'orcid'
            }
            print(f"\nFound ORCID publication: {pub_data['title'][:100]}")
            publications.append(pub_data)
        
        return publications
    except Exception as e:
        print(f"Error fetching from ORCID: {e}")
        return []

def get_crossref_works(author_name: str, mailto: str = None) -> List[Dict]:
    """Fetch publications from Crossref."""
    try:
        cr = Crossref(mailto=mailto)
        works = cr.works(query_author=author_name, limit=100)
        return works['message']['items']
    except Exception as e:
        print(f"Error fetching from Crossref: {e}")
        return []

def supplement_with_crossref(pub: Dict, cr: Crossref = None) -> Dict:
    """Supplement a publication entry with data from Crossref."""
    if not cr:
        cr = Crossref()
    
    try:
        # Skip supplementation if we have all important fields
        has_authors = bool(pub.get('author'))
        has_title = bool(pub.get('title'))
        has_journal = bool(pub.get('journal'))
        has_year = bool(pub.get('year'))
        has_doi = bool(pub.get('doi') and pub.get('doi') != '"none"')
        
        # Always ensure authors are properly formatted first
        if has_authors and isinstance(pub.get('author'), str):
            pub['author'] = pub['author'].split(' and ')
        
        if has_authors and has_title and has_journal and has_year and has_doi:
            return pub
            
        # Try to find the work in Crossref, preferring DOI lookup
        cr_work = None
        if pub.get('doi') and pub.get('doi') != '"none"':
            print(f"\nLooking up DOI: {pub['doi']}")
            try:
                works = cr.works(ids=[pub['doi']])
                if works and works.get('message'):
                    cr_work = works['message']
            except Exception as e:
                print(f"DOI lookup failed: {e}")
        
        # Fall back to title search if DOI lookup fails or we don't have a DOI
        if not cr_work:
            query = pub.get('title', '')
            if not query:
                return pub
                
            print(f"\nSearching Crossref for: {query[:100]}...")
            works = cr.works(query=query, limit=5)
            if not works.get('message', {}).get('items'):
                return pub
            
            # Try to find exact title match
            query_lower = query.lower()
            for item in works['message']['items']:
                if not item.get('title'):
                    continue
                item_title = item['title'][0].lower() if isinstance(item['title'], list) else item['title'].lower()
                # Remove common prefixes that might cause mismatches
                item_title = item_title.replace('review of: ', '').replace('review: ', '').strip('"')
                if item_title == query_lower:
                    cr_work = item
                    break
            
            if not cr_work:
                print("No exact title match found")
                return pub
        
        print(f"Found Crossref match: {cr_work.get('title', [''])[0][:100]}")
        
        # Supplement missing fields
        if not has_title and cr_work.get('title'):
            pub['title'] = cr_work['title'][0] if isinstance(cr_work['title'], list) else cr_work['title']
        
        # For authors, only supplement if missing or empty
        existing_authors = pub.get('author', [])
        if (not has_authors or len(existing_authors) == 0) and cr_work.get('author'):
            print(f"Original authors: {existing_authors}")
            cr_authors = [f"{a.get('given', '')} {a.get('family', '')}".strip() 
                        for a in cr_work['author']]
            cr_authors = [a for a in cr_authors if a]  # Remove empty author names
            print(f"Adding Crossref authors: {cr_authors}")
            pub['author'] = cr_authors
        elif has_authors and isinstance(pub.get('author'), str):
            # If authors exist but are in string format, convert to list
            pub['author'] = pub['author'].split(' and ')
        
        if not has_journal and cr_work.get('container-title'):
            pub['journal'] = cr_work['container-title'][0] if isinstance(cr_work['container-title'], list) else cr_work['container-title']
        
        if not has_year and cr_work.get('published-print'):
            year_parts = cr_work.get('published-print', {}).get('date-parts', [[None]])[0]
            if year_parts and year_parts[0]:
                pub['year'] = str(year_parts[0])
        
        if not has_doi and cr_work.get('DOI'):
            pub['doi'] = cr_work['DOI']
        
        if not pub.get('type'):
            pub['type'] = cr_work.get('type', 'Article').capitalize()
            
    except Exception as e:
        print(f"Error supplementing with Crossref: {e}")
    
    return pub

def get_bibtex_works(bibtex_file: str) -> List[Dict]:
    """Fetch publications from BibTeX file."""
    try:
        if not Path(bibtex_file).exists():
            print(f"Creating empty BibTeX file: {bibtex_file}")
            Path(bibtex_file).touch()
            return []
            
        # First, try to fix common BibTeX syntax errors
        with open(bibtex_file, 'r', encoding='utf-8') as bibfile:
            content = bibfile.read()
            
        # Fix missing commas after DOI
        fixed_content = content
        fixed_content = fixed_content.replace('}\n', '},\n', 50)  # Replace up to 50 occurrences
        fixed_content = fixed_content.replace('publisher={', 'publisher = {', 50)
        
        # Create a temporary file with fixed content
        temp_bibtex = Path(bibtex_file).parent / f"temp_{Path(bibtex_file).name}"
        with open(temp_bibtex, 'w', encoding='utf-8') as f:
            f.write(fixed_content)
            
        # Now parse the fixed file
        publications = []
        normalized_titles = set()  # For deduplication
        
        try:
            with open(temp_bibtex, 'r', encoding='utf-8') as bibfile:
                parser = BibTexParser()
                parser.customization = convert_to_unicode
                bib_database = bibtexparser.load(bibfile, parser=parser)
                
                for entry in bib_database.entries:
                    # Check for missing comma in the original bibtex (common issue)
                    author_str = entry.get('author', '')
                    
                    # Clean up DOI if it has quotes or is 'none'
                    doi = entry.get('doi', '')
                    if doi:
                        doi = doi.strip('"')
                        if doi.lower() == 'none':
                            doi = ''
                    
                    title = entry.get('title', '').lower().strip()
                    if title in normalized_titles:
                        print(f"\nSkipping duplicate entry: {title[:100]}")
                        continue
                    
                    normalized_titles.add(title)
                    
                    pub_data = {
                        'title': entry.get('title', ''),
                        'author': author_str.split(' and ') if author_str else [],
                        'journal': entry.get('journal', entry.get('booktitle', '')),
                        'year': entry.get('year'),
                        'doi': doi,
                        'type': entry.get('ENTRYTYPE', 'Article').capitalize(),
                        'source': 'bibtex'  # Mark source for merge logic
                    }
                    
                    publications.append(pub_data)
                    print(f"\nFound BibTeX publication: {pub_data['title'][:100]}")
                    print(f"  Authors: {pub_data['author']}")
                    print(f"  DOI: {pub_data['doi']}")
        
        except Exception as e:
            print(f"Error parsing fixed BibTeX file: {e}")
            # Try a more robust, manual approach
            print("Attempting manual BibTeX parsing...")
            
            with open(bibtex_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Find all BibTeX entries
            import re
            entries = re.findall(r'@(\w+)\{([^,]+),(.*?)\}', content, re.DOTALL)
            
            for entry_type, entry_key, entry_content in entries:
                # Extract fields
                fields = {}
                for field_match in re.finditer(r'\s*(\w+)\s*=\s*\{([^}]*)\}', entry_content):
                    field_name, field_value = field_match.groups()
                    fields[field_name.lower()] = field_value
                
                # Create publication data
                title = fields.get('title', '')
                if title.lower().strip() in normalized_titles:
                    print(f"\nSkipping duplicate entry: {title[:100]}")
                    continue
                
                if title:
                    normalized_titles.add(title.lower().strip())
                
                author_str = fields.get('author', '')
                doi = fields.get('doi', '')
                if doi:
                    doi = doi.strip('"')
                    if doi.lower() == 'none':
                        doi = ''
                
                pub_data = {
                    'title': title,
                    'author': author_str.split(' and ') if author_str else [],
                    'journal': fields.get('journal', fields.get('booktitle', '')),
                    'year': fields.get('year'),
                    'doi': doi,
                    'type': entry_type.capitalize(),
                    'source': 'bibtex'
                }
                
                publications.append(pub_data)
                print(f"\nFound BibTeX publication (manual parsing): {pub_data['title'][:100]}")
                print(f"  Authors: {pub_data['author']}")
                print(f"  DOI: {pub_data['doi']}")
        
        # Clean up the temporary file
        if temp_bibtex.exists():
            temp_bibtex.unlink()
        
        return publications
    except Exception as e:
        print(f"Error reading BibTeX file: {e}")
        return []

def format_authors(authors: Union[List[Dict], List[str]], highlight_name: str) -> str:
    """Format author list, highlighting the specified author."""
    if not authors:  # Handle empty author list
        return "No authors listed"
    
    author_names = []
    
    if isinstance(authors, str):
        # Handle case where authors is a string
        authors = authors.split(' and ')
    
    if authors and isinstance(authors[0], dict):  # Crossref format
        for author in authors:
            name = f"{author.get('given', '')} {author.get('family', '')}"
            if highlight_name.lower() in name.lower():
                name = f"**{name.strip()}**"
            author_names.append(name.strip())
    else:  # Scholar/ORCID format or string list
        for author in authors:
            if not author:  # Skip empty author entries
                continue
                
            name = author
            if highlight_name.lower() in name.lower():
                name = f"**{name.strip()}**"
            author_names.append(name.strip())
    
    return ', '.join(author_names)

def format_publication(pub: Dict, highlight_name: str) -> str:
    """Format a single publication in MkDocs format."""
    # Handle different year formats
    year = None
    if isinstance(pub.get('year'), str):
        year = pub['year']
    elif isinstance(pub.get('year'), int):
        year = str(pub['year'])
    elif 'published-print' in pub:
        year = pub.get('published-print', {}).get('date-parts', [[None]])[0][0]
    
    if not year:
        return None
    
    # Handle different title formats
    title = pub.get('title', '')
    if isinstance(title, list):
        title = title[0]
    
    # Handle different author formats
    authors = pub.get('author', pub.get('authors', []))
    if authors:
        authors_str = format_authors(authors, highlight_name)
    else:
        authors_str = ""  # Empty string if no authors
    
    # Handle different journal formats
    journal = pub.get('journal', '')
    if isinstance(journal, list):
        journal = journal[0] if journal else ''
    elif 'container-title' in pub:
        journal = pub['container-title'][0] if pub['container-title'] else ''
    
    # Clean up DOI
    doi = pub.get('doi', pub.get('DOI', ''))
    if doi and (doi.startswith('"') or doi.endswith('"')):
        doi = doi.strip('"')
    
    # Skip invalid DOIs
    if doi == "none" or not doi:
        doi = None
    
    # Use different admonition style for preprints
    pub_type = pub.get('type', 'Article')
    admonition = "warning" if pub_type.lower() == "preprint" else "publication"
    
    # Base content without links
    content = f"""!!! {admonition} "{pub_type}"
    **{title}**"""
    
    # Only add authors line if there are authors
    if authors_str:
        content += f"""  
    {authors_str}"""
    
    # Add journal and year
    content += f"""  
    *{journal}* ({year})"""
    
    # Add links only if DOI exists and is valid
    if doi:
        content += f"""  
    [DOI](https://doi.org/{doi}) | [BibTeX](https://api.crossref.org/works/{doi}/transform/application/x-bibtex)"""
    
    return content

def generate_publications_page(pubs: List[Dict], highlight_name: str, from_year: int = None) -> str:
    """Generate the full publications page content."""
    # Convert to Polars DataFrame for efficient processing
    df = pl.DataFrame(pubs)
    
    # Extract year from different formats and convert to integer
    if 'year' in df.columns:
        df = df.with_columns(pl.col('year').cast(pl.Int64))
    elif 'published-print' in df.columns:
        df = df.with_columns(
            pl.struct('published-print').map_elements(
                lambda x: x.get('date-parts', [[None]])[0][0]
            ).alias('year')
        )
    
    # Filter by year if specified
    if from_year is not None:
        df = df.filter(pl.col('year') >= from_year)
    
    # Sort by year and citations (if available)
    if 'citations' in df.columns:
        df = df.sort(['year', 'citations'], descending=True)
    else:
        df = df.sort('year', descending=True)
    
    # Generate content
    content = ["# Publications\n\n## Featured Publications\n"]
    
    # Process each year
    for year in df.get_column('year').unique().sort(descending=True):
        if year is None:
            continue
            
        content.append(f"\n### {year}")
        year_pubs = df.filter(pl.col('year') == year).to_dicts()
        
        # Format each publication
        for pub in year_pubs:
            formatted = format_publication(pub, highlight_name)
            if formatted:
                content.append(formatted)
    
    if len(content) <= 3:  # Only has header sections
        if from_year:
            content.append(f"\nNo publications found from {from_year} onwards.")
        else:
            content.append("\nNo publications found.")
    
    return "\n".join(content)

def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Update publications page from various sources",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        "-b", "--bibtex",
        help="BibTeX file to read and update publications from",
        default="docs/my_pubs.bibtexa"
    )
    parser.add_argument(
        "-a", "--author",
        # default="Antônio Camargo",
        default="Uri Neri",
        help="Author name to search for"
    )
    parser.add_argument(
        "-o", "--orcid",
        help="ORCID ID to supplement publications with",
        # default="0000-0003-3913-2484" Antônio Pedro Camargo
        default="0000-0003-0894-2484"
    )
    parser.add_argument(
        "-c", "--crossref",
        action="store_true",
        help="Use Crossref to supplement publications"
    )
    parser.add_argument(
        "-s", "--scopus",
        action="store_true",
        help="Use Scopus to supplement publications (not implemented yet)"
    )
    parser.add_argument(
        "-m", "--mailto",
        help="Email to send to Crossref for better rate limits"
    )
    parser.add_argument(
        "-O", "--output",
        type=Path,
        default=Path("docs/publications.md"),
        help="Output path for the publications markdown file"
    )
    parser.add_argument(
        "-r", "--raw-output",
        type=Path,
        help="Output path for raw publication data in JSON format"
    )
    parser.add_argument(
        "-f", "--from-year",
        type=int,
        default=None,
        help="Only include publications from this year onwards"
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

def merge_publications(pubs_list: List[List[Dict]], cr: Crossref = None) -> List[Dict]:
    """Merge publications from different sources, supplementing BibTeX entries with additional data."""
    if not pubs_list:
        return []
    
    # Keep track of all input bibtex entries to ensure none are lost
    bibtex_entries = []
    if pubs_list and pubs_list[0]:
        bibtex_entries = [p for p in pubs_list[0] if p.get('source') == 'bibtex']
    
    # Convert to Polars DataFrame
    all_pubs = []
    for pubs in pubs_list:
        if pubs:  # Only process non-empty lists
            # Ensure citations field exists
            for pub in pubs:
                if 'citations' not in pub:
                    pub['citations'] = 0
                if 'source' not in pub:
                    pub['source'] = 'other'
                print(f"\nProcessing publication from {pub['source']}: {pub.get('title', '')[:100]}")
                print(f"Authors: {pub.get('author', [])}")
            
            df = pl.DataFrame(pubs)
            
            # Normalize titles and DOIs for matching
            if 'title' in df.columns:
                df = df.with_columns([
                    pl.col('title').map_elements(
                        lambda x: x[0].lower() if isinstance(x, list) else str(x).lower(),
                        return_dtype=pl.Utf8
                    ).alias('normalized_title'),
                    pl.col('doi').map_elements(
                        lambda x: str(x).lower() if x else '',
                        return_dtype=pl.Utf8
                    ).alias('normalized_doi')
                ])
                
                # Convert to dicts and add to all_pubs
                all_pubs.extend(df.to_dicts())
    
    # Create DataFrame from all publications
    if not all_pubs:
        return []
    
    merged_df = pl.DataFrame(all_pubs)
    
    # First, separate entries with and without DOIs
    has_doi_df = None
    no_doi_df = None
    
    if 'normalized_doi' in merged_df.columns:
        has_doi_df = merged_df.filter(pl.col('normalized_doi') != '')
        no_doi_df = merged_df.filter(pl.col('normalized_doi') == '')
    else:
        no_doi_df = merged_df.clone()
    
    # Process entries with DOIs
    doi_results = []
    if has_doi_df is not None and len(has_doi_df) > 0:
        # Prioritize bibtex source during grouping
        has_doi_df = has_doi_df.with_columns(
            pl.when(pl.col('source') == 'bibtex')
            .then(1)
            .otherwise(0)
            .alias('is_bibtex')
        )
        
        grouped = has_doi_df.group_by('normalized_doi')
        # Aggregate, preferring BibTeX source when available
        grouped = grouped.agg([
            # Sort by is_bibtex to get bibtex entry first
            pl.col('source').sort_by('is_bibtex', descending=True).first().alias('source'),
            pl.col('title').sort_by('is_bibtex', descending=True).first().alias('title'),
            pl.col('author').sort_by('is_bibtex', descending=True).first().alias('author'),
            pl.col('journal').sort_by('is_bibtex', descending=True).first().alias('journal'),
            pl.col('year').sort_by('is_bibtex', descending=True).first().alias('year'),
            pl.col('doi').sort_by('is_bibtex', descending=True).first().alias('doi'),
            pl.col('type').sort_by('is_bibtex', descending=True).first().alias('type'),
            pl.col('citations').max().fill_null(0).alias('citations')
        ])
        doi_results = grouped.to_dicts()
    
    # Process entries without DOIs
    no_doi_results = []
    if no_doi_df is not None and len(no_doi_df) > 0:
        # Prioritize bibtex source during grouping
        no_doi_df = no_doi_df.with_columns(
            pl.when(pl.col('source') == 'bibtex')
            .then(1)
            .otherwise(0)
            .alias('is_bibtex')
        )
        
        # Filter out titles that might match with DOI entries to avoid duplicates
        if has_doi_df is not None and len(has_doi_df) > 0:
            doi_titles = set(has_doi_df.get_column('normalized_title').to_list())
            no_doi_df = no_doi_df.filter(~pl.col('normalized_title').is_in(doi_titles))
            
        if len(no_doi_df) > 0:
            grouped = no_doi_df.group_by('normalized_title')
            # Aggregate, preferring BibTeX source when available
            grouped = grouped.agg([
                # Sort by is_bibtex to get bibtex entry first
                pl.col('source').sort_by('is_bibtex', descending=True).first().alias('source'),
                pl.col('title').sort_by('is_bibtex', descending=True).first().alias('title'),
                pl.col('author').sort_by('is_bibtex', descending=True).first().alias('author'),
                pl.col('journal').sort_by('is_bibtex', descending=True).first().alias('journal'),
                pl.col('year').sort_by('is_bibtex', descending=True).first().alias('year'),
                pl.col('doi').sort_by('is_bibtex', descending=True).first().alias('doi'),
                pl.col('type').sort_by('is_bibtex', descending=True).first().alias('type'),
                pl.col('citations').max().fill_null(0).alias('citations')
            ])
            no_doi_results = grouped.to_dicts()
    
    # Combine results from DOI and title-based merging
    combined_results = doi_results + no_doi_results
    
    # Now check if any entries from the original bibtex were lost in the process
    combined_titles = {pub['title'].lower().strip() for pub in combined_results if pub.get('title')}
    missing_entries = []
    
    for entry in bibtex_entries:
        if not entry.get('title'):
            continue
            
        title = entry['title'].lower().strip()
        if title not in combined_titles:
            print(f"\nRecovering lost entry from bibtex: {entry['title'][:100]}")
            missing_entries.append(entry)
    
    # Add missing entries back to the combined results
    combined_results.extend(missing_entries)
    
    # Convert back to list of dicts and supplement with Crossref data
    result = []
    for pub in combined_results:
        print(f"\nMerged publication: {pub.get('title', '')[:100]}")
        print(f"Pre-supplement authors: {pub.get('author', [])}")
        supplemented = supplement_with_crossref(pub, cr)
        print(f"Post-supplement authors: {supplemented.get('author', [])}")
        result.append(supplemented)
    
    return result

def pub_to_bibtex_entry(pub: Dict) -> Dict:
    """Convert a publication dict to BibTeX entry format."""
    # Ensure we have at least one author and a year for the ID
    authors = pub.get('author', [])
    if isinstance(authors, list):
        first_author = authors[0].split()[-1] if authors else 'Unknown'
        author_str = ' and '.join(authors)
    else:
        first_author = 'Unknown'
        author_str = str(authors) if authors else 'Unknown Author'
    
    year = str(pub.get('year', ''))
    entry_id = f"{first_author}{year}"
    
    entry = {
        'ENTRYTYPE': pub.get('type', 'Article').lower(),
        'ID': entry_id,
        'title': str(pub.get('title', '')),
        'year': year,
        'author': author_str
    }
    
    # Add optional fields if they exist
    if pub.get('journal'):
        if pub.get('type', '').lower() in ['inproceedings', 'conference']:
            entry['booktitle'] = str(pub['journal'])
        else:
            entry['journal'] = str(pub['journal'])
    
    if pub.get('doi'):
        entry['doi'] = str(pub['doi'])
    
    return entry

def save_supplemented_bibtex(publications: List[Dict], input_bibtex: str) -> None:
    """Save supplemented publications as BibTeX with timestamp."""
    if not publications:
        return
        
    # Create BibTeX database
    db = BibDatabase()
    db.entries = [pub_to_bibtex_entry(pub) for pub in publications]
    
    # Generate timestamp and filename
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    input_path = Path(input_bibtex)
    output_path = input_path.parent / f"{input_path.stem}_supplemented_{timestamp}{input_path.suffix}"
    
    # Write to file
    writer = bibtexparser.bwriter.BibTexWriter()
    writer.indent = '    '  # Use 4 spaces for indentation
    writer.order_entries_by = ('year', 'author', 'title')
    
    with open(output_path, 'w', encoding='utf-8') as bibfile:
        bibfile.write(writer.write(db))
    print(f"Supplemented BibTeX saved to: {output_path}")

def main():
    """Main function."""
    args = parse_args()
    
    if args.clear:
        if args.output:
            clear_file(args.output)
        if args.raw_output:
            clear_file(args.raw_output)
    
    # Initialize Crossref client if needed
    cr = Crossref(mailto=args.mailto) if args.crossref or args.mailto else None
    
    publications = []
    
    # Read from BibTeX file (primary source)
    bibtex_pubs = get_bibtex_works(args.bibtex)
    publications.append(bibtex_pubs)
    
    # Fetch from ORCID if enabled
    if args.orcid:
        orcid_pubs = get_orcid_works(args.orcid)
        publications.append(orcid_pubs)
    
    # Fetch from Crossref if enabled
    if args.crossref:
        crossref_pubs = get_crossref_works(args.author, args.mailto)
        publications.append(crossref_pubs)
    
    # Scopus support placeholder
    if args.scopus:
        print("Scopus support not implemented yet")
    
    # Merge all publications, supplementing with Crossref data
    merged_pubs = merge_publications(publications, cr)
    
    # Save supplemented BibTeX
    save_supplemented_bibtex(merged_pubs, args.bibtex)
    
    # Generate and save the publications page
    content = generate_publications_page(merged_pubs, args.author, args.from_year)
    
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content)
        print(f"Publications page written to {args.output}")
    
    if args.raw_output:
        args.raw_output.parent.mkdir(parents=True, exist_ok=True)
        args.raw_output.write_text(json.dumps(merged_pubs, indent=2))
        print(f"Raw publication data written to {args.raw_output}")

if __name__ == "__main__":
    main() 