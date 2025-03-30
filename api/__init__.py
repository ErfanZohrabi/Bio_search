"""
BioSearch API Package

This package contains modules for interacting with various biological database APIs.
"""

from .db_helpers import (
    search_ncbi,
    search_uniprot,
    search_drugbank,
    format_ncbi_gene_results,
    format_pubmed_results,
    format_uniprot_results,
    format_drugbank_results
)

# Define search_pubmed function as an alias for search_ncbi with 'pubmed' parameter
async def search_pubmed(session, query, retmax=10, ssl_context=None):
    """
    Search PubMed database - wrapper around search_ncbi
    
    Args:
        session (aiohttp.ClientSession): Session for making HTTP requests
        query (str): Search query
        retmax (int): Maximum number of results to return
        ssl_context: SSL context for HTTPS requests
        
    Returns:
        dict: Search results
    """
    return await search_ncbi(session, 'pubmed', query, retmax)

__all__ = [
    'search_ncbi',
    'search_pubmed',
    'search_uniprot',
    'search_drugbank',
    'format_ncbi_gene_results',
    'format_pubmed_results',
    'format_uniprot_results',
    'format_drugbank_results'
] 