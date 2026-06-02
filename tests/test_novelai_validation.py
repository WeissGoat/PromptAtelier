import unittest

from tags_machine_core.composers import ScriptComposer
from tags_machine_core.renderers import NovelAIRenderAdapter


class NovelAIValidationTest(unittest.TestCase):
    def setUp(self):
        self.bundle = ScriptComposer().compose_full_prompt(prompt="akemi homura, standing")
        self.adapter = NovelAIRenderAdapter()

    def test_explicit_negative_seed_is_rejected(self):
        with self.assertRaisesRegex(
            ValueError,
            "NovelAI parameter seed must be between 0 and 4294967295, got -1",
        ):
            self.adapter.build_request(self.bundle, seed=-1)

    def test_params_negative_seed_is_rejected(self):
        with self.assertRaisesRegex(
            ValueError,
            "NovelAI parameter seed must be between 0 and 4294967295, got -1",
        ):
            self.adapter.build_request(self.bundle, params={"seed": -1})

    def test_params_seed_is_validated_even_when_explicit_seed_exists(self):
        with self.assertRaisesRegex(
            ValueError,
            "NovelAI parameter seed must be between 0 and 4294967295, got -1",
        ):
            self.adapter.build_request(self.bundle, seed=123, params={"seed": -1})

    def test_invalid_n_samples_is_rejected(self):
        with self.assertRaisesRegex(
            ValueError,
            "NovelAI parameter n_samples must be between 1 and 4, got 5",
        ):
            self.adapter.build_request(
                self.bundle,
                width=1024,
                height=1024,
                params={"n_samples": 5},
            )

    def test_fractional_integer_parameter_is_rejected(self):
        with self.assertRaisesRegex(
            ValueError,
            "NovelAI parameter steps must be between 1 and 50, got 3.5",
        ):
            self.adapter.build_request(self.bundle, params={"steps": 3.5})

    def test_omitted_seed_still_generates_valid_seed(self):
        request = self.adapter.build_request(self.bundle)

        self.assertGreaterEqual(request.params["seed"], 0)
        self.assertLessEqual(request.params["seed"], 4294967295)
        self.assertEqual(request.params["extra_noise_seed"], request.params["seed"])

    def test_valid_seed_is_preserved(self):
        request = self.adapter.build_request(self.bundle, seed=123)

        self.assertEqual(request.seed, 123)
        self.assertEqual(request.params["seed"], 123)
        self.assertEqual(request.params["extra_noise_seed"], 123)


if __name__ == "__main__":
    unittest.main()
