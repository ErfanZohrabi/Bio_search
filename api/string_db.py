"""
STRING database integration module for BioSearch.
Provides functionality to query and visualize protein-protein interaction networks.
"""

import aiohttp
import logging
from typing import List, Dict, Optional
from urllib.parse import quote

logger = logging.getLogger(__name__)

# STRING API base URL
STRING_BASE_URL = "https://string-db.org/api"
STRING_NETWORK_URL = "https://string-db.org/cgi/network.pl"

# Common species codes
SPECIES_CODES = {
    "human": "9606",
    "mouse": "10090",
    "rat": "10116",
    "yeast": "4932",
    "e.coli": "83333",
    "auto-detect": "auto"
}

def get_network_url(
    identifiers,
    species="9606",
    score="0.4",
    network_type=""
):
    """Generate a URL for the STRING network viewer.
    
    Args:
        identifiers (str): Comma-separated list of protein identifiers
        species (str): Species ID (default: 9606 for human)
        score (str): Minimum required interaction score (default: "0.4")
        network_type (str): Type of network (e.g., "physical")
        
    Returns:
        str: URL for the STRING network viewer
    """
    # Process the identifiers - make sure they're properly formatted
    if isinstance(identifiers, list):
        # If it's a list, join with the proper delimiter
        identifiers_str = "%0d".join([id.strip() for id in identifiers if id.strip()])
    elif isinstance(identifiers, str):
        # If it's a comma-separated string, split and rejoin with the proper delimiter
        identifiers_str = "%0d".join([id.strip() for id in identifiers.split(',') if id.strip()])
    else:
        # Default fallback
        identifiers_str = str(identifiers)
    
    # Create the network URL
    base_url = "https://string-db.org/cgi/network.pl"
    network_params = {
        "identifiers": identifiers_str,
        "species": species,
        "required_score": score
    }
    
    if network_type:
        network_params["network_type"] = network_type
    
    # Build the query string
    query_parts = []
    for key, value in network_params.items():
        query_parts.append(f"{key}={value}")
    
    query_string = "&".join(query_parts)
    network_url = f"{base_url}?{query_string}"
    
    logger.info(f"Generated STRING network URL: {network_url}")
    return network_url

async def search_string(
    session: aiohttp.ClientSession,
    query: str,
    species: str = "human",
    limit: int = 10
) -> List[Dict]:
    """
    Search STRING database for proteins/genes.
    
    Args:
        session: aiohttp ClientSession
        query: Search query
        species: Species name or code
        limit: Maximum number of results
    
    Returns:
        List of matching proteins/genes
    """
    species_code = SPECIES_CODES.get(species.lower(), "9606")
    
    params = {
        "identifier": query,
        "species": species_code,
        "limit": str(limit),
        "format": "json"
    }
    
    url = f"{STRING_BASE_URL}/json/resolve"
    async with session.get(url, params=params) as response:
        if response.status == 200:
            return await response.json()
        else:
            logger.error(f"STRING API error: {response.status}")
            return []

async def get_interactions(
    session: aiohttp.ClientSession,
    identifiers: List[str],
    species: str = "human"
) -> Dict:
    """
    Get protein-protein interactions from STRING.
    
    Args:
        session: aiohttp ClientSession
        identifiers: List of protein/gene identifiers
        species: Species name or code
    
    Returns:
        Dictionary containing interaction data
    """
    species_code = SPECIES_CODES.get(species.lower(), "9606")
    
    params = {
        "identifiers": "%0D".join(identifiers),
        "species": species_code,
        "format": "json"
    }
    
    url = f"{STRING_BASE_URL}/json/interactions"
    async with session.get(url, params=params) as response:
        if response.status == 200:
            return await response.json()
        else:
            logger.error(f"STRING API error: {response.status}")
            return {} 