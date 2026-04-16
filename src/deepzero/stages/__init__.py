from deepzero.engine.stage import register_processor
from deepzero.stages.command import GenericCommand
from deepzero.stages.filter import MetadataFilter
from deepzero.stages.hash_filter import HashExclude
from deepzero.stages.ingest import FileDiscovery
from deepzero.stages.llm import GenericLLM
from deepzero.stages.sort import Sort
from deepzero.stages.top_k import TopKSelector

register_processor("file_discovery", FileDiscovery)
register_processor("metadata_filter", MetadataFilter)
register_processor("hash_exclude", HashExclude)
register_processor("generic_llm", GenericLLM)
register_processor("generic_command", GenericCommand)
register_processor("top_k", TopKSelector)
register_processor("sort", Sort)
