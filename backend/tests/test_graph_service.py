from app.services import graph


class FakeRecord:
    def __init__(self, values):
        self.values = values

    def __getitem__(self, key):
        return self.values[key]


class FakeSession:
    def __init__(self):
        self.node_query = None
        self.node_parameters = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def run(self, query, parameters):
        if "OPTIONAL MATCH (node)-[relationship]-()" in query:
            self.node_query = query
            self.node_parameters = parameters
            return [
                FakeRecord({"id": "P0009", "type": "PERSON", "label": "Highly Connected", "degree": 12}),
            ]
        return []


class FakeDriver:
    def __init__(self, session):
        self.fake_session = session

    def session(self, database):
        return self.fake_session


def test_graph_limit_selects_high_degree_node_before_id_order(monkeypatch):
    fake_session = FakeSession()
    monkeypatch.setattr(graph, "get_driver", lambda: FakeDriver(fake_session))
    monkeypatch.setattr(graph.settings, "neo4j_database", "neo4j")

    result = graph.get_graph(limit=1, node_type="PERSON")

    assert result["nodes"] == [{"id": "P0009", "type": "PERSON", "label": "Highly Connected"}]
    assert result["counts"] == {"nodes": 1, "edges": 0}
    assert fake_session.node_parameters == {"node_type": "PERSON", "limit": 1}
    assert "ORDER BY degree DESC, id" in fake_session.node_query
    assert fake_session.node_query.index("ORDER BY degree DESC, id") < fake_session.node_query.index("LIMIT $limit")
