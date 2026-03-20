with open("tests/test_engine_embeddings.py", "r") as f:
    content = f.read()

content = content.replace("mock_embedding.side_effect = [\n        Exception(\"Google API error\"),\n        mock_response\n    ]", "mock_embedding.side_effect = [\n        Exception(\"Google API error\"),\n        Exception(\"Google API error 2\"),\n        mock_response\n    ]")

with open("tests/test_engine_embeddings.py", "w") as f:
    f.write(content)
