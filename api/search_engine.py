"""
Unified Search Engine for BioSearch Application

This module contains the search engine for querying multiple biological databases and
organizing the results in a structured format.
"""
import asyncio
import aiohttp
import os
import logging
from typing import List, Dict, Any
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Import database-specific modules
from .db_helpers import (
    search_ncbi, 
    search_uniprot, 
    search_drugbank,
    format_ncbi_gene_results,
    format_pubmed_results,
    format_uniprot_results,
    format_drugbank_results,
    ssl_context,
    MOCK_MODE,
    NCBI_API_KEY
)

from .cache import cache, cached
from .models import SearchResult, Gene, Protein, Pathway, Drug, Publication, Structure

# Check for optional dependencies
try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

try:
    import networkx as nx
    NETWORKX_AVAILABLE = True
except ImportError:
    NETWORKX_AVAILABLE = False

ALL_MODULES_AVAILABLE = REDIS_AVAILABLE and NETWORKX_AVAILABLE

async def search_pubmed(session, query, retmax=10):
    """Search PubMed database using NCBI E-utilities."""
    if MOCK_MODE:
        logger.info(f"Using mock mode for PubMed search in search_engine: {query}")
    elif NCBI_API_KEY:
        logger.info(f"Using NCBI API key for PubMed search in search_engine")
    
    return await search_ncbi(session, 'pubmed', query, retmax)

async def search_engine(session, db_type, query, limit=10):
    """
    Unified search engine for querying different database types
    
    Args:
        session (aiohttp.ClientSession): Session for HTTP requests
        db_type (str): Type of database to search ('gene', 'protein', etc.)
        query (str): Search term
        limit (int): Maximum number of results to return
        
    Returns:
        dict: Search results from the specified database type
    """
    if MOCK_MODE:
        logger.info(f"Using mock mode for search engine: {db_type} - {query}")
    
    try:
        if db_type == 'gene':
            results = await search_ncbi(session, 'gene', query, limit)
            return await format_ncbi_gene_results(results)
        
        elif db_type == 'protein':
            results = await search_uniprot(session, query, limit)
            return await format_uniprot_results(results)
        
        elif db_type == 'pathway':
            # Currently we don't have a pathway database search
            return []
        
        elif db_type == 'structure':
            # Add a basic implementation for protein structure search in PDB
            # Use NCBI search with the 'structure' database as fallback
            try:
                # First try with NCBI's structure database
                results = await search_ncbi(session, 'structure', query, limit)
                pdb_results = []
                
                # Process results - extract relevant structure IDs
                if 'id_list' in results and results['id_list']:
                    for pdb_id in results['id_list'][:limit]:
                        pdb_results.append({
                            'id': pdb_id,
                            'name': f"PDB Structure {pdb_id}",
                            'description': f"Protein structure from PDB",
                            'url': f"https://www.rcsb.org/structure/{pdb_id}",
                            'type': 'structure',
                            'source_db': 'PDB'
                        })
                return pdb_results
            except Exception as e:
                logger.error(f"Error in PDB structure search: {str(e)}")
                # Return empty list on error rather than failing
                return []
        
        elif db_type == 'drug':
            results = await search_drugbank(session, query, limit)
            return await format_drugbank_results(results)
        
        elif db_type == 'publication':
            results = await search_pubmed(session, query, limit)
            return await format_pubmed_results(results)
        
        else:
            logger.error(f"Unsupported database type: {db_type}")
            return {'error': f"Unsupported database type: {db_type}"}
    
    except Exception as e:
        logger.error(f"Error in {db_type} search: {str(e)}")
        return {'error': str(e)}

async def unified_search(query, databases=None, filters=None, limit=10):
    """
    Perform a unified search across multiple biological databases
    
    Args:
        query (str): Search term
        databases (List[str]): List of database IDs to search
        filters (Dict): Additional filters for the search
        limit (int): Maximum number of results to return per database
        
    Returns:
        dict: Organized search results
    """
    if not query:
        return {'error': 'No query provided', 'results': {}}
    
    # Use all available databases if none specified
    if not databases:
        databases = ['ncbi', 'pubmed', 'uniprot', 'drugbank']
    
    # Init filters if not provided
    if not filters:
        filters = {}
    
    # Map database IDs to their types
    db_types = {
        'ncbi': 'gene',
        'pubmed': 'publication',
        'uniprot': 'protein',
        'drugbank': 'drug',
        'kegg': 'pathway',
        'pdb': 'structure'
    }
    
    if MOCK_MODE:
        logger.info(f"Using mock mode for unified search: {query} - {databases}")
    elif NCBI_API_KEY:
        logger.info(f"Using NCBI API key for unified search")
    
    # Create a session for all requests
    async with aiohttp.ClientSession() as session:
        # Initialize the results structure
        results = {
            'query': query,
            'filters': filters,
            'counts': {
                'total': 0,
                'genes': 0,
                'proteins': 0,
                'pathways': 0,
                'drugs': 0,
                'publications': 0,
                'structures': 0
            },
            'results': {
                'genes': [],
                'proteins': [],
                'pathways': [],
                'drugs': [],
                'publications': [],
                'structures': [],
                'other': {}
            }
        }
        
        # Create tasks for each database
        tasks = []
        for db_id in databases:
            if db_id in db_types:
                db_type = db_types[db_id]
                task = asyncio.create_task(search_engine(session, db_type, query, limit))
                tasks.append((db_id, db_type, task))
        
        # Wait for all tasks to complete and process results
        for db_id, db_type, task in tasks:
            try:
                db_results = await task
                
                # Handle error responses
                if isinstance(db_results, dict) and 'error' in db_results:
                    logger.error(f"Error in {db_id} search: {db_results['error']}")
                    continue
                
                # Skip empty results
                if not db_results:
                    continue
                
                # Add source database to each result if not already set
                for item in db_results:
                    # For certain databases, always enforce the correct source_db
                    if db_type == 'protein':
                        item['source_db'] = 'UniProt'  # Force UniProt for proteins
                    elif db_type == 'publication':
                        item['source_db'] = 'PubMed'  # Force PubMed for publications
                    elif db_type == 'drug':
                        item['source_db'] = 'DrugBank'  # Force DrugBank for drugs
                    elif db_type == 'gene':
                        item['source_db'] = 'NCBI'  # Force NCBI for genes
                    elif db_type == 'pathway':
                        item['source_db'] = 'KEGG'  # Force KEGG for pathways
                    elif db_type == 'structure':
                        item['source_db'] = 'PDB'  # Force PDB for structures
                    elif 'source_db' not in item:
                        item['source_db'] = db_id.upper()  # Default fallback
                
                # Add to the appropriate result category
                if db_type == 'gene':
                    results['results']['genes'].extend(db_results)
                    results['counts']['genes'] += len(db_results)
                
                elif db_type == 'protein':
                    results['results']['proteins'].extend(db_results)
                    results['counts']['proteins'] += len(db_results)
                
                elif db_type == 'pathway':
                    results['results']['pathways'].extend(db_results)
                    results['counts']['pathways'] += len(db_results)
                
                elif db_type == 'drug':
                    results['results']['drugs'].extend(db_results)
                    results['counts']['drugs'] += len(db_results)
                
                elif db_type == 'publication':
                    results['results']['publications'].extend(db_results)
                    results['counts']['publications'] += len(db_results)
                
                elif db_type == 'structure':
                    results['results']['structures'].extend(db_results)
                    results['counts']['structures'] += len(db_results)
                
                else:
                    # For any other database type not in our standard categories
                    if db_id not in results['results']['other']:
                        results['results']['other'][db_id] = []
                    
                    results['results']['other'][db_id].extend(db_results)
                
                # Update total count
                results['counts']['total'] += len(db_results)
            
            except Exception as e:
                logger.error(f"Error processing {db_id} results: {str(e)}")
        
        return results 