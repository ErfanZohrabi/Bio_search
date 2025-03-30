"""
PDB API Module for BioSearch Application

This module provides functions for interacting with the Protein Data Bank (PDB) API.
"""

import logging
import aiohttp
import json
from typing import Dict, List, Any, Optional
from datetime import datetime
from .db_config import PDB_CONFIG
from .cache import cached
from .models import Structure

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Import SSL context
from .db_helpers import ssl_context

@cached(ttl=3600, key_prefix="pdb")
async def search_pdb(session: aiohttp.ClientSession, query: str, limit: int = 10) -> Dict[str, Any]:
    """
    Search for protein structures in PDB database.
    
    Args:
        session: aiohttp client session
        query: Search term (protein name, gene, PDB ID, etc.)
        limit: Maximum number of results to return
        
    Returns:
        Dictionary with search results
    """
    try:
        # Prepare the search query
        # PDB search requires a specific JSON format with query parameters
        search_query = {
            "query": {
                "type": "terminal",
                "service": "text",
                "parameters": {
                    "value": query
                }
            },
            "request_options": {
                "return_all_hits": True,
                "pager": {
                    "start": 0,
                    "rows": limit
                }
            },
            "return_type": "entry"
        }
        
        search_url = f"{PDB_CONFIG.base_url}/query"
        
        async with session.post(
            search_url,
            json=search_query,
            headers={"Content-Type": "application/json"},
            ssl=ssl_context
        ) as response:
            if response.status != 200:
                logger.error(f"PDB search error: {response.status} for query '{query}'")
                return {"error": f"PDB API error: {response.status}"}
            
            data = await response.json()
            
            # Extract result IDs
            result_ids = []
            if "result_set" in data:
                for result in data["result_set"]:
                    if "identifier" in result:
                        result_ids.append(result["identifier"])
            
            # Get details for each structure
            structure_details = []
            for pdb_id in result_ids:
                details = await get_pdb_structure_details(session, pdb_id)
                if details and not isinstance(details, dict) and "error" not in details:
                    structure_details.append(details)
            
            return {"results": structure_details}
    
    except Exception as e:
        logger.error(f"Error in search_pdb: {str(e)}")
        return {"error": str(e)}

@cached(ttl=86400, key_prefix="pdb_structure")  # Cache for 24 hours
async def get_pdb_structure_details(session: aiohttp.ClientSession, pdb_id: str) -> Dict[str, Any]:
    """
    Get detailed information about a PDB structure.
    
    Args:
        session: aiohttp client session
        pdb_id: PDB structure ID
        
    Returns:
        Dictionary with structure details
    """
    try:
        # Format the URL for PDB entry details
        entry_url = f"{PDB_CONFIG.base_url}/entry/{pdb_id}"
        
        async with session.get(entry_url, ssl=ssl_context) as response:
            if response.status != 200:
                logger.error(f"PDB entry error: {response.status} for structure '{pdb_id}'")
                return {"error": f"PDB API error: {response.status}"}
            
            data = await response.json()
            
            # Extract basic information
            structure = {
                "id": pdb_id,
                "title": "",
                "description": "",
                "resolution": None,
                "experimental_method": "",
                "deposition_date": None,
                "release_date": None,
                "authors": [],
                "citation": {},
                "sequence_length": None,
                "ligands": [],
                "related_proteins": [],
                "url": f"https://www.rcsb.org/structure/{pdb_id}"
            }
            
            if "struct" in data:
                struct_data = data["struct"]
                structure["title"] = struct_data.get("title", "")
                if "pdbx_descriptor" in struct_data:
                    structure["description"] = struct_data["pdbx_descriptor"]
            
            if "rcsb_entry_info" in data:
                entry_info = data["rcsb_entry_info"]
                structure["resolution"] = entry_info.get("resolution_combined", None)
                structure["experimental_method"] = entry_info.get("experimental_method", "")
                structure["sequence_length"] = entry_info.get("polymer_entity_count_protein", None)
            
            if "rcsb_accession_info" in data:
                accession_info = data["rcsb_accession_info"]
                if "deposit_date" in accession_info:
                    structure["deposition_date"] = accession_info["deposit_date"]
                if "initial_release_date" in accession_info:
                    structure["release_date"] = accession_info["initial_release_date"]
            
            if "rcsb_primary_citation" in data:
                citation = data["rcsb_primary_citation"]
                structure["citation"] = {
                    "title": citation.get("title", ""),
                    "journal": citation.get("journal_abbrev", ""),
                    "year": citation.get("year", None),
                    "doi": citation.get("pdbx_database_id_doi", "")
                }
                if "rcsb_authors" in citation:
                    structure["authors"] = citation["rcsb_authors"]
            
            # Additional information
            related_proteins_url = f"{PDB_CONFIG.base_url}/entry/{pdb_id}/polymer_entities"
            ligands_url = f"{PDB_CONFIG.base_url}/entry/{pdb_id}/ligands"
            
            # Get related protein information
            async with session.get(related_proteins_url, ssl=ssl_context) as proteins_response:
                if proteins_response.status == 200:
                    proteins_data = await proteins_response.json()
                    for entity in proteins_data:
                        if "entity_poly" in entity and "pdbx_strand_id" in entity["entity_poly"]:
                            chains = entity["entity_poly"]["pdbx_strand_id"].split(",")
                            protein_info = {
                                "entity_id": entity.get("entity_id", ""),
                                "chains": chains,
                                "name": entity.get("rcsb_polymer_entity", {}).get("pdbx_description", "Unknown")
                            }
                            structure["related_proteins"].append(protein_info)
            
            # Get ligand information
            async with session.get(ligands_url, ssl=ssl_context) as ligands_response:
                if ligands_response.status == 200:
                    ligands_data = await ligands_response.json()
                    for ligand in ligands_data:
                        ligand_info = {
                            "id": ligand.get("chem_comp", {}).get("id", ""),
                            "name": ligand.get("chem_comp", {}).get("name", "Unknown"),
                            "formula": ligand.get("chem_comp", {}).get("formula", "")
                        }
                        structure["ligands"].append(ligand_info)
            
            return structure
    
    except Exception as e:
        logger.error(f"Error in get_pdb_structure_details: {str(e)}")
        return {"error": str(e)}

async def format_pdb_results(data: Dict[str, Any]) -> List[Structure]:
    """
    Format PDB search results into Structure models.
    
    Args:
        data: Raw PDB API response
        
    Returns:
        List of Structure objects
    """
    structures = []
    
    if "error" in data:
        logger.error(f"Error in PDB results: {data['error']}")
        return structures
    
    results = data.get("results", [])
    
    for result in results:
        # Parse dates if available
        deposition_date = None
        if result.get("deposition_date"):
            try:
                deposition_date = datetime.strptime(result["deposition_date"], "%Y-%m-%d")
            except ValueError:
                logger.warning(f"Could not parse deposition date: {result['deposition_date']}")
        
        # Extract chains
        chains = []
        for protein in result.get("related_proteins", []):
            chains.append({
                "entity_id": protein.get("entity_id", ""),
                "id": ",".join(protein.get("chains", [])),
                "name": protein.get("name", "")
            })
        
        # Extract ligands
        ligands = []
        for ligand in result.get("ligands", []):
            ligands.append({
                "id": ligand.get("id", ""),
                "name": ligand.get("name", ""),
                "formula": ligand.get("formula", "")
            })
        
        # Extract authors
        authors = result.get("authors", [])
        
        # Create Structure object
        structure = Structure(
            id=result.get("id", ""),
            name=result.get("title", "Unknown Structure"),
            source_db="PDB",
            url=result.get("url", f"https://www.rcsb.org/structure/{result.get('id')}"),
            method=result.get("experimental_method", ""),
            resolution=result.get("resolution"),
            deposition_date=deposition_date,
            chains=chains,
            ligands=ligands,
            authors=authors,
            citation=result.get("citation", {}),
            experimental_data={}  # Would need additional processing to extract experimental data
        )
        
        structures.append(structure)
    
    return structures 