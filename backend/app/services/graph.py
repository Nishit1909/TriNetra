from typing import Literal

from app.config import settings
from app.db.neo4j import get_driver

NodeType = Literal["PERSON", "VEHICLE", "LOCATION"]


def get_graph(limit: int | None = None, node_type: NodeType | None = None) -> dict:
    node_query = """
        MATCH (node)
        WHERE ($node_type IS NULL OR node.node_type = $node_type)
        OPTIONAL MATCH (node)-[relationship]-()
        RETURN coalesce(node.node_id, elementId(node)) AS id,
               node.node_type AS type,
               coalesce(
                   CASE WHEN node.node_type = 'PERSON' THEN node.name END,
                   node.name,
                   node.node_id,
                   elementId(node)
               ) AS label,
               count(relationship) AS degree
        ORDER BY degree DESC, id
    """
    parameters = {"node_type": node_type}
    if limit is not None:
        node_query += " LIMIT $limit"
        parameters["limit"] = limit

    with get_driver().session(database=settings.neo4j_database) as session:
        nodes = [
            {key: record[key] for key in ("id", "type", "label")}
            for record in session.run(node_query, parameters)
        ]
        node_ids = [node["id"] for node in nodes]

        if not node_ids:
            edges = []
        else:
            edge_records = session.run(
                """
                MATCH (source)-[relationship]->(target)
                WHERE coalesce(source.node_id, elementId(source)) IN $node_ids
                  AND coalesce(target.node_id, elementId(target)) IN $node_ids
                RETURN coalesce(source.node_id, elementId(source)) AS source,
                       coalesce(target.node_id, elementId(target)) AS target,
                       type(relationship) AS type
                """,
                {"node_ids": node_ids},
            )
            edges = [record.data() for record in edge_records]

    return {
        "nodes": nodes,
        "edges": edges,
        "counts": {"nodes": len(nodes), "edges": len(edges)},
    }