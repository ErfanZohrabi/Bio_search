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
from api.string_db import get_network_url as get_string_network_url
from api.stitch import get_drug_network_url as get_stitch_network_url
import ssl
import datetime
import argparse
import re
import urllib.parse
from typing import Dict, List, Any, Optional, Union
from pydantic import BaseModel, Field, validator
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

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

# Define Pydantic models for data validation
class PublicationNode(BaseModel):
    id: str  # PMID
    label: str  # Title
    authors: str
    year: str
    journal: str
    type: str  # source, citing, cited, secondary
    
class NetworkEdge(BaseModel):
    source: str
    target: str
    type: str  # cites, cited_by, cocitation, secondary
    weight: Optional[float] = 1.0
    
class NetworkData(BaseModel):
    source_pmid: str
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    metadata: Dict[str, Any] = {}
    
    class Config:
        # Allow extra fields
        extra = "allow"
        # Make the model more forgiving of missing data
        validate_assignment = True
        arbitrary_types_allowed = True

# Enhanced HTTP client with retry logic
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((aiohttp.ClientError, asyncio.TimeoutError))
)
async def robust_fetch(session, url, params=None, timeout=60.0):
    """
    Enhanced HTTP client with retry logic and better error handling
    """
    try:
        logger.info(f"Fetching URL: {url} with params: {params}")
        async with session.get(url, params=params, timeout=timeout) as response:
            if response.status == 429:  # Rate limit
                logger.warning(f"Rate limit hit for {url}. Retrying...")
                raise aiohttp.ClientResponseError(
                    response.request_info, 
                    response.history, 
                    status=response.status, 
                    message="Rate Limited"
                )
                
            response.raise_for_status()  # Raise exception for 4xx/5xx errors
            
            # Decide whether to return json or text based on content type
            content_type = response.headers.get('Content-Type', '')
            logger.debug(f"Response content type: {content_type}")
            
            if 'application/json' in content_type:
                result = await response.json()
                logger.debug(f"JSON response successfully parsed")
                return result
            else:
                result = await response.text()
                logger.debug(f"Text response received, length: {len(result)}")
                return result
                
    except asyncio.TimeoutError:
        logger.error(f"Timeout error fetching {url}")
        # Return a special error object instead of raising the exception
        return {
            "error": "Request timed out. The server is taking too long to respond.",
            "timeout_error": True
        }
        
    except aiohttp.ClientConnectorError as e:
        logger.error(f"Connection error fetching {url}: {e}")
        # Return a special error object for connection issues
        return {
            "error": f"Connection error: {str(e)}",
            "connection_error": True
        }
        
    except aiohttp.ClientError as e:
        logger.error(f"Client error fetching {url}: {e}")
        # Return a special error object for other client errors
        return {
            "error": f"Client error: {str(e)}",
            "client_error": True
        }

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

@app.route('/network')
def network_viewer():
    """Render the network visualization page."""
    identifiers = request.args.get('identifiers', '')
    network_type = request.args.get('type', 'string')  # string or stitch
    
    if not identifiers:
        return render_template('network_viewer.html', identifier_list=[])
    
    identifier_list = identifiers.split(',')
    logger.info(f"Network visualization requested for {len(identifier_list)} identifiers, type: {network_type}")
    
    return render_template('network_viewer.html', identifier_list=identifier_list, network_type=network_type)

@app.route('/api/network/string')
def string_network():
    """API endpoint to get network data from STRING db."""
    identifiers = request.args.get('identifiers', '')
    species = request.args.get('species', '9606')  # Default: human
    score = request.args.get('score', '0.4')       # Default: medium confidence
    network_type = request.args.get('network_type', '')  # physical, functional, etc.
    
    # Call directly to STRING with the appropriate parameters
    network_url = get_string_network_url(identifiers, species, score, network_type)
    
    logger.info(f"STRING network URL: {network_url}")
    return jsonify({"url": network_url})

@app.route('/api/network/string-data')
async def string_network_data():
    """API endpoint to get network data from STRING API in Cytoscape format."""
    identifiers = request.args.get('identifiers', '')
    species = request.args.get('species', '9606')  # Default: human
    score = request.args.get('score', '0.4')       # Default: medium confidence
    network_type = request.args.get('network_type', '')  # physical, functional, etc.
    
    if not identifiers:
        return jsonify({"error": "No identifiers provided"}), 400
    
    identifier_list = identifiers.split(',')
    logger.info(f"STRING network data requested for {len(identifier_list)} identifiers")
    
    try:
        # Clean and validate identifiers
        cleaned_identifiers = []
        for identifier in identifier_list:
            # Remove any whitespace and special characters except for dots and dashes
            cleaned = identifier.strip()
            if cleaned:
                cleaned_identifiers.append(cleaned)
        
        if not cleaned_identifiers:
            return jsonify({"error": "No valid identifiers provided after cleaning"}), 400
            
        logger.info(f"Cleaned identifiers: {cleaned_identifiers}")
        
        # Use the enhanced HTTP client to fetch data from STRING API
        connector = aiohttp.TCPConnector(ssl=ssl_context)
        async with aiohttp.ClientSession(connector=connector) as session:
            # Fetch network data from STRING API
            string_api_url = "https://string-db.org/api/json/network"
            params = {
                "identifiers": "%0d".join(cleaned_identifiers),  # STRING API requires %0d separator
                "species": species,
                "required_score": score
            }
            
            if network_type:
                params["network_type"] = network_type
            
            logger.info(f"STRING API request parameters: {params}")    
            data = await robust_fetch(session, string_api_url, params)
            
            # Check for special error objects
            if isinstance(data, dict) and (
                data.get("timeout_error") or 
                data.get("connection_error") or 
                data.get("client_error")
            ):
                error_msg = data.get("error", "Unknown error occurred")
                logger.error(f"Error fetching STRING data: {error_msg}")
                return jsonify({"error": error_msg}), 503  # Service Unavailable
            
            # Ensure data is properly parsed as JSON if it's a string
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except json.JSONDecodeError:
                    logger.error(f"Error decoding JSON from STRING API: {data[:100]}...")
                    return jsonify({"error": "Invalid response from STRING API"}), 500
            
            # Handle case where data is not a list
            if not isinstance(data, list):
                # Check if it's an error message from STRING API
                if isinstance(data, dict) and "error" in data:
                    error_msg = data.get("error", "Unknown STRING API error")
                    logger.error(f"STRING API returned error: {error_msg}")
                    return jsonify({"error": f"STRING API error: {error_msg}"}), 400
                
                logger.error(f"Expected list from STRING API, got {type(data)}: {str(data)[:100]}...")
                return jsonify({"error": "Unexpected response format from STRING API"}), 500
                
            # Convert to Cytoscape.js format
            nodes = []
            edges = []
            seen_nodes = set()
            
            # Process network data
            for item in data:
                if not isinstance(item, dict):
                    logger.warning(f"Skipping non-dictionary item in STRING response: {item}")
                    continue
                    
                source_id = item.get("preferredName_A") or item.get("stringId_A", f"node_{len(seen_nodes)}")
                target_id = item.get("preferredName_B") or item.get("stringId_B", f"node_{len(seen_nodes)+1}")
                score = item.get("score", 0)
                
                # Add source node if not seen before
                if source_id not in seen_nodes:
                    nodes.append({
                        "data": {
                            "id": source_id,
                            "label": item.get("preferredName_A", source_id),
                            "string_id": item.get("stringId_A", ""),
                            "type": "protein"
                        }
                    })
                    seen_nodes.add(source_id)
                
                # Add target node if not seen before
                if target_id not in seen_nodes:
                    nodes.append({
                        "data": {
                            "id": target_id,
                            "label": item.get("preferredName_B", target_id),
                            "string_id": item.get("stringId_B", ""),
                            "type": "protein"
                        }
                    })
                    seen_nodes.add(target_id)
                
                # Add edge
                edges.append({
                    "data": {
                        "id": f"{source_id}-{target_id}",
                        "source": source_id,
                        "target": target_id,
                        "weight": score,
                        "interaction": item.get("action", "interaction")
                    }
                })
            
            # If we have no nodes/edges but didn't get an error from STRING
            if not nodes:
                logger.warning(f"STRING API returned no nodes for identifiers: {cleaned_identifiers}")
                return jsonify({"error": "No protein interactions found. Try using official UniProt or STRING identifiers."}), 404
            
            return jsonify({
                "elements": {
                    "nodes": nodes,
                    "edges": edges
                },
                "metadata": {
                    "total_nodes": len(nodes),
                    "total_edges": len(edges),
                    "source_identifiers": cleaned_identifiers,
                    "species": species,
                    "score": score
                }
            })
    
    except Exception as e:
        logger.error(f"Error fetching STRING network data: {str(e)}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@app.route('/api/network/stitch')
def stitch_network():
    """API endpoint to get network data from STITCH db."""
    identifiers = request.args.get('identifiers', '')
    species = request.args.get('species', '9606')  # Default: human
    score = request.args.get('score', '0.4')       # Default: medium confidence
    network_type = request.args.get('network_type', '')  # physical, functional, etc.
    
    # Call directly to STITCH with the appropriate parameters
    network_url = get_stitch_network_url(identifiers, species, score, network_type)
    
    logger.info(f"STITCH network URL: {network_url}")
    return jsonify({"url": network_url})

@app.route('/api/network/stitch-data')
async def stitch_network_data():
    """API endpoint to get network data from STITCH API in Cytoscape format."""
    identifiers = request.args.get('identifiers', '')
    species = request.args.get('species', '9606')  # Default: human
    score = request.args.get('score', '0.4')       # Default: medium confidence
    network_type = request.args.get('network_type', '')  # physical, functional, etc.
    
    if not identifiers:
        return jsonify({"error": "No identifiers provided"}), 400
    
    identifier_list = identifiers.split(',')
    logger.info(f"STITCH network data requested for {len(identifier_list)} identifiers")
    
    try:
        # Clean and validate identifiers
        cleaned_identifiers = []
        for identifier in identifier_list:
            # Remove any whitespace and special characters except for dots and dashes
            cleaned = identifier.strip()
            if cleaned:
                cleaned_identifiers.append(cleaned)
        
        if not cleaned_identifiers:
            return jsonify({"error": "No valid identifiers provided after cleaning"}), 400
            
        logger.info(f"Cleaned identifiers for STITCH: {cleaned_identifiers}")
        
        # Use the enhanced HTTP client to fetch data from STITCH API
        connector = aiohttp.TCPConnector(ssl=ssl_context)
        async with aiohttp.ClientSession(connector=connector) as session:
            # Fetch network data from STITCH API
            stitch_api_url = "https://stitch.embl.de/api/json/network"
            params = {
                "identifiers": "%0d".join(cleaned_identifiers),  # STITCH API requires %0d separator
                "species": species,
                "required_score": score
            }
            
            if network_type:
                params["network_type"] = network_type
             
            logger.info(f"STITCH API request parameters: {params}")   
            data = await robust_fetch(session, stitch_api_url, params)
            
            # Check for special error objects
            if isinstance(data, dict) and (
                data.get("timeout_error") or 
                data.get("connection_error") or 
                data.get("client_error")
            ):
                error_msg = data.get("error", "Unknown error occurred")
                logger.error(f"Error fetching STITCH data: {error_msg}")
                return jsonify({"error": error_msg}), 503  # Service Unavailable
            
            # Ensure data is properly parsed as JSON if it's a string
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except json.JSONDecodeError:
                    logger.error(f"Error decoding JSON from STITCH API: {data[:100]}...")
                    return jsonify({"error": "Invalid response from STITCH API"}), 500
            
            # Handle case where data is not a list
            if not isinstance(data, list):
                # Check if it's an error message from STITCH API
                if isinstance(data, dict) and "error" in data:
                    error_msg = data.get("error", "Unknown STITCH API error")
                    logger.error(f"STITCH API returned error: {error_msg}")
                    return jsonify({"error": f"STITCH API error: {error_msg}"}), 400
                
                logger.error(f"Expected list from STITCH API, got {type(data)}: {str(data)[:100]}...")
                return jsonify({"error": "Unexpected response format from STITCH API"}), 500
            
            # Convert to Cytoscape.js format
            nodes = []
            edges = []
            seen_nodes = set()
            
            # Process network data
            for item in data:
                if not isinstance(item, dict):
                    logger.warning(f"Skipping non-dictionary item in STITCH response: {item}")
                    continue
                    
                source_id = item.get("preferredName_A") or item.get("stitchId_A", f"node_{len(seen_nodes)}")
                target_id = item.get("preferredName_B") or item.get("stitchId_B", f"node_{len(seen_nodes)+1}")
                score = item.get("score", 0)
                
                # Determine if this is a chemical or protein
                source_type = "chemical" if isinstance(item.get("stitchId_A", ""), str) and item.get("stitchId_A", "").startswith("CID") else "protein"
                target_type = "chemical" if isinstance(item.get("stitchId_B", ""), str) and item.get("stitchId_B", "").startswith("CID") else "protein"
                
                # Add source node if not seen before
                if source_id not in seen_nodes:
                    nodes.append({
                        "data": {
                            "id": source_id,
                            "label": item.get("preferredName_A", source_id),
                            "stitch_id": item.get("stitchId_A", ""),
                            "type": source_type
                        }
                    })
                    seen_nodes.add(source_id)
                
                # Add target node if not seen before
                if target_id not in seen_nodes:
                    nodes.append({
                        "data": {
                            "id": target_id,
                            "label": item.get("preferredName_B", target_id),
                            "stitch_id": item.get("stitchId_B", ""),
                            "type": target_type
                        }
                    })
                    seen_nodes.add(target_id)
                
                # Add edge
                edges.append({
                    "data": {
                        "id": f"{source_id}-{target_id}",
                        "source": source_id,
                        "target": target_id,
                        "weight": score,
                        "interaction": item.get("action", "interaction")
                    }
                })
            
            # If we have no nodes/edges but didn't get an error from STITCH
            if not nodes:
                logger.warning(f"STITCH API returned no nodes for identifiers: {cleaned_identifiers}")
                return jsonify({"error": "No protein-drug interactions found. Try using official UniProt or chemical identifiers."}), 404
            
            return jsonify({
                "elements": {
                    "nodes": nodes,
                    "edges": edges
                },
                "metadata": {
                    "total_nodes": len(nodes),
                    "total_edges": len(edges),
                    "source_identifiers": cleaned_identifiers,
                    "species": species,
                    "score": score
                }
            })
    
    except Exception as e:
        logger.error(f"Error fetching STITCH network data: {str(e)}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@app.route('/publication-network')
def publication_network():
    """Render the publication network visualization page."""
    query = request.args.get('query', '')
    pmid = request.args.get('pmid', '')
    
    logger.info(f"Publication network visualization requested, PMID: {pmid}, query: {query}")
    return render_template('publication_network.html', pmid=pmid, query=query)

@app.route('/api/network/publication')
async def publication_cocitation_network():
    """API endpoint to get co-citation network data for publications."""
    query = request.args.get('query', '')
    pmid = request.args.get('pmid', '')
    limit = int(request.args.get('limit', 30))
    
    if not query and not pmid:
        logger.warning("API request missing both query and PMID")
        return jsonify({"error": "No query or PMID provided"}), 400
    
    # Validate PMID format if provided
    if pmid and not pmid.isdigit():
        logger.warning(f"Invalid PMID format: {pmid}")
        return jsonify({"error": "Invalid PMID format. PMIDs must be numeric identifiers."}), 400
    
    try:
        logger.info(f"Publication network requested - PMID: '{pmid}', Query: '{query}', Limit: {limit}")
        
        # If we have a query but no PMID, search for PMIDs first
        if query and not pmid:
            logger.info(f"Searching for PMIDs with query: {query}")
            pmids = await search_pubmed_pmids(query, limit=5)
            
            # Check for timeout or connection errors from the PMID search
            if isinstance(pmids, dict) and "error" in pmids:
                logger.warning(f"Error in PMID search: {pmids['error']}")
                return jsonify({"error": pmids["error"]}), 503  # Service Unavailable
                
            if not pmids:
                logger.warning(f"No publications found for query: {query}")
                return jsonify({"error": f"No publications found for query: {query}"}), 404
            pmid = pmids[0]  # Use the first PMID
            logger.info(f"Using first PMID from search results: {pmid}")
        
        # Build the co-citation network
        try:
            # Set a higher timeout for network building operations
            network_data = await build_cocitation_network(pmid, limit)
            
            # Check for errors in network data
            if (network_data.get('metadata') and 
                network_data['metadata'].get('error') and
                len(network_data.get('nodes', [])) <= 1):
                    
                logger.warning(f"Network generation returned error: {network_data['metadata']['error']}")
                # Don't return 500, return 200 with minimal data and error in metadata
                # The client can handle displaying the error
            
            logger.info(f"Built co-citation network with {len(network_data.get('nodes', []))} nodes and {len(network_data.get('edges', []))} edges")
            
            # Ensure we have valid data structure (at least the source node)
            if not network_data.get('nodes'):
                logger.warning(f"Network data missing nodes for PMID: {pmid}")
                return jsonify({"error": "Could not generate network data - no publication information found"}), 404
                
            # Validate the network data using the Pydantic model
            try:
                # Convert to Pydantic model and back to dict to ensure validation
                validated_data = NetworkData(
                    source_pmid=pmid,
                    nodes=network_data["nodes"],
                    edges=network_data["edges"],
                    metadata=network_data["metadata"]
                ).model_dump()
                
                logger.info(f"Returning validated network data with {len(validated_data['nodes'])} nodes and {len(validated_data['edges'])} edges")
                return jsonify(validated_data)
            except Exception as e:
                logger.error(f"Error validating network data: {str(e)}", exc_info=True)
                # Return the original data as fallback with a warning message
                network_data["metadata"]["validation_warning"] = f"Data validation failed: {str(e)}"
                return jsonify(network_data)
        except Exception as e:
            logger.error(f"Error in build_cocitation_network: {str(e)}", exc_info=True)
            return jsonify({"error": f"Network generation error: {str(e)}"}), 500
    
    except Exception as e:
        logger.error(f"Unexpected error in publication network endpoint: {str(e)}", exc_info=True)
        return jsonify({"error": f"Server error: {str(e)}"}), 500

async def search_pubmed_pmids(query, limit=10):
    """Search PubMed and return a list of PMIDs."""
    logger.info(f"Searching PubMed for: {query}")
    
    connector = aiohttp.TCPConnector(ssl=ssl_context)
    async with aiohttp.ClientSession(connector=connector) as session:
        try:
            data = await search_pubmed(session, query, retmax=limit)
            if not data or 'esearchresult' not in data:
                logger.warning(f"No results found in PubMed for query: {query}")
                return []
            
            pmids = data['esearchresult'].get('idlist', [])
            logger.info(f"Found {len(pmids)} PMIDs for query: {query}")
            return pmids
        except Exception as e:
            logger.error(f"Error searching PubMed: {str(e)}")
            return []

async def get_citing_papers(pmid, limit=30):
    """Get papers that cite the given PMID."""
    logger.info(f"Getting papers citing PMID: {pmid}")
    
    pmid = str(pmid).strip()
    citing_papers = []
    
    connector = aiohttp.TCPConnector(ssl=ssl_context)
    async with aiohttp.ClientSession(connector=connector) as session:
        try:
            # Use the Links API to find citing articles
            elink_url = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi'
            params = {
                'dbfrom': 'pubmed',
                'linkname': 'pubmed_pubmed_citedin',
                'id': pmid,
                'retmode': 'json',
                'retmax': limit
            }
            
            if NCBI_API_KEY:
                params['api_key'] = NCBI_API_KEY
            
            data = await robust_fetch(session, elink_url, params)
            
            if isinstance(data, str):
                # Parse JSON if it's returned as a string
                data = json.loads(data)
            
            # Extract PMIDs of citing papers
            try:
                link_set = data.get('linksets', [{}])[0]
                links = link_set.get('linksetdbs', [])
                for link in links:
                    if link.get('linkname') == 'pubmed_pubmed_citedin':
                        citing_papers = [str(id_) for id_ in link.get('links', [])]
                        break
            except (IndexError, KeyError) as e:
                logger.warning(f"Error parsing citing papers data: {str(e)}")
            
            logger.info(f"Found {len(citing_papers)} papers citing PMID: {pmid}")
            return citing_papers[:limit]  # Limit the number of results
            
        except Exception as e:
            logger.error(f"Error getting citing papers for PMID {pmid}: {str(e)}")
            return []

async def get_cited_papers(pmid, limit=30):
    """Get papers that are cited by the given PMID."""
    logger.info(f"Getting papers cited by PMID: {pmid}")
    
    pmid = str(pmid).strip()
    cited_papers = []
    
    connector = aiohttp.TCPConnector(ssl=ssl_context)
    async with aiohttp.ClientSession(connector=connector) as session:
        try:
            # Use the Links API to find cited articles
            elink_url = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi'
            params = {
                'dbfrom': 'pubmed',
                'linkname': 'pubmed_pubmed_refs',
                'id': pmid,
                'retmode': 'json',
                'retmax': limit
            }
            
            if NCBI_API_KEY:
                params['api_key'] = NCBI_API_KEY
            
            data = await robust_fetch(session, elink_url, params)
            
            if isinstance(data, str):
                # Parse JSON if it's returned as a string
                data = json.loads(data)
            
            # Extract PMIDs of cited papers
            try:
                link_set = data.get('linksets', [{}])[0]
                links = link_set.get('linksetdbs', [])
                for link in links:
                    if link.get('linkname') == 'pubmed_pubmed_refs':
                        cited_papers = [str(id_) for id_ in link.get('links', [])]
                        break
            except (IndexError, KeyError) as e:
                logger.warning(f"Error parsing cited papers data: {str(e)}")
            
            logger.info(f"Found {len(cited_papers)} papers cited by PMID: {pmid}")
            return cited_papers[:limit]  # Limit the number of results
            
        except Exception as e:
            logger.error(f"Error getting cited papers for PMID {pmid}: {str(e)}")
            return []

async def get_publication_metadata(pmids):
    """Get metadata for a list of PMIDs."""
    if not pmids:
        return {}
    
    # Ensure all PMIDs are strings
    pmids = [str(pmid) for pmid in pmids]
    logger.info(f"Getting metadata for {len(pmids)} PMIDs")
    
    # Convert list of PMIDs to comma-separated string
    pmid_string = ','.join(pmids)
    
    connector = aiohttp.TCPConnector(ssl=ssl_context)
    async with aiohttp.ClientSession(connector=connector) as session:
        try:
            # Use the Summary API to get metadata
            esummary_url = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi'
            params = {
                'db': 'pubmed',
                'id': pmid_string,
                'retmode': 'json'
            }
            
            if NCBI_API_KEY:
                params['api_key'] = NCBI_API_KEY
            
            data = await robust_fetch(session, esummary_url, params)
            
            if isinstance(data, str):
                # Parse JSON if it's returned as a string
                data = json.loads(data)
            
            # Extract metadata for each PMID
            metadata = {}
            
            if not data or 'result' not in data:
                logger.warning(f"No metadata returned for PMIDs: {pmid_string[:100]}...")
                return metadata
            
            for pmid in pmids:
                pmid = str(pmid)  # Ensure it's a string
                try:
                    if pmid in data['result']:
                        paper_data = data['result'][pmid]
                        
                        # Extract author list
                        authors = []
                        for author in paper_data.get('authors', []):
                            name = author.get('name', '')
                            if name and name != 'et al.':
                                authors.append(name)
                        
                        author_string = ', '.join(authors[:3])
                        if len(authors) > 3:
                            author_string += ' et al.'
                        
                        # Extract and format publication date
                        pub_date = paper_data.get('pubdate', '')
                        pub_year = ''
                        if pub_date:
                            # Try to extract year from various date formats
                            year_match = re.search(r'\b(19|20)\d{2}\b', pub_date)
                            if year_match:
                                pub_year = year_match.group(0)
                        
                        # Generate a clean title
                        title = paper_data.get('title', 'Unknown Title')
                        title = title.strip()
                        
                        # Extract journal info
                        journal = paper_data.get('source', 'Unknown Journal')
                        
                        metadata[pmid] = {
                            'title': title,
                            'authors': author_string,
                            'year': pub_year,
                            'journal': journal
                        }
                    else:
                        # Create placeholder entry for missing PMIDs
                        logger.warning(f"No metadata found for PMID {pmid} in the API response")
                        metadata[pmid] = {
                            'title': f"Paper {pmid}",
                            'authors': 'Unknown Authors',
                            'year': '',
                            'journal': 'Unknown Journal'
                        }
                except Exception as e:
                    logger.error(f"Error extracting metadata for PMID {pmid}: {str(e)}")
                    # Create a placeholder for failed entries
                    metadata[pmid] = {
                        'title': f"Paper {pmid}",
                        'authors': 'Unknown Authors',
                        'year': '',
                        'journal': 'Unknown Journal'
                    }
            
            logger.info(f"Retrieved metadata for {len(metadata)} PMIDs")
            return metadata
            
        except Exception as e:
            logger.error(f"Error getting metadata for PMIDs: {str(e)}")
            # Create placeholder entries for all PMIDs
            return {pmid: {
                'title': f"Paper {pmid}",
                'authors': 'Unknown Authors',
                'year': '',
                'journal': 'Unknown Journal'
            } for pmid in pmids}

async def build_cocitation_network(pmid, limit=30):
    """Build a co-citation network for a publication."""
    pmid = str(pmid)
    logger.info(f"Building co-citation network for PMID: {pmid}")
    
    try:
        # Define empty fallback values for all data
        citing_papers = []
        cited_papers = []
        all_pmids = set([pmid])  # Start with just the source PMID
        secondary_connections = []
        secondary_papers = set()

        # Use a longer timeout and wrap in try/except
        try:
            # Fetch citing and cited papers concurrently with a timeout
            citing_papers_task = asyncio.create_task(get_citing_papers(pmid, limit=limit))
            cited_papers_task = asyncio.create_task(get_cited_papers(pmid, limit=limit))
            
            # Wait for both tasks with a timeout
            done, pending = await asyncio.wait(
                [citing_papers_task, cited_papers_task], 
                timeout=30.0,  # 30 second timeout
                return_when=asyncio.ALL_COMPLETED
            )
            
            # Cancel any pending tasks
            for task in pending:
                task.cancel()
                
            # Process completed tasks
            if citing_papers_task in done and not citing_papers_task.exception():
                citing_papers = citing_papers_task.result()
            else:
                logger.warning(f"Failed to get citing papers for PMID {pmid}")
                
            if cited_papers_task in done and not cited_papers_task.exception():
                cited_papers = cited_papers_task.result()
            else:
                logger.warning(f"Failed to get cited papers for PMID {pmid}")
                
        except asyncio.TimeoutError:
            logger.warning(f"Timeout while fetching citation data for PMID: {pmid}")
        except Exception as e:
            logger.warning(f"Error fetching citation data: {str(e)}")
        
        # Continue with whatever data we have even if some parts failed
        logger.info(f"Found {len(cited_papers)} cited and {len(citing_papers)} citing papers for PMID: {pmid}")
        
        # Update all_pmids with the papers we found
        all_pmids.update([str(p) for p in citing_papers])
        all_pmids.update([str(p) for p in cited_papers])
        
        # Find secondary connections (citations between citing and cited papers)
        # Only proceed if we have some citing papers
        limit_for_secondary = min(3, len(citing_papers))
        if limit_for_secondary > 0:
            try:
                # Use a timeout for secondary connection fetching
                secondary_cited_tasks = []
                for i in range(limit_for_secondary):
                    if i < len(citing_papers):
                        secondary_cited_tasks.append(asyncio.create_task(
                            get_cited_papers(citing_papers[i], limit=10)
                        ))
                
                # Wait for tasks with timeout
                done, pending = await asyncio.wait(
                    secondary_cited_tasks,
                    timeout=20.0,  # 20 second timeout
                    return_when=asyncio.ALL_COMPLETED
                )
                
                # Cancel pending tasks
                for task in pending:
                    task.cancel()
                
                # Process completed tasks
                secondary_cited_results = []
                for i, task in enumerate(secondary_cited_tasks):
                    if task in done and not task.exception():
                        secondary_cited_results.append(task.result())
                    else:
                        secondary_cited_results.append([])  # Empty result for failed tasks
                
                # Process secondary cited papers
                for citing_idx, cited_list in enumerate(secondary_cited_results):
                    if citing_idx < len(citing_papers):
                        citing_pmid = citing_papers[citing_idx]
                        for cited_pmid in cited_list:
                            # Don't include the original paper as a secondary connection
                            if str(cited_pmid) != pmid:
                                secondary_connections.append({
                                    'source': str(citing_pmid),
                                    'target': str(cited_pmid),
                                    'type': 'cites'
                                })
                                secondary_papers.add(str(cited_pmid))
            except Exception as e:
                logger.warning(f"Error getting secondary cited connections: {str(e)}")
                # Continue without secondary connections
        
        # Add secondary papers to all_pmids
        all_pmids.update(secondary_papers)
        
        # Process remaining parts of the function with better error handling
        # Fetch metadata for all PMIDs
        metadata = {}
        try:
            if all_pmids:
                metadata = await get_publication_metadata(list(all_pmids))
        except Exception as e:
            logger.error(f"Error fetching publication metadata: {str(e)}")
            # Create fallback metadata
            metadata = {pmid: {
                'title': f"Paper {pmid}",
                'authors': 'Unknown Authors',
                'year': '',
                'journal': 'Unknown Journal'
            }}
        
        # Build nodes and edges for the network
        nodes = []
        edges = []
        
        # Ensure we have at least the source node
        source_metadata = metadata.get(pmid, {
            'title': f"Paper {pmid}",
            'authors': 'Unknown Authors',
            'year': '',
            'journal': 'Unknown Journal'
        })
        
        # Add the source node
        nodes.append({
            'id': pmid,
            'label': source_metadata.get('title', f"Paper {pmid}"),
            'authors': source_metadata.get('authors', 'Unknown Authors'),
            'year': source_metadata.get('year', ''),
            'journal': source_metadata.get('journal', 'Unknown Journal'),
            'type': 'source'
        })
        
        # Add citing paper nodes and edges
        for citing_pmid in citing_papers:
            citing_pmid = str(citing_pmid)
            citing_metadata = metadata.get(citing_pmid, {
                'title': f"Paper {citing_pmid}",
                'authors': 'Unknown Authors',
                'year': '',
                'journal': 'Unknown Journal'
            })
            
            nodes.append({
                'id': citing_pmid,
                'label': citing_metadata.get('title', f"Paper {citing_pmid}"),
                'authors': citing_metadata.get('authors', 'Unknown Authors'),
                'year': citing_metadata.get('year', ''),
                'journal': citing_metadata.get('journal', 'Unknown Journal'),
                'type': 'citing'
            })
            
            edges.append({
                'source': citing_pmid,
                'target': pmid,
                'type': 'cites'
            })
        
        # Add cited paper nodes and edges
        for cited_pmid in cited_papers:
            cited_pmid = str(cited_pmid)
            cited_metadata = metadata.get(cited_pmid, {
                'title': f"Paper {cited_pmid}",
                'authors': 'Unknown Authors',
                'year': '',
                'journal': 'Unknown Journal'
            })
            
            nodes.append({
                'id': cited_pmid,
                'label': cited_metadata.get('title', f"Paper {cited_pmid}"),
                'authors': cited_metadata.get('authors', 'Unknown Authors'),
                'year': cited_metadata.get('year', ''),
                'journal': cited_metadata.get('journal', 'Unknown Journal'),
                'type': 'cited'
            })
            
            edges.append({
                'source': pmid,
                'target': cited_pmid,
                'type': 'cites'
            })
        
        # Add secondary connection edges and nodes
        existing_node_ids = set(node['id'] for node in nodes)
        for pmid_sec in secondary_papers:
            pmid_sec = str(pmid_sec)
            if pmid_sec not in existing_node_ids:
                sec_metadata = metadata.get(pmid_sec, {
                    'title': f"Paper {pmid_sec}",
                    'authors': 'Unknown Authors',
                    'year': '',
                    'journal': 'Unknown Journal'
                })
                
                nodes.append({
                    'id': pmid_sec,
                    'label': sec_metadata.get('title', f"Paper {pmid_sec}"),
                    'authors': sec_metadata.get('authors', 'Unknown Authors'),
                    'year': sec_metadata.get('year', ''),
                    'journal': sec_metadata.get('journal', 'Unknown Journal'),
                    'type': 'secondary'
                })
                existing_node_ids.add(pmid_sec)
        
        for conn in secondary_connections:
            edges.append(conn)
        
        # Add co-citation relationships
        cocitation_edges = []
        
        # For each pair of cited papers, add a co-citation edge if we have at least 2 cited papers
        cited_list = list(cited_papers)
        if len(cited_list) >= 2:
            for i in range(len(cited_list)):
                for j in range(i + 1, len(cited_list)):
                    source_id = str(cited_list[i])
                    target_id = str(cited_list[j])
                    
                    cocitation_edges.append({
                        'source': source_id,
                        'target': target_id,
                        'type': 'cocitation',
                        'weight': 1  # Could be weighted by number of shared citations
                    })
        
        # Add co-citation edges to the main edges list
        edges.extend(cocitation_edges)
        
        # Prepare metadata for the response
        network_metadata = {
            'source_title': source_metadata.get('title', f"Paper {pmid}"),
            'citing_count': len(citing_papers),
            'cited_count': len(cited_papers),
            'secondary_count': len(secondary_papers),
            'total_nodes': len(nodes),
            'total_edges': len(edges),
            'cocitation_edges': len(cocitation_edges)
        }
        
        logger.info(f"Built network with {len(nodes)} nodes and {len(edges)} edges")
        
        # Return with at least the source node, even if we couldn't find any connections
        return {
            'source_pmid': pmid,
            'nodes': nodes,
            'edges': edges,
            'metadata': network_metadata
        }
    except Exception as e:
        logger.error(f"Error building co-citation network: {str(e)}", exc_info=True)
        # Return a minimal valid network with just the source node to prevent 500 errors
        return {
            'source_pmid': pmid,
            'nodes': [{
                'id': pmid,
                'label': f"Paper {pmid}",
                'authors': 'Unknown Authors',
                'year': '',
                'journal': 'Unknown Journal',
                'type': 'source'
            }],
            'edges': [],
            'metadata': {
                'error': str(e),
                'source_title': f"Paper {pmid}",
                'citing_count': 0,
                'cited_count': 0,
                'secondary_count': 0,
                'total_nodes': 1,
                'total_edges': 0,
                'cocitation_edges': 0
            }
        }

@app.errorhandler(404)
def page_not_found(e):
    """Handle 404 errors."""
    return render_template('404.html'), 404

@app.errorhandler(500)
def server_error(e):
    """Handle server errors."""
    logger.error(f"Server error: {str(e)}", exc_info=True)
    return render_template('500.html', error=str(e)), 500

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
if __name__ == '__main__':
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='BioSearch Web Application')
    parser.add_argument('--port', type=int, default=5000, help='Port to run the server on')
    parser.add_argument('--debug', action='store_true', help='Run in debug mode')
    args = parser.parse_args()
    
    # Initialize app components
    initialize_app()
    
    # Use parsed arguments with fallback to environment variables
    port = args.port or int(os.environ.get('PORT', 5000))
    debug = args.debug or os.environ.get('FLASK_DEBUG', 'true').lower() in ('true', '1', 't')
    
    print(f"Starting server on port {port}, debug mode: {debug}")
    app.run(host='0.0.0.0', port=port, debug=debug) 