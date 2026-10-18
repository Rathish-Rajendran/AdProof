import json

from scripts.export_schemas import render_files


def test_generated_schemas_and_examples_are_current():
    for path, expected in render_files().items():
        assert path.exists(), f"Missing generated artifact: {path.relative_to(path.parents[1])}"
        assert path.read_text(encoding="utf-8") == expected
        if path.parent.name == "examples":
            from adproof.domain import models

            model = getattr(models, path.stem)
            model.model_validate(json.loads(expected))
