"""
Data models for BioSearch application.

This module defines the standard data structures for all biological entities
returned by the BioSearch system, ensuring consistent formats across databases.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any, Union
from datetime import datetime
import json

@dataclass
class BaseModel:
    """Base class for all models with common functionality."""
    id: str
    name: str
    source_db: str
    title: str = ""
    url: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert model to dictionary representation."""
        return {k: v for k, v in self.__dict__.items() if v is not None}
    
    def to_json(self) -> str:
        """Convert model to JSON string."""
        return json.dumps(self.to_dict(), default=str)

@dataclass
class Gene(BaseModel):
    """Model representing a gene."""
    organism: str = "unknown"  # Default value to fix order issues
    symbol: Optional[str] = None
    aliases: List[str] = field(default_factory=list)
    description: Optional[str] = None
    location: Optional[str] = None
    proteins: List[str] = field(default_factory=list)
    pathways: List[str] = field(default_factory=list)
    variants: List[str] = field(default_factory=list)
    expression_data: Dict[str, Any] = field(default_factory=dict)
    gene_ontology: List[Dict[str, str]] = field(default_factory=list)
    references: List[Dict[str, str]] = field(default_factory=list)

@dataclass
class Protein(BaseModel):
    """Model representing a protein."""
    organism: str = "unknown"  # Default value to fix order issues
    sequence: Optional[str] = None
    gene: Optional[str] = None
    function: Optional[str] = None
    structure_ids: List[str] = field(default_factory=list)
    domains: List[Dict[str, Any]] = field(default_factory=list)
    interactions: List[str] = field(default_factory=list)
    pathways: List[str] = field(default_factory=list)
    ec_number: Optional[str] = None
    reactions: List[Dict[str, Any]] = field(default_factory=list)
    molecular_weight: Optional[float] = None
    locations: List[str] = field(default_factory=list)
    isoforms: List[Dict[str, Any]] = field(default_factory=list)
    post_translational_modifications: List[Dict[str, Any]] = field(default_factory=list)
    
    def get_structure_urls(self) -> List[str]:
        """Get URLs for all associated protein structures."""
        urls = []
        for struct_id in self.structure_ids:
            urls.append(f"https://www.rcsb.org/structure/{struct_id}")
        return urls

@dataclass
class Structure(BaseModel):
    """Model representing a protein structure."""
    method: str = "unknown"  # Default value to fix order issues
    resolution: Optional[float] = None
    deposition_date: Optional[datetime] = None
    chains: List[Dict[str, Any]] = field(default_factory=list)
    ligands: List[Dict[str, Any]] = field(default_factory=list)
    authors: List[str] = field(default_factory=list)
    citation: Optional[Dict[str, Any]] = None
    experimental_data: Dict[str, Any] = field(default_factory=dict)
    
    def get_download_url(self, file_format: str = "pdb") -> str:
        """Get download URL for the structure file."""
        return f"https://files.rcsb.org/download/{self.id}.{file_format}"

@dataclass
class Pathway(BaseModel):
    """Model representing a biological pathway."""
    organism: str = "unknown"  # Default value to fix order issues
    description: Optional[str] = None
    category: Optional[str] = None
    genes: List[str] = field(default_factory=list)
    proteins: List[str] = field(default_factory=list)
    reactions: List[Dict[str, Any]] = field(default_factory=list)
    diseases: List[str] = field(default_factory=list)
    references: List[Dict[str, str]] = field(default_factory=list)
    diagram_url: Optional[str] = None
    
    def get_components_count(self) -> Dict[str, int]:
        """Get count of various pathway components."""
        return {
            "genes": len(self.genes),
            "proteins": len(self.proteins),
            "reactions": len(self.reactions)
        }

@dataclass
class Drug(BaseModel):
    """Model representing a drug/compound."""
    formula: Optional[str] = None
    synonyms: List[str] = field(default_factory=list)
    description: Optional[str] = None
    mechanism: Optional[str] = None
    targets: List[str] = field(default_factory=list)
    indications: List[str] = field(default_factory=list)
    smiles: Optional[str] = None
    inchi: Optional[str] = None
    categories: List[str] = field(default_factory=list)
    atc_codes: List[str] = field(default_factory=list)
    properties: Dict[str, Any] = field(default_factory=dict)
    interactions: List[Dict[str, Any]] = field(default_factory=list)
    
    def get_structure_url(self) -> str:
        """Get URL for visualizing the drug structure."""
        if self.smiles:
            return f"https://pubchem.ncbi.nlm.nih.gov/search/#query={self.smiles}"
        return f"https://pubchem.ncbi.nlm.nih.gov/search/#query={self.name}"

@dataclass
class Publication(BaseModel):
    """Model representing a scientific publication."""
    authors: List[str] = field(default_factory=list)
    journal: Optional[str] = None
    year: Optional[int] = None
    pubdate: Optional[str] = None
    abstract: Optional[str] = None
    keywords: List[str] = field(default_factory=list)
    doi: Optional[str] = None
    pmid: Optional[str] = None
    full_text_url: Optional[str] = None
    
    def get_citation(self) -> str:
        """Format publication as a citation string."""
        author_str = ", ".join(self.authors[:3])
        if len(self.authors) > 3:
            author_str += " et al."
        
        journal_info = f"{self.journal}, {self.year}" if self.journal and self.year else ""
        return f"{author_str}. {self.title}. {journal_info}. PMID: {self.pmid}" if self.pmid else f"{author_str}. {self.title}. {journal_info}"

@dataclass
class SearchResult:
    """Container for search results across multiple databases."""
    query: str
    timestamp: datetime = field(default_factory=datetime.now)
    genes: List[Gene] = field(default_factory=list)
    proteins: List[Protein] = field(default_factory=list)
    pathways: List[Pathway] = field(default_factory=list)
    drugs: List[Drug] = field(default_factory=list)
    publications: List[Publication] = field(default_factory=list)
    structures: List[Structure] = field(default_factory=list)
    other_results: Dict[str, List[Any]] = field(default_factory=dict)
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert search results to dictionary."""
        result = {
            "query": self.query,
            "timestamp": self.timestamp.isoformat(),
            "result_counts": {
                "genes": len(self.genes),
                "proteins": len(self.proteins),
                "pathways": len(self.pathways),
                "drugs": len(self.drugs),
                "publications": len(self.publications),
                "structures": len(self.structures)
            },
            "results": {
                "genes": [gene.to_dict() for gene in self.genes],
                "proteins": [protein.to_dict() for protein in self.proteins],
                "pathways": [pathway.to_dict() for pathway in self.pathways],
                "drugs": [drug.to_dict() for drug in self.drugs],
                "publications": [pub.to_dict() for pub in self.publications],
                "structures": [structure.to_dict() for structure in self.structures],
            }
        }
        
        if self.other_results:
            result["results"]["other"] = self.other_results
            
        if self.error:
            result["error"] = self.error
            
        return result

def create_from_dict(model_type, data):
    """
    Factory function to create model instances from dictionaries.
    
    Args:
        model_type (str): The type of model to create ('gene', 'protein', etc.)
        data (dict): Dictionary containing data for the model
        
    Returns:
        An instance of the appropriate model class
    """
    models = {
        'gene': Gene,
        'protein': Protein,
        'drug': Drug,
        'publication': Publication,
        'pathway': Pathway,
        'structure': Structure
    }
    
    if model_type not in models:
        raise ValueError(f"Unknown model type: {model_type}")
    
    # Extract required parameters
    id = data.pop('id', None)
    name = data.pop('name', None)
    source_db = data.pop('source_db', None)
    url = data.pop('url', None)
    
    if not id or not name or not source_db:
        raise ValueError("Missing required parameters for model creation")
    
    # Create and return the model instance
    return models[model_type](id=id, name=name, source_db=source_db, url=url, **data) 