"""
KEGG API Module for BioSearch Application

This module provides functions for interacting with the KEGG API.
"""

import logging
import aiohttp
import asyncio
import re
import ssl
from typing import Dict, List, Any, Optional, Tuple
from .db_config import KEGG_CONFIG
from .cache import cached
from .models import Pathway

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Import SSL context
from .db_helpers import ssl_context

@cached(ttl=3600, key_prefix="kegg")
async def search_kegg_pathway(session: aiohttp.ClientSession, query: str, organism: str = "hsa", limit: int = 10) -> Dict[str, Any]:
    """
    Search for pathways in KEGG database.
    
    Args:
        session: aiohttp client session
        query: Search term
        organism: KEGG organism code (default: hsa for human)
        limit: Maximum number of results to return
        
    Returns:
        Dictionary with search results
    """
    try:
        # Format the search URL for KEGG
        search_url = f"{KEGG_CONFIG.base_url}{KEGG_CONFIG.search_endpoint}/pathway/{organism}"
        
        async with session.get(f"{search_url}/{query}", ssl=ssl_context) as response:
            if response.status != 200:
                logger.error(f"KEGG search error: {response.status} for query '{query}'")
                return {"error": f"KEGG API error: {response.status}"}
            
            text_data = await response.text()
            
            # Parse the text response (KEGG returns plain text)
            pathway_ids = []
            pathway_names = {}
            
            for line in text_data.strip().split("\n"):
                if not line:
                    continue
                
                # Extract pathway ID and name
                match = re.match(r'path:(.+)\t(.+)', line)
                if match:
                    pathway_id = match.group(1)
                    pathway_name = match.group(2)
                    pathway_ids.append(pathway_id)
                    pathway_names[pathway_id] = pathway_name
            
            # Limit results
            pathway_ids = pathway_ids[:limit]
            
            # Get pathway details in parallel
            detail_tasks = [get_kegg_pathway_info(session, pathway_id) for pathway_id in pathway_ids]
            pathway_details = await asyncio.gather(*detail_tasks)
            
            # Format results
            results = []
            for pathway_id, details in zip(pathway_ids, pathway_details):
                if details and not isinstance(details, dict):
                    pathway = {
                        "id": pathway_id,
                        "name": pathway_names.get(pathway_id, "Unknown"),
                        "description": details.get("description", ""),
                        "genes": details.get("genes", []),
                        "url": f"https://www.kegg.jp/kegg-bin/show_pathway?{pathway_id}"
                    }
                    results.append(pathway)
            
            return {"results": results}
    
    except Exception as e:
        logger.error(f"Error in search_kegg_pathway: {str(e)}")
        return {"error": str(e)}

@cached(ttl=86400, key_prefix="kegg_pathway")  # Cache for 24 hours
async def get_kegg_pathway_info(session: aiohttp.ClientSession, pathway_id: str) -> Dict[str, Any]:
    """
    Get detailed information about a KEGG pathway.
    
    Args:
        session: aiohttp client session
        pathway_id: KEGG pathway ID
        
    Returns:
        Dictionary with pathway details
    """
    try:
        # Format the fetch URL for KEGG
        fetch_url = f"{KEGG_CONFIG.base_url}{KEGG_CONFIG.fetch_endpoint}/{pathway_id}"
        
        async with session.get(fetch_url, ssl=ssl_context) as response:
            if response.status != 200:
                logger.error(f"KEGG fetch error: {response.status} for pathway '{pathway_id}'")
                return {"error": f"KEGG API error: {response.status}"}
            
            text_data = await response.text()
            
            # Parse the text response (KEGG returns plain text)
            description = ""
            genes = []
            modules = []
            diseases = []
            references = []
            current_section = None
            
            for line in text_data.strip().split("\n"):
                if not line.strip():
                    continue
                
                # Check for section headers
                if line.startswith("DESCRIPTION"):
                    current_section = "DESCRIPTION"
                    description = line.replace("DESCRIPTION", "").strip()
                elif line.startswith("GENE"):
                    current_section = "GENE"
                    gene_match = re.search(r'GENE\s+(\S+)\s+(.+)', line)
                    if gene_match:
                        gene_id = gene_match.group(1)
                        gene_name = gene_match.group(2)
                        genes.append({"id": gene_id, "name": gene_name})
                elif line.startswith("MODULE"):
                    current_section = "MODULE"
                    module_match = re.search(r'MODULE\s+(\S+)\s+(.+)', line)
                    if module_match:
                        module_id = module_match.group(1)
                        module_name = module_match.group(2)
                        modules.append({"id": module_id, "name": module_name})
                elif line.startswith("DISEASE"):
                    current_section = "DISEASE"
                    disease_match = re.search(r'DISEASE\s+(\S+)\s+(.+)', line)
                    if disease_match:
                        disease_id = disease_match.group(1)
                        disease_name = disease_match.group(2)
                        diseases.append({"id": disease_id, "name": disease_name})
                elif line.startswith("REFERENCE"):
                    current_section = "REFERENCE"
                    references.append({"text": line.replace("REFERENCE", "").strip()})
                elif current_section == "DESCRIPTION" and line.startswith(" "):
                    description += " " + line.strip()
                elif current_section == "GENE" and line.startswith(" "):
                    gene_match = re.search(r'\s+(\S+)\s+(.+)', line)
                    if gene_match:
                        gene_id = gene_match.group(1)
                        gene_name = gene_match.group(2)
                        genes.append({"id": gene_id, "name": gene_name})
                elif current_section == "MODULE" and line.startswith(" "):
                    module_match = re.search(r'\s+(\S+)\s+(.+)', line)
                    if module_match:
                        module_id = module_match.group(1)
                        module_name = module_match.group(2)
                        modules.append({"id": module_id, "name": module_name})
                elif current_section == "DISEASE" and line.startswith(" "):
                    disease_match = re.search(r'\s+(\S+)\s+(.+)', line)
                    if disease_match:
                        disease_id = disease_match.group(1)
                        disease_name = disease_match.group(2)
                        diseases.append({"id": disease_id, "name": disease_name})
                elif current_section == "REFERENCE" and line.startswith(" "):
                    if references:
                        references[-1]["text"] += " " + line.strip()
            
            return {
                "description": description,
                "genes": genes,
                "modules": modules,
                "diseases": diseases,
                "references": references,
                "diagram_url": f"https://www.kegg.jp/kegg-bin/show_pathway?{pathway_id}/default%3dwhite"
            }
    
    except Exception as e:
        logger.error(f"Error in get_kegg_pathway_info: {str(e)}")
        return {"error": str(e)}

async def format_kegg_results(data: Dict[str, Any]) -> List[Pathway]:
    """
    Format KEGG search results into Pathway models.
    
    Args:
        data: Raw KEGG API response
        
    Returns:
        List of Pathway objects
    """
    pathways = []
    
    if "error" in data:
        logger.error(f"Error in KEGG results: {data['error']}")
        return pathways
    
    results = data.get("results", [])
    
    for result in results:
        # Extract genes from the nested dictionary structure
        gene_ids = []
        for gene_item in result.get("genes", []):
            gene_ids.append(gene_item.get("id"))
        
        # Extract diseases from the nested dictionary structure
        diseases = []
        if "diseases" in result:
            for disease_item in result["diseases"]:
                diseases.append(disease_item.get("name", ""))
        
        # Create Pathway object
        pathway = Pathway(
            id=result.get("id", ""),
            name=result.get("name", "Unknown Pathway"),
            source_db="KEGG",
            url=result.get("url", f"https://www.kegg.jp/kegg-bin/show_pathway?{result.get('id')}"),
            organism="human",  # Can be parameterized later
            description=result.get("description", ""),
            category="",  # KEGG doesn't provide explicit categories in the basic API response
            genes=gene_ids,
            proteins=[],  # Would need additional processing to map genes to proteins
            reactions=[],  # Would need additional processing
            diseases=diseases,
            references=[],  # Would need additional processing from the references list
            diagram_url=result.get("diagram_url", "")
        )
        
        pathways.append(pathway)
    
    return pathways 