#!/usr/bin/env python3
"""ETL execution engine with batching, retry logic, and metrics.

This module provides optimized execution capabilities for ETL operations including:
- Chunked batch processing for large datasets
- Retry mechanisms with exponential backoff
- Performance metrics and timing logs
- Idempotent operations for reliable reruns
"""

from __future__ import annotations

import time
import logging
from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass, field
from pathlib import Path
import json

from .neo4j_client import neo4j_session
from .etl_config import ETLConfig


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class ExecutionMetrics:
    """Metrics for tracking ETL execution performance."""

    operation_name: str
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    total_items: int = 0
    processed_items: int = 0
    failed_items: int = 0
    retry_attempts: int = 0
    batch_count: int = 0
    average_batch_time: float = 0.0
    errors: List[str] = field(default_factory=list)

    @property
    def duration_seconds(self) -> float:
        """Calculate total execution duration."""
        end = self.end_time or time.time()
        return end - self.start_time

    @property
    def success_rate(self) -> float:
        """Calculate success rate percentage."""
        if self.total_items == 0:
            return 0.0
        return (self.processed_items / self.total_items) * 100

    @property
    def throughput_per_second(self) -> float:
        """Calculate items processed per second."""
        duration = self.duration_seconds
        if duration == 0:
            return 0.0
        return self.processed_items / duration

    def finish(self) -> None:
        """Mark execution as finished."""
        self.end_time = time.time()

    def add_error(self, error: str) -> None:
        """Add error to the metrics."""
        self.errors.append(error)
        self.failed_items += 1

    def to_dict(self) -> Dict[str, Any]:
        """Convert metrics to dictionary for logging."""
        return {
            "operation_name": self.operation_name,
            "duration_seconds": round(self.duration_seconds, 2),
            "total_items": self.total_items,
            "processed_items": self.processed_items,
            "failed_items": self.failed_items,
            "success_rate": round(self.success_rate, 2),
            "throughput_per_second": round(self.throughput_per_second, 2),
            "retry_attempts": self.retry_attempts,
            "batch_count": self.batch_count,
            "average_batch_time": round(self.average_batch_time, 3),
            "error_count": len(self.errors),
        }


@dataclass
class BatchConfig:
    """Configuration for batch processing."""

    batch_size: int = 100
    max_retries: int = 3
    retry_delay: float = 1.0  # Initial delay in seconds
    retry_backoff: float = 2.0  # Exponential backoff multiplier
    max_retry_delay: float = 30.0  # Maximum retry delay
    timeout_seconds: float = 300.0  # 5 minutes default timeout


class ETLExecutor:
    """High-performance ETL executor with batching and retry capabilities."""

    def __init__(self, config: BatchConfig = None):
        """Initialize executor with configuration.

        Args:
            config: Batch processing configuration
        """
        self.config = config or BatchConfig()
        self.metrics_history: List[ExecutionMetrics] = []

    def execute_batch_operation(
        self,
        session,
        operation_name: str,
        data_items: List[Any],
        batch_processor: Callable[[Any, List[Any]], int],
        **kwargs,
    ) -> ExecutionMetrics:
        """Execute a batch operation with retry logic and metrics.

        Args:
            session: Neo4j session
            operation_name: Name of the operation for logging
            data_items: List of data items to process
            batch_processor: Function that processes a batch of items
            **kwargs: Additional arguments passed to batch_processor

        Returns:
            ExecutionMetrics object with execution results
        """
        metrics = ExecutionMetrics(operation_name=operation_name)
        metrics.total_items = len(data_items)

        logger.info(f"🚀 Starting {operation_name} with {len(data_items)} items")

        try:
            # Process data in batches
            batch_times = []

            for i in range(0, len(data_items), self.config.batch_size):
                batch = data_items[i : i + self.config.batch_size]
                batch_start = time.time()

                # Execute batch with retry logic
                batch_result = self._execute_batch_with_retry(
                    session, batch, batch_processor, metrics, **kwargs
                )

                batch_time = time.time() - batch_start
                batch_times.append(batch_time)
                metrics.batch_count += 1
                metrics.processed_items += batch_result

                # Progress logging
                progress = (i + len(batch)) / len(data_items) * 100
                logger.info(
                    f"  📊 {operation_name}: {progress:.1f}% "
                    f"({metrics.processed_items}/{metrics.total_items}) "
                    f"- Batch time: {batch_time:.2f}s"
                )

            # Calculate average batch time
            if batch_times:
                metrics.average_batch_time = sum(batch_times) / len(batch_times)

        except Exception as e:
            logger.error(f"❌ {operation_name} failed: {e}")
            metrics.add_error(str(e))
        finally:
            metrics.finish()
            self.metrics_history.append(metrics)

        # Log final results
        self._log_execution_results(metrics)
        return metrics

    def _execute_batch_with_retry(
        self,
        session,
        batch: List[Any],
        batch_processor: Callable,
        metrics: ExecutionMetrics,
        **kwargs,
    ) -> int:
        """Execute a single batch with retry logic.

        Args:
            session: Neo4j session
            batch: Batch of data items
            batch_processor: Function to process the batch
            metrics: Metrics object to update
            **kwargs: Additional arguments

        Returns:
            Number of successfully processed items
        """
        last_exception = None
        delay = self.config.retry_delay

        for attempt in range(self.config.max_retries + 1):
            try:
                # Execute the batch processor
                result = batch_processor(session, batch, **kwargs)

                if attempt > 0:
                    logger.info(f"  ✅ Batch succeeded on attempt {attempt + 1}")

                return result if isinstance(result, int) else len(batch)

            except Exception as e:
                last_exception = e
                metrics.retry_attempts += 1

                if attempt < self.config.max_retries:
                    logger.warning(
                        f"  ⚠️  Batch failed (attempt {attempt + 1}): {e}. "
                        f"Retrying in {delay:.1f}s..."
                    )
                    time.sleep(delay)
                    delay = min(
                        delay * self.config.retry_backoff, self.config.max_retry_delay
                    )
                else:
                    logger.error(f"  ❌ Batch failed after {attempt + 1} attempts: {e}")

        # All retries failed
        metrics.add_error(
            f"Batch failed after {self.config.max_retries + 1} attempts: {last_exception}"
        )
        return 0

    def _log_execution_results(self, metrics: ExecutionMetrics) -> None:
        """Log detailed execution results.

        Args:
            metrics: Execution metrics to log
        """
        logger.info(f"\n📊 {metrics.operation_name} Execution Results:")
        logger.info(f"  ⏱️  Duration: {metrics.duration_seconds:.2f} seconds")
        logger.info(
            f"  📈 Throughput: {metrics.throughput_per_second:.1f} items/second"
        )
        logger.info(f"  ✅ Success rate: {metrics.success_rate:.1f}%")
        logger.info(f"  📦 Batches processed: {metrics.batch_count}")
        logger.info(f"  ⚡ Average batch time: {metrics.average_batch_time:.3f}s")
        logger.info(f"  🔄 Retry attempts: {metrics.retry_attempts}")

        if metrics.errors:
            logger.warning(f"  ⚠️  Errors encountered: {len(metrics.errors)}")
            for i, error in enumerate(metrics.errors[:3], 1):  # Show first 3 errors
                logger.warning(f"    {i}. {error}")
            if len(metrics.errors) > 3:
                logger.warning(f"    ... and {len(metrics.errors) - 3} more errors")

    def get_performance_summary(self) -> Dict[str, Any]:
        """Get overall performance summary across all operations.

        Returns:
            Dictionary with performance statistics
        """
        if not self.metrics_history:
            return {"message": "No operations executed yet"}

        total_items = sum(m.total_items for m in self.metrics_history)
        total_processed = sum(m.processed_items for m in self.metrics_history)
        total_duration = sum(m.duration_seconds for m in self.metrics_history)
        total_retries = sum(m.retry_attempts for m in self.metrics_history)

        return {
            "operations_count": len(self.metrics_history),
            "total_items": total_items,
            "total_processed": total_processed,
            "overall_success_rate": (
                (total_processed / total_items * 100) if total_items > 0 else 0
            ),
            "total_duration_seconds": round(total_duration, 2),
            "average_throughput": (
                round(total_processed / total_duration, 2) if total_duration > 0 else 0
            ),
            "total_retries": total_retries,
            "operations": [m.to_dict() for m in self.metrics_history],
        }

    def save_metrics(self, output_path: Path) -> None:
        """Save execution metrics to JSON file.

        Args:
            output_path: Path to save metrics file
        """
        summary = self.get_performance_summary()

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

        logger.info(f"📄 Metrics saved to: {output_path}")


# Utility functions for common batch operations


def batch_upsert_nodes(
    session,
    batch: List[Dict[str, Any]],
    node_label: str,
    id_property: str = "id",
    properties: List[str] = None,
) -> int:
    """Generic batch upsert operation for nodes.

    Args:
        session: Neo4j session
        batch: Batch of node data
        node_label: Neo4j node label
        id_property: Property name for node ID
        properties: List of properties to set

    Returns:
        Number of nodes processed
    """
    if not batch:
        return 0

    # Build SET clause for properties
    if properties:
        set_clause = ", ".join([f"n.{prop} = item.{prop}" for prop in properties])
    else:
        # Use all properties from first item
        sample_item = batch[0]
        set_clause = ", ".join(
            [
                f"n.{prop} = item.{prop}"
                for prop in sample_item.keys()
                if prop != id_property
            ]
        )

    query = f"""
    UNWIND $batch AS item
    MERGE (n:{node_label} {{ {id_property}: item.{id_property} }})
    ON CREATE SET {set_clause}
    ON MATCH SET {set_clause}
    RETURN count(n) AS processed_count
    """

    result = session.run(query, {"batch": batch})
    return result.single()["processed_count"]


def batch_create_relationships(
    session,
    batch: List[Dict[str, Any]],
    from_label: str,
    to_label: str,
    relationship_type: str,
    from_id_property: str = "from_id",
    to_id_property: str = "to_id",
    rel_properties: List[str] = None,
) -> int:
    """Generic batch relationship creation.

    Args:
        session: Neo4j session
        batch: Batch of relationship data
        from_label: Source node label
        to_label: Target node label
        relationship_type: Relationship type
        from_id_property: Property name for source node ID
        to_id_property: Property name for target node ID
        rel_properties: List of relationship properties to set

    Returns:
        Number of relationships processed
    """
    if not batch:
        return 0

    # Build SET clause for relationship properties
    rel_set_clause = ""
    if rel_properties:
        rel_set_clause = "ON CREATE SET " + ", ".join(
            [f"r.{prop} = item.{prop}" for prop in rel_properties]
        )

    query = f"""
    UNWIND $batch AS item
    MATCH (from:{from_label} {{ id: item.{from_id_property} }})
    MATCH (to:{to_label} {{ id: item.{to_id_property} }})
    MERGE (from)-[r:{relationship_type}]->(to)
    {rel_set_clause}
    RETURN count(r) AS processed_count
    """

    result = session.run(query, {"batch": batch})
    return result.single()["processed_count"]


if __name__ == "__main__":
    # Example usage and testing
    from .etl_config import DEFAULT_CONFIG
    from .neo4j_client import load_config, create_driver

    print("🧪 Testing ETL Executor...")

    # Create test data
    test_data = [
        {"id": f"test_{i}", "name": f"Test Item {i}", "value": i} for i in range(1, 101)
    ]

    # Initialize executor
    config = BatchConfig(batch_size=20, max_retries=2)
    executor = ETLExecutor(config)

    # Test batch processor function
    def test_processor(session, batch: List[Dict[str, Any]]) -> int:
        """Test processor that simulates node creation."""
        # Simulate some processing time
        time.sleep(0.1)
        return len(batch)

    # Mock session for testing
    class MockSession:
        def run(self, query, params=None):
            return type(
                "Result",
                (),
                {"single": lambda: {"processed_count": len(params.get("batch", []))}},
            )()

    mock_session = MockSession()

    # Execute test operation
    metrics = executor.execute_batch_operation(
        session=mock_session,
        operation_name="Test Node Creation",
        data_items=test_data,
        batch_processor=test_processor,
    )

    # Display results
    print(f"\n✅ Test completed!")
    print(f"📊 Performance Summary:")
    summary = executor.get_performance_summary()
    for key, value in summary.items():
        if key != "operations":
            print(f"  {key}: {value}")

    # Save metrics
    metrics_path = Path("test_metrics.json")
    executor.save_metrics(metrics_path)
    print(f"📄 Metrics saved to: {metrics_path}")
