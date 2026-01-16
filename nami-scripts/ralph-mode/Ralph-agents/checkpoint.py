#!/usr/bin/env python3
"""
Checkpoint System for Ralph Agents

Provides state persistence and resume functionality for agents.
"""
import json
import pickle
from pathlib import Path
from datetime import datetime
from typing import Any, Optional, Dict
from dataclasses import dataclass, asdict


@dataclass
class CheckpointMetadata:
    """Metadata about a checkpoint."""
    timestamp: str
    agent_name: str
    task: str
    iteration: int
    workspace_path: str
    files_created: int
    tokens_used: int


@dataclass
class Checkpoint:
    """Complete checkpoint data."""
    metadata: CheckpointMetadata
    state: Dict[str, Any]
    workspace_snapshot: Dict[str, str]  # file_path -> hash


class CheckpointManager:
    """
    Manages checkpoint creation, loading, and cleanup.
    
    Features:
    - Save agent state to disk
    - Resume from checkpoints
    - Automatic checkpoint rotation
    - Workspace snapshot tracking
    """
    
    def __init__(self, checkpoint_dir: str = "./checkpoints"):
        """
        Initialize checkpoint manager.
        
        Args:
            checkpoint_dir: Directory to store checkpoints
        """
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        
        # Maximum checkpoints to keep (rotate old ones)
        self.max_checkpoints = 10
    
    def create_checkpoint(
        self,
        agent_name: str,
        task: str,
        iteration: int,
        workspace_path: str,
        state: Dict[str, Any],
        tokens_used: int = 0
    ) -> str:
        """
        Create a checkpoint of the current state.
        
        Args:
            agent_name: Name of the agent
            task: Current task description
            iteration: Current iteration number
            workspace_path: Path to workspace directory
            state: Agent state to save
            tokens_used: Total tokens used so far
            
        Returns:
            Checkpoint ID (timestamp-based)
        """
        # Create checkpoint ID
        checkpoint_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Count files in workspace
        files_created = 0
        if workspace_path:
            workspace = Path(workspace_path)
            if workspace.exists():
                files_created = len(list(workspace.rglob("*")))
        
        # Create metadata
        metadata = CheckpointMetadata(
            timestamp=datetime.now().isoformat(),
            agent_name=agent_name,
            task=task,
            iteration=iteration,
            workspace_path=workspace_path,
            files_created=files_created,
            tokens_used=tokens_used
        )
        
        # Create workspace snapshot (file hashes)
        workspace_snapshot = self._create_workspace_snapshot(workspace_path)
        
        # Create checkpoint
        checkpoint = Checkpoint(
            metadata=metadata,
            state=state,
            workspace_snapshot=workspace_snapshot
        )
        
        # Save checkpoint
        checkpoint_path = self.checkpoint_dir / f"checkpoint_{checkpoint_id}.pkl"
        with open(checkpoint_path, 'wb') as f:
            pickle.dump(checkpoint, f)
        
        # Save metadata as JSON for easy reading
        metadata_path = self.checkpoint_dir / f"checkpoint_{checkpoint_id}_meta.json"
        with open(metadata_path, 'w') as f:
            json.dump(asdict(metadata), f, indent=2)
        
        # Rotate old checkpoints
        self._rotate_checkpoints()
        
        return checkpoint_id
    
    def load_checkpoint(self, checkpoint_id: str) -> Optional[Checkpoint]:
        """
        Load a checkpoint by ID.
        
        Args:
            checkpoint_id: Checkpoint ID to load
            
        Returns:
            Checkpoint object or None if not found
        """
        checkpoint_path = self.checkpoint_dir / f"checkpoint_{checkpoint_id}.pkl"
        
        if not checkpoint_path.exists():
            return None
        
        with open(checkpoint_path, 'rb') as f:
            return pickle.load(f)
    
    def list_checkpoints(self) -> Dict[str, CheckpointMetadata]:
        """
        List all available checkpoints.
        
        Returns:
            Dict mapping checkpoint IDs to metadata
        """
        checkpoints = {}
        
        for meta_file in self.checkpoint_dir.glob("checkpoint_*_meta.json"):
            checkpoint_id = meta_file.stem.replace("_meta", "")
            
            with open(meta_file, 'r') as f:
                metadata = CheckpointMetadata(**json.load(f))
            
            checkpoints[checkpoint_id] = metadata
        
        return sorted(checkpoints.items(), key=lambda x: x[1].timestamp, reverse=True)
    
    def get_latest_checkpoint(self) -> Optional[Checkpoint]:
        """
        Get the most recent checkpoint.
        
        Returns:
            Latest checkpoint or None if no checkpoints exist
        """
        checkpoints = self.list_checkpoints()
        if not checkpoints:
            return None
        
        latest_id, _ = checkpoints[0]
        return self.load_checkpoint(latest_id)
    
    def delete_checkpoint(self, checkpoint_id: str) -> bool:
        """
        Delete a checkpoint.
        
        Args:
            checkpoint_id: Checkpoint ID to delete
            
        Returns:
            True if deleted, False if not found
        """
        checkpoint_path = self.checkpoint_dir / f"checkpoint_{checkpoint_id}.pkl"
        metadata_path = self.checkpoint_dir / f"checkpoint_{checkpoint_id}_meta.json"
        
        deleted = False
        
        if checkpoint_path.exists():
            checkpoint_path.unlink()
            deleted = True
        
        if metadata_path.exists():
            metadata_path.unlink()
            deleted = True
        
        return deleted
    
    def clear_all_checkpoints(self):
        """Delete all checkpoints."""
        for file in self.checkpoint_dir.glob("checkpoint_*"):
            file.unlink()
    
    def _create_workspace_snapshot(self, workspace_path: str) -> Dict[str, str]:
        """
        Create a snapshot of the workspace (file hashes).
        
        Args:
            workspace_path: Path to workspace directory
            
        Returns:
            Dict mapping file paths to hashes
        """
        snapshot = {}
        
        if not workspace_path:
            return snapshot
        
        workspace = Path(workspace_path)
        if not workspace.exists():
            return snapshot
        
        # Hash files using simple checksum
        for file in workspace.rglob("*"):
            if file.is_file():
                try:
                    with open(file, 'rb') as f:
                        content = f.read()
                    # Simple hash based on size and first/last bytes
                    file_hash = f"{len(content)}_{content[:10].hex()}_{content[-10:].hex()}"
                    snapshot[str(file.relative_to(workspace))] = file_hash
                except Exception:
                    # Skip files that can't be read
                    pass
        
        return snapshot
    
    def _rotate_checkpoints(self):
        """Remove old checkpoints if we exceed the limit."""
        checkpoints = self.list_checkpoints()
        
        if len(checkpoints) > self.max_checkpoints:
            # Remove oldest checkpoints
            for checkpoint_id, _ in checkpoints[self.max_checkpoints:]:
                self.delete_checkpoint(checkpoint_id)
    
    def get_checkpoint_summary(self) -> str:
        """
        Get a summary of all checkpoints.
        
        Returns:
            Formatted summary string
        """
        checkpoints = self.list_checkpoints()
        
        if not checkpoints:
            return "No checkpoints available."
        
        lines = ["\nAvailable Checkpoints:"]
        lines.append("=" * 80)
        
        for checkpoint_id, metadata in checkpoints:
            lines.append(f"\nCheckpoint: {checkpoint_id}")
            lines.append(f"  Timestamp: {metadata.timestamp}")
            lines.append(f"  Agent: {metadata.agent_name}")
            lines.append(f"  Task: {metadata.task[:50]}...")
            lines.append(f"  Iteration: {metadata.iteration}")
            lines.append(f"  Files Created: {metadata.files_created}")
            lines.append(f"  Tokens Used: {metadata.tokens_used:,}")
        
        lines.append("\n" + "=" * 80)
        return "\n".join(lines)