import unittest

from tags_machine_core.json_tools import sanitize_json_for_display


class JsonToolsTest(unittest.TestCase):
    def test_sanitize_json_for_display_truncates_image_like_fields_by_default(self):
        image_text = "x" * 100
        prompt_text = "akemi homura, foot focus"
        data = {
            "request_body": {
                "parameters": {
                    "reference_image_multiple": [image_text],
                    "director_reference_images": [image_text],
                    "image": image_text,
                    "mask": image_text,
                    "prompt": prompt_text,
                }
            }
        }

        sanitized = sanitize_json_for_display(
            data,
            max_image_string_length=12,
            max_string_length=200,
        )
        parameters = sanitized["request_body"]["parameters"]

        self.assertEqual(parameters["prompt"], prompt_text)
        self.assertEqual(
            parameters["reference_image_multiple"][0],
            "xxxxxxxxxxxx...(truncated, chars=100)",
        )
        self.assertEqual(
            parameters["director_reference_images"][0],
            "xxxxxxxxxxxx...(truncated, chars=100)",
        )
        self.assertEqual(parameters["image"], "xxxxxxxxxxxx...(truncated, chars=100)")
        self.assertEqual(parameters["mask"], "xxxxxxxxxxxx...(truncated, chars=100)")

    def test_sanitize_json_for_display_full_preserves_image_like_fields(self):
        image_text = "x" * 100
        data = {
            "parameters": {
                "reference_image_multiple": [image_text],
                "director_reference_images": [image_text],
                "image": image_text,
                "mask": image_text,
            }
        }

        sanitized = sanitize_json_for_display(
            data,
            full=True,
            max_image_string_length=12,
        )

        self.assertEqual(sanitized, data)


if __name__ == "__main__":
    unittest.main()
