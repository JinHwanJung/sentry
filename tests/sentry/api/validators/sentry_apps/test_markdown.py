from __future__ import absolute_import

from sentry.testutils import TestCase

from .util import invalid_schema, validate_component


class TestMarkdownSchemaValidation(TestCase):
    def setUp(self):
        self.schema = {
            "type": "markdown",
            "text": """
# This Is a Title
- this
- is
- a
- list
            """,
        }

    def test_valid_schema(self):
        validate_component(self.schema)

    @invalid_schema
    def test_missing_text(self):
        del self.schema["text"]
        validate_component(self.schema)

    @invalid_schema
    def test_invalid_text_type(self):
        self.schema["text"] = 1
        validate_component(self.schema)
