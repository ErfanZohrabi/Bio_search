from flask import Flask, render_template, request, jsonify, redirect, url_for, Response
import requests
import json
import asyncio
import aiohttp
import time
import os
import logging
from dotenv import load_dotenv
from api import (
    search_ncbi,
    search_uniprot,
    search_drugbank,
    format_ncbi_gene_results,
    format_pubmed_results,
    format_uniprot_results,
    format_drugbank_results
)
from api.db_helpers import ssl_context, NCBI_API_KEY
from api.cache import cache
from api.search_engine import unified_search, search_engine
import ssl
import datetime

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Check if we're in mock mode
env_mock_mode = os.environ.get('BIOSEARCH_MOCK_MODE', 'false').lower()
MOCK_MODE = env_mock_mode in ('true', '1', 't', 'yes')

# FORCE DISABLE MOCK MODE
MOCK_MODE = False

logger.info(f"Environment BIOSEARCH_MOCK_MODE value: '{env_mock_mode}'")
if MOCK_MODE:
    logger.info("MOCK MODE ENABLED: Using mock data instead of real API calls")
else:
    logger.info("MOCK MODE DISABLED: Using real API calls")

app = Flask(__name__)

# Define search_pubmed as a wrapper around search_ncbi
async def search_pubmed(session, query, retmax=10, ssl_context=None):
    """Search PubMed database using NCBI E-utilities."""
    if MOCK_MODE:
        logger.info(f"Using mock mode for PubMed search: {query}")
    elif NCBI_API_KEY:
        logger.info(f"Using NCBI API key for PubMed search")
    else:
        logger.warning(f"No NCBI API key found for PubMed search - rate limits will apply")
    
    return await search_ncbi(session, 'pubmed', query, retmax)

# Supported databases and their configurations
DATABASES = {
    'ncbi': {
        'name': 'NCBI',
        'db_type': 'gene',
        'formatter': format_ncbi_gene_results,
        'search_func': search_ncbi,
        'format_func': format_ncbi_gene_results,
        'badge_class': 'badge-ncbi'
    },
    'pubmed': {
        'name': 'PubMed',
        'db_type': 'pubmed',
        'formatter': format_pubmed_results,
        'search_func': search_pubmed,
        'format_func': format_pubmed_results,
        'badge_class': 'badge-pubmed'
    },
    'uniprot': {
        'name': 'UniProt',
        'formatter': format_uniprot_results,
        'search_func': search_uniprot,
        'format_func': format_uniprot_results,
        'badge_class': 'badge-uniprot'
    },
    'drugbank': {
        'name': 'DrugBank',
        'formatter': format_drugbank_results,
        'search_func': search_drugbank,
        'format_func': format_drugbank_results,
        'badge_class': 'badge-drugbank'
    },
    'kegg': {
        'name': 'KEGG',
        'description': 'Pathway database'
    },
    'pdb': {
        'name': 'PDB',
        'description': 'Protein structure database'
    },
    'ensembl': {
        'name': 'Ensembl',
        'description': 'Genomic database'
    }
}

# Create a custom SSL context that doesn't verify certificates
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

@app.route('/')
def home():
    """Render the home page."""
    return render_template('index.html', databases=DATABASES)

@app.route('/search', methods=['POST'])
def search():
    """Handle search requests from the frontend."""
    query = request.form.get('query', '')
    selected_dbs = request.form.getlist('databases') or list(DATABASES.keys())
    
    # Extract filters from the request
    filters = {}
    organism = request.form.get('organism')
    if organism:
        filters['organism'] = organism
    
    date_from = request.form.get('date_from')
    if date_from:
        filters['date_from'] = date_from
    
    date_to = request.form.get('date_to')
    if date_to:
        filters['date_to'] = date_to
    
    result_type = request.form.get('result_type')
    if result_type:
        filters['result_type'] = result_type
    
    # Get limit parameter with default of 10
    limit = int(request.form.get('limit', 10))
    
    logger.info(f"Search request for: '{query}' in databases: {selected_dbs}, filters: {filters}, limit: {limit}")
    
    # Check if legacy search should be used (for backward compatibility)
    use_legacy = request.form.get('use_legacy', 'false').lower() == 'true'
    
    if use_legacy:
        # Legacy search using the old method
        results = asyncio.run(search_all_databases(query, selected_dbs, limit))
    else:
        # Use the new unified search engine
        try:
            results = asyncio.run(unified_search(query, selected_dbs, filters, limit))
            
            # Adapt the results to match the format expected by the frontend
            adapted_results = {}
            if 'results' in results:
                # Process genes (NCBI, Ensembl)
                if 'genes' in results['results'] and results['results']['genes']:
                    ncbi_genes = [g for g in results['results']['genes'] if g.get('source_db') == 'NCBI']
                    ensembl_genes = [g for g in results['results']['genes'] if g.get('source_db') == 'Ensembl']
                    
                    if ncbi_genes:
                        adapted_results['NCBI'] = ncbi_genes
                    
                    if ensembl_genes:
                        adapted_results['Ensembl'] = ensembl_genes
                
                # Process proteins (UniProt)
                if 'proteins' in results['results'] and results['results']['proteins']:
                    # Get all proteins regardless of source_db for now
                    uniprot_proteins = results['results']['proteins']
                    
                    if uniprot_proteins:
                        adapted_results['UniProt'] = uniprot_proteins
                
                # Process pathways (KEGG)
                if 'pathways' in results['results'] and results['results']['pathways']:
                    # Get all pathways regardless of source_db for now
                    kegg_pathways = results['results']['pathways']
                    
                    if kegg_pathways:
                        adapted_results['KEGG'] = kegg_pathways
                
                # Process structures (PDB)
                if 'structures' in results['results'] and results['results']['structures']:
                    # Get all structures regardless of source_db for now
                    pdb_structures = results['results']['structures']
                    
                    if pdb_structures:
                        adapted_results['PDB'] = pdb_structures
                
                # Process drugs (DrugBank)
                if 'drugs' in results['results'] and results['results']['drugs']:
                    # Get all drugs regardless of source_db for now
                    drugbank_drugs = results['results']['drugs']
                    
                    if drugbank_drugs:
                        adapted_results['DrugBank'] = drugbank_drugs
                
                # Process publications (PubMed)
                if 'publications' in results['results'] and results['results']['publications']:
                    # Get all publications regardless of source_db for now 
                    pubmed_pubs = results['results']['publications']
                    
                    if pubmed_pubs:
                        adapted_results['PubMed'] = pubmed_pubs
                
                # Include any other results
                if 'other' in results['results']:
                    for db_name, db_results in results['results']['other'].items():
                        adapted_results[db_name.upper()] = db_results
            
            # Return the adapted results
            results = adapted_results
        except Exception as e:
            logger.error(f"Error in unified search: {str(e)}")
            return jsonify({"error": str(e)})
    
    return jsonify(results)

async def search_all_databases(query, selected_dbs, limit=10):
    """Legacy method: Search across multiple biological databases asynchronously."""
    tasks = []
    # Configure the session with SSL context
    connector = aiohttp.TCPConnector(ssl=ssl_context)
    async with aiohttp.ClientSession(connector=connector) as session:
        for db_id in selected_dbs:
            if db_id in DATABASES:
                tasks.append(search_database(session, db_id, query, limit))
        
        results = await asyncio.gather(*tasks)
    
    # Combine results from all databases
    all_results = {}
    for db_id, db_results in zip(selected_dbs, results):
        if db_id in DATABASES:
            all_results[DATABASES[db_id]['name']] = db_results
    
    return all_results

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

@app.route('/api_docs')
def api_docs():
    return render_template('api_docs.html')

@app.route('/api/search', methods=['GET', 'POST'])
def api_search():
    if request.method == 'POST':
        data = request.get_json() or {}
        query = data.get('query', '')
        databases_str = data.get('databases', 'ncbi,pubmed,uniprot,drugbank')
        organism = data.get('organism', 'human')
        limit = int(data.get('limit', 10))
        date_from = data.get('date_from')
        date_to = data.get('date_to')
        result_type = data.get('result_type')
    else:
        query = request.args.get('query', '')
        databases_str = request.args.get('databases', 'ncbi,pubmed,uniprot,drugbank')
        organism = request.args.get('organism', 'human')
        limit = int(request.args.get('limit', 10))
        date_from = request.args.get('date_from')
        date_to = request.args.get('date_to')
        result_type = request.args.get('result_type')
    
    if not query:
        return jsonify({"error": "No query provided"}), 400
    
    databases = [db.strip().lower() for db in databases_str.split(',') if db.strip()]
    # Use all databases if none specified
    if not databases:
        databases = list(DATABASES.keys())
    
    # Check if specified databases are valid
    invalid_dbs = [db for db in databases if db not in DATABASES]
    if invalid_dbs:
        return jsonify({"error": f"Invalid databases: {', '.join(invalid_dbs)}"}), 400
    
    # Prepare results structure
    search_results = {
        "query": query,
        "timestamp": datetime.datetime.now().isoformat(),
        "results": {},
        "result_counts": {}
    }
    
    # Search each database
    for db_name in databases:
        if db_name in DATABASES:
            db_info = DATABASES[db_name]
            
            try:
                # Search the database
                results = db_info['search_func'](query, ssl_context=ssl_context)
                
                # Format the results
                formatted_results = db_info['format_func'](results, limit=limit)
                
                # Apply filters if needed
                if organism and organism != 'all':
                    formatted_results = [r for r in formatted_results if 'organism' not in r or r.get('organism', '').lower() == organism.lower()]
                
                if date_from or date_to:
                    filtered_results = []
                    for r in formatted_results:
                        # Skip if no date field
                        if 'date' not in r and 'year' not in r:
                            continue
                        
                        # Extract date
                        result_date = None
                        if 'date' in r:
                            try:
                                result_date = datetime.datetime.strptime(r['date'], '%Y-%m-%d')
                            except ValueError:
                                continue
                        elif 'year' in r:
                            try:
                                result_date = datetime.datetime(int(r['year']), 1, 1)
                            except (ValueError, TypeError):
                                continue
                        
                        if result_date:
                            # Apply date_from filter
                            if date_from:
                                try:
                                    from_date = datetime.datetime.strptime(date_from, '%Y-%m-%d')
                                    if result_date < from_date:
                                        continue
                                except ValueError:
                                    pass
                            
                            # Apply date_to filter
                            if date_to:
                                try:
                                    to_date = datetime.datetime.strptime(date_to, '%Y-%m-%d')
                                    if result_date > to_date:
                                        continue
                                except ValueError:
                                    pass
                        
                        filtered_results.append(r)
                    
                    formatted_results = filtered_results
                
                if result_type:
                    formatted_results = [r for r in formatted_results if 'type' in r and r['type'].lower() == result_type.lower()]
                
                # Group results by type
                for result in formatted_results:
                    result_type = result.get('type', 'unknown')
                    if result_type not in search_results['results']:
                        search_results['results'][result_type] = []
                    
                    # Add source database info
                    result['source_db'] = db_info['name']
                    result['badge_class'] = db_info['badge_class']
                    
                    search_results['results'][result_type].append(result)
            
            except Exception as e:
                app.logger.error(f"Error searching {db_name}: {str(e)}")
                # Continue with other databases even if one fails
    
    # Calculate result counts
    for result_type, results in search_results['results'].items():
        search_results['result_counts'][result_type] = len(results)
    
    return jsonify(search_results)

@app.route('/about')
def about():
    """Render the about page."""
    return render_template('about.html', databases=DATABASES)

@app.errorhandler(404)
def page_not_found(e):
    """Handle 404 errors."""
    return render_template('404.html'), 404

@app.errorhandler(500)
def server_error(e):
    """Handle 500 errors."""
    logger.error(f"Server error: {str(e)}")
    return render_template('500.html'), 500

@app.cli.command("init-cache")
def init_cache_command():
    """Initialize the Redis cache."""
    try:
        asyncio.run(cache.initialize_async())
        app.logger.info("Cache initialized successfully")
    except Exception as e:
        app.logger.error(f"Cache initialization failed: {str(e)}")

# Replace before_first_request (removed in Flask 2.x) with a new approach
# Using 'with app.app_context()' pattern for initialization
def initialize_app():
    """Initialize application components."""
    # Initialize cache asynchronously
    try:
        asyncio.run(cache.initialize_async())
        app.logger.info("Cache initialized on startup")
    except Exception as e:
        app.logger.error(f"Cache initialization failed: {str(e)}")

# Register the function to run when the application starts
   if __name__ == "__main__":
       import os
       port = int(os.environ.get("PORT", 5000))
       app.run(host="0.0.0.0", port=port)
