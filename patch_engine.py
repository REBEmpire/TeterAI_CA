import re

with open("src/ai_engine/engine.py", "r") as f:
    content = f.read()

new_models_to_try = """        models_to_try = [
            ("google", "vertex_ai/text-embedding-004"),
            ("google", "gemini/gemini-embedding-2-preview"),
            ("xai", "xai/v1/embeddings")
        ]"""

content = re.sub(
    r'        models_to_try = \[\n            \("google", "vertex_ai/text-embedding-004"\),\n            \("xai", "xai/v1/embeddings"\)\n        \]',
    new_models_to_try,
    content,
    flags=re.MULTILINE
)

with open("src/ai_engine/engine.py", "w") as f:
    f.write(content)
