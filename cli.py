#!/usr/bin/env python3
"""
BioSearch CLI - Command-line interface for the BioSearch application.

This module provides command-line access to the BioSearch functionality,
allowing users to search biological databases without using the web interface.
"""

import argparse
import json
import sys
import os
import ssl
import requests
import asyncio
import aiohttp
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress
from tabulate import tabulate
import time
import logging

# Add parent directory to path to import BioSearch modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from api import (
    search_ncbi, search_pubmed, search_uniprot, search_drugbank,
    format_ncbi_gene_results, format_pubmed_results, format_uniprot_results, format_drugbank_results
)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Create a console for rich output
console = Console()

# Create a custom SSL context that doesn't verify certificates
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

# Dictionary of supported databases
DATABASES = {
    'ncbi': {
        'name': 'NCBI',
        'search_func': search_ncbi,
        'format_func': format_ncbi_gene_results
    },
    'pubmed': {
        'name': 'PubMed',
        'search_func': search_pubmed,
        'format_func': format_pubmed_results
    },
    'uniprot': {
        'name': 'UniProt',
        'search_func': search_uniprot,
        'format_func': format_uniprot_results
    },
    'drugbank': {
        'name': 'DrugBank',
        'search_func': search_drugbank,
        'format_func': format_drugbank_results
    }
}

def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="BioSearch CLI - Search biological databases from the command line"
    )
    
    # Required query argument
    parser.add_argument(
        "query",
        help="Search query (e.g., gene name, protein, drug name)"
    )
    
    # Optional arguments
    parser.add_argument(
        "-d", "--databases",
        help="Comma-separated list of databases to search (default: all)",
        default="ncbi,pubmed,uniprot,drugbank"
    )
    
    parser.add_argument(
        "-o", "--organism",
        help="Filter results by organism (default: human)",
        default="human"
    )
    
    parser.add_argument(
        "-l", "--limit",
        help="Maximum number of results per database (default: 5)",
        type=int,
        default=5
    )
    
    parser.add_argument(
        "-f", "--format",
        help="Output format (default: table)",
        choices=["table", "json", "csv"],
        default="table"
    )
    
    parser.add_argument(
        "--from",
        dest="date_from",
        help="Filter results from this date (YYYY-MM-DD)"
    )
    
    parser.add_argument(
        "--to",
        dest="date_to",
        help="Filter results until this date (YYYY-MM-DD)"
    )
    
    parser.add_argument(
        "-t", "--type",
        help="Filter by result type (e.g., gene, protein, pathway)"
    )
    
    parser.add_argument(
        "--output",
        help="Save results to file (specify file path)"
    )
    
    parser.add_argument(
        "--server",
        help="Use running BioSearch server at URL instead of direct API calls",
        metavar="URL"
    )
    
    return parser.parse_args()

def search_via_server(args):
    """Search using a running BioSearch server."""
    server_url = args.server.rstrip("/")
    api_url = f"{server_url}/api/search"
    
    # Prepare parameters
    params = {
        "query": args.query,
        "databases": args.databases,
        "organism": args.organism,
        "limit": args.limit
    }
    
    if args.date_from:
        params["date_from"] = args.date_from
    if args.date_to:
        params["date_to"] = args.date_to
    if args.type:
        params["result_type"] = args.type
    
    try:
        with Progress() as progress:
            task = progress.add_task("[cyan]Searching...", total=None)
            response = requests.get(api_url, params=params)
        
        if response.status_code != 200:
            console.print(f"[bold red]Error:[/bold red] Server returned status code {response.status_code}")
            console.print(response.text)
            return None
        
        return response.json()
    
    except requests.exceptions.RequestException as e:
        console.print(f"[bold red]Error connecting to server:[/bold red] {str(e)}")
        return None

async def search_directly_async(args):
    """Search databases directly using API functions."""
    # Parse databases to search
    databases = [db.strip().lower() for db in args.databases.split(',') if db.strip()]
    
    # Use all databases if none specified
    if not databases:
        databases = list(DATABASES.keys())
    
    # Check if specified databases are valid
    invalid_dbs = [db for db in databases if db not in DATABASES]
    if invalid_dbs:
        console.print(f"[bold red]Error:[/bold red] Invalid databases: {', '.join(invalid_dbs)}")
        console.print(f"Valid options: {', '.join(DATABASES.keys())}")
        return None
    
    # Create a basic results structure that doesn't rely on weird nesting
    results = {
        "query": args.query,
        "total_count": 0,
        "protein": [],
        "gene": [],
        "publication": [],
        "drug": []
    }
    
    # Configure aiohttp session with SSL context
    connector = aiohttp.TCPConnector(ssl=ssl_context)
    
    # Enable debug output
    debug_mode = os.environ.get('BIOSEARCH_DEBUG', 'false').lower() in ('true', '1', 't')
    
    # Search each database
    with Progress() as progress:
        # Create a task for overall progress
        overall_task = progress.add_task("[cyan]Searching databases...", total=len(databases))
        
        async with aiohttp.ClientSession(connector=connector) as session:
            for db_name in databases:
                if db_name in DATABASES:
                    db_info = DATABASES[db_name]
                    
                    # Create a task for this database
                    db_task = progress.add_task(f"[green]Searching {db_info['name']}...", total=None)
                    
                    try:
                        # Use the search_database function for all database types
                        formatted_results = await search_database(session, db_name, args.query, args.limit)
                        
                        # Skip if error or empty results
                        if isinstance(formatted_results, dict) and 'error' in formatted_results:
                            logger.warning(f"Error in {db_name} search: {formatted_results['error']}")
                            continue
                        
                        if not formatted_results:
                            logger.info(f"No results found for {db_name}")
                            continue
                        
                        # Add to the appropriate category based on database type
                        if db_name == 'ncbi':
                            results["gene"].extend(formatted_results)
                            logger.info(f"Added {len(formatted_results)} results to gene category")
                        elif db_name == 'pubmed':
                            results["publication"].extend(formatted_results)
                            logger.info(f"Added {len(formatted_results)} results to publication category")
                        elif db_name == 'uniprot':
                            results["protein"].extend(formatted_results)
                            logger.info(f"Added {len(formatted_results)} results to protein category")
                        elif db_name == 'drugbank':
                            results["drug"].extend(formatted_results)
                            logger.info(f"Added {len(formatted_results)} results to drug category")
                    
                    except Exception as e:
                        console.print(f"[bold yellow]Warning:[/bold yellow] Error searching {db_name}: {str(e)}")
                        import traceback
                        logger.error(f"Exception during {db_name} search: {str(e)}")
                        logger.error(traceback.format_exc())
                    
                    finally:
                        # Complete the database task
                        progress.update(db_task, completed=True)
                        
                        # Update overall progress
                        progress.update(overall_task, advance=1)
    
    # Calculate total count
    total_count = sum(len(results[key]) for key in ['protein', 'gene', 'publication', 'drug'])
    results['total_count'] = total_count
    
    logger.info(f"Final result counts: genes={len(results['gene'])}, proteins={len(results['protein'])}, publications={len(results['publication'])}, drugs={len(results['drug'])}")
    
    return results

def search_directly(args):
    """Wrapper to run async search function."""
    return asyncio.run(search_directly_async(args))

def display_results(results, format_type, args):
    """Display search results in the specified format."""
    # Check if we have any results
    if results['total_count'] == 0:
        console.print("[yellow]No results found.[/yellow]")
        return
    
    # Print nice header
    if format_type == "table":
        console.print(Panel.fit(
            f"[bold]Search Results for:[/bold] {results['query']} - [cyan]{results['total_count']}[/cyan] total results",
            border_style="cyan"
        ))
        
        # For each result type, create a table if we have results
        result_types = {
            'protein': 'Protein',
            'gene': 'Gene',
            'publication': 'Publication',
            'drug': 'Drug'
        }
        
        for key, title in result_types.items():
            items = results[key]
            if not items:
                continue
            
            count = len(items)
            console.print(f"\n[bold cyan]{title}[/bold cyan] ([bold]{count}[/bold] results)")
            
            # Create a table for this result type
            table = Table(show_header=True, header_style="bold")
            
            # Display based on the category
            if key == 'gene':
                table.add_column("ID")
                table.add_column("Symbol")
                table.add_column("Name")
                table.add_column("Organism")
                table.add_column("Source")
                
                for item in items[:args.limit]:
                    table.add_row(
                        str(item.get('id', '')),
                        item.get('symbol', ''),
                        item.get('name', '')[:50] + ('...' if len(item.get('name', '')) > 50 else ''),
                        item.get('organism', ''),
                        item.get('source_db', '')
                    )
            
            elif key == 'protein':
                table.add_column("ID")
                table.add_column("Name")
                table.add_column("Organism")
                table.add_column("Length")
                table.add_column("Source")
                
                for item in items[:args.limit]:
                    table.add_row(
                        str(item.get('id', '')),
                        item.get('name', '')[:50] + ('...' if len(item.get('name', '')) > 50 else ''),
                        item.get('organism', ''),
                        str(item.get('length', '')),
                        item.get('source_db', '')
                    )
            
            elif key == 'publication':
                table.add_column("ID")
                table.add_column("Title")
                table.add_column("Authors")
                table.add_column("Journal")
                table.add_column("Year")
                
                for item in items[:args.limit]:
                    authors = ', '.join(item.get('authors', [])[:2])
                    if len(item.get('authors', [])) > 2:
                        authors += ', et al.'
                    
                    table.add_row(
                        str(item.get('id', '')),
                        item.get('title', '')[:50] + ('...' if len(item.get('title', '')) > 50 else ''),
                        authors,
                        item.get('journal', ''),
                        str(item.get('year', ''))
                    )
            
            elif key == 'drug':
                table.add_column("ID")
                table.add_column("Name")
                table.add_column("Formula")
                table.add_column("Description")
                table.add_column("Source")
                
                for item in items[:args.limit]:
                    table.add_row(
                        str(item.get('id', '')),
                        item.get('name', ''),
                        item.get('formula', ''),
                        item.get('description', '')[:50] + ('...' if len(item.get('description', '')) > 50 else ''),
                        item.get('source_db', '')
                    )
            
            console.print(table)
    
    elif format_type == "json":
        # Print JSON output
        print(json.dumps(results, indent=2))
    
    elif format_type == "csv":
        # For each result type, create a CSV table
        for result_type, items in results['results'].items():
            if not items:
                continue
            
            print(f"\n# {result_type.capitalize()} Results")
            
            # Get all unique keys from the items
            all_keys = set()
            for item in items:
                all_keys.update(item.keys())
            
            # Filter out complex keys (lists, dicts)
            simple_keys = [k for k in all_keys if all(not isinstance(item.get(k), (list, dict)) for item in items if k in item)]
            
            # Define important keys to include first
            priority_keys = ['id', 'name', 'symbol', 'organism', 'description', 'source_db']
            sorted_keys = [k for k in priority_keys if k in simple_keys]
            sorted_keys.extend([k for k in simple_keys if k not in priority_keys])
            
            # Create rows for tabulate
            rows = []
            for item in items:
                row = [str(item.get(k, '')) for k in sorted_keys]
                rows.append(row)
            
            # Print CSV table
            print(tabulate(rows, headers=sorted_keys, tablefmt="csv"))

def export_results(results, output_file):
    """Export results to a file."""
    # Determine file format based on extension
    _, ext = os.path.splitext(output_file)
    
    try:
        with open(output_file, 'w') as f:
            if ext.lower() == '.json':
                json.dump(results, f, indent=2)
            elif ext.lower() == '.csv':
                # For each result type, create a CSV section
                for result_type, items in results['results'].items():
                    if not items:
                        continue
                    
                    f.write(f"\n# {result_type.capitalize()} Results\n")
                    
                    # Get all unique keys from the items
                    all_keys = set()
                    for item in items:
                        all_keys.update(item.keys())
                    
                    # Filter out complex keys (lists, dicts)
                    simple_keys = [k for k in all_keys if all(not isinstance(item.get(k), (list, dict)) for item in items if k in item)]
                    
                    # Define important keys to include first
                    priority_keys = ['id', 'name', 'symbol', 'organism', 'description', 'source_db']
                    sorted_keys = [k for k in priority_keys if k in simple_keys]
                    sorted_keys.extend([k for k in simple_keys if k not in priority_keys])
                    
                    # Create rows for tabulate
                    rows = []
                    for item in items:
                        row = [str(item.get(k, '')) for k in sorted_keys]
                        rows.append(row)
                    
                    # Write CSV table
                    f.write(tabulate(rows, headers=sorted_keys, tablefmt="csv"))
                    f.write("\n\n")
            else:
                # Default to JSON for unknown extensions
                json.dump(results, f, indent=2)
        
        console.print(f"[green]Results exported to {output_file}[/green]")
    
    except Exception as e:
        console.print(f"[bold red]Error exporting results:[/bold red] {str(e)}")

async def search_database(session, db_id, query, limit=10):
    """Legacy method: Search a specific database using its API."""
    db_info = DATABASES[db_id]
    
    try:
        if db_id == 'pubmed':
            # Special case for PubMed - use search_ncbi directly with 'pubmed' database
            raw_results = await search_ncbi(session, 'pubmed', query, limit)
            formatted_results = await format_pubmed_results(raw_results)
            # Add source database info
            if formatted_results and isinstance(formatted_results, list):
                for item in formatted_results:
                    item['source_db'] = db_info['name']
            return formatted_results
        
        elif db_id == 'ncbi':
            raw_results = await search_ncbi(session, db_info['db_type'], query, limit)
            formatted_results = await format_ncbi_gene_results(raw_results)
            # Add source database info
            if formatted_results and isinstance(formatted_results, list):
                for item in formatted_results:
                    item['source_db'] = db_info['name']
            return formatted_results
        
        elif db_id == 'uniprot':
            raw_results = await search_uniprot(session, query, limit)
            formatted_results = await format_uniprot_results(raw_results)
            # Add source database info
            if formatted_results and isinstance(formatted_results, list):
                for item in formatted_results:
                    item['source_db'] = db_info['name']
            return formatted_results
        
        elif db_id == 'drugbank':
            raw_results = await search_drugbank(session, query, limit)
            formatted_results = await format_drugbank_results(raw_results)
            # Add source database info - ensure source is marked as DrugBank even though we use PubChem API
            if formatted_results and isinstance(formatted_results, list):
                for item in formatted_results:
                    item['source_db'] = db_info['name']
            return formatted_results
        
        else:
            logger.warning(f"Database {db_id} not supported in legacy mode")
            return {'error': f"Database {db_id} not supported in legacy mode"}
    except Exception as e:
        logger.error(f"Error searching {db_id}: {str(e)}")
        return {'error': str(e)}

def main():
    """Main entry point for the CLI."""
    args = parse_args()
    
    console.print(Panel.fit(
        "[bold cyan]BioSearch CLI[/bold cyan]\n"
        f"Searching for: [bold]{args.query}[/bold]",
        border_style="cyan"
    ))
    
    start_time = time.time()
    
    # Perform search
    if args.server:
        results = search_via_server(args)
    else:
        results = search_directly(args)
    
    elapsed_time = time.time() - start_time
    
    if results:
        console.print(f"Search completed in [cyan]{elapsed_time:.2f}[/cyan] seconds")
        
        # Display results
        display_results(results, args.format, args)
        
        # Export results if requested
        if args.output:
            export_results(results, args.output)
    else:
        console.print("[bold red]Search failed or no results returned.[/bold red]")
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main()) 